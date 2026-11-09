#!/usr/bin/env python3
"""hr_mcp_server.py - MCP server with Hartwell Foods HR tools for AI apps.

Tools
  search_policy(query)     Semantic search of the HR documents in hartwell-hr/hr-docs/.
                           Returns the 4 closest chunks, each with its source file.
  get_leave_balance(...)   Leave balances from hartwell-hr/employees.csv.
                           - HR staff mode (default): takes an employee's work email.
                           - Employee mode (--as-employee EMAIL): takes no inputs and can
                             only return that one employee's balance.

The search uses the same approach as week-03/ask.py: one chunk per document section, each
chunk starting with "<title> - <section>", the source file, and the version line, stored in a
Chroma database with Chroma's built-in all-MiniLM-L6-v2 embeddings. The database lives in
week-04/chroma_db/ (git-ignored). It is built on first use and rebuilt automatically when the
documents change; --rebuild forces a rebuild.

The server never calls Claude and needs no API key: the client (Claude Code or an agent)
reads the chunks and writes the answer.

Usage (run from the repo root, using the repo's .venv):
  .venv/bin/python week-04/hr_mcp_server.py                                  # HR staff mode
  .venv/bin/python week-04/hr_mcp_server.py --as-employee dana.whitfield@hartwellfoods.example
  .venv/bin/python week-04/hr_mcp_server.py --rebuild        # rebuild the database, then exit
  .venv/bin/python week-04/hr_mcp_server.py --list-chunks    # print every chunk, then exit

The server talks MCP over stdio, so stdout is reserved for protocol messages: everything
else (progress, warnings) goes to stderr.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path

# --------------------------------------------------------------------------------------
# Configuration (paths are relative to this file, so the server works from any directory)
# --------------------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent             # .../UMW-GBUS-562/week-04
DATA_DIR = HERE / "hartwell-hr"
DOCS_DIR = DATA_DIR / "hr-docs"
EMPLOYEES_CSV = DATA_DIR / "employees.csv"
DB_DIR = HERE / "chroma_db"                        # git-ignored (chroma_db/ in .gitignore)
COLLECTION_NAME = "hr_docs"

TOP_K = 4
MAX_CHUNK_CHARS = 1600   # sections longer than this are split at paragraph breaks
SUPPORTED_SUFFIXES = {".html", ".htm"}
BALANCE_FIELDS = ("vacation_days_left", "sick_days_left", "personal_days_left")


def log(message: str) -> None:
    """Write a message to stderr (stdout carries the MCP protocol)."""
    print(message, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------------------
# Parsing and chunking (adapted from week-03/ask.py, HTML only)
# --------------------------------------------------------------------------------------

@dataclass
class Section:
    heading: str
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class ParsedDoc:
    title: str
    meta: str            # version / owner line, may be empty
    sections: list[Section]
    contact: str = ""    # footer contact line, may be empty


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict


def clean(text: str) -> str:
    """Collapse runs of whitespace into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def pretty_name(path: Path) -> str:
    """'leave-policy.html' -> 'Leave Policy'."""
    return re.sub(r"[-_]+", " ", path.stem).strip().title()


def parse_html(path: Path) -> ParsedDoc:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")

    contact = ""
    footer = soup.find("footer")
    if footer:
        contact = clean(footer.get_text(" "))

    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()

    root = soup.find("main") or soup.find("article") or soup.body or soup

    h1 = root.find("h1")
    if h1:
        title = clean(h1.get_text(" "))
    elif soup.title and soup.title.string:
        title = clean(soup.title.string.split("|")[0])
    else:
        title = pretty_name(path)

    meta_tag = root.find(class_="meta")
    meta = clean(meta_tag.get_text(" ")) if meta_tag else ""

    # Walk the top-level content blocks in document order. A block nested inside another
    # block (e.g. a <p> inside an <li>) is read as part of its parent, so nothing is doubled.
    block_tags = ["h1", "h2", "h3", "h4", "p", "li", "table", "pre", "blockquote", "dt", "dd"]
    sections: list[Section] = [Section(heading="Overview")]
    h2_heading = None
    for el in root.find_all(block_tags):
        if el is h1 or el is meta_tag:
            continue
        if any(parent.name in block_tags for parent in el.parents if parent is not root):
            continue
        if el.name in ("h2", "h3", "h4"):
            text = clean(el.get_text(" "))
            if el.name == "h2" or h2_heading is None:
                h2_heading = text
                heading = text
            else:  # sub-heading: keep the parent heading for context
                heading = f"{h2_heading} > {text}"
            sections.append(Section(heading=heading))
            continue
        if el.name == "li":
            text = "- " + clean(el.get_text(" "))
        elif el.name == "table":
            rows = [
                " | ".join(clean(c.get_text(" ")) for c in tr.find_all(["th", "td"]))
                for tr in el.find_all("tr")
            ]
            text = "\n".join(r for r in rows if r)
        else:
            text = clean(el.get_text(" "))
        if text:
            sections[-1].paragraphs.append(text)

    return ParsedDoc(title=title, meta=meta, sections=sections, contact=contact)


def split_long(paragraphs: list[str]) -> list[list[str]]:
    """Group paragraphs into parts no longer than MAX_CHUNK_CHARS (never splitting a paragraph)."""
    parts, current, size = [], [], 0
    for p in paragraphs:
        if current and size + len(p) > MAX_CHUNK_CHARS:
            parts.append(current)
            current, size = [], 0
        current.append(p)
        size += len(p) + 1
    if current:
        parts.append(current)
    return parts


def chunk_document(path: Path, docs_dir: Path) -> tuple[list[Chunk], str]:
    """Return (chunks, contact_line) for one file."""
    doc = parse_html(path)
    rel = path.relative_to(docs_dir).as_posix()
    status = "superseded" if "supersed" in doc.meta.lower() else "current"

    chunks: list[Chunk] = []
    for section in doc.sections:
        if not section.paragraphs:
            continue
        parts = split_long(section.paragraphs)
        for part_no, paragraphs in enumerate(parts, start=1):
            heading = section.heading
            if len(parts) > 1:
                heading += f" (part {part_no} of {len(parts)})"
            header = [f"{doc.title} - {heading}", f"Source file: {rel}"]
            if doc.meta:
                header.append(f"Version: {doc.meta}")
            text = "\n".join(header) + "\n\n" + "\n".join(paragraphs)
            metadata = {
                "source": rel,
                "title": doc.title,
                "section": heading,
                "version": doc.meta,
                "status": status,
                "chunk_index": len(chunks),
            }
            chunks.append(Chunk(id=f"{rel}::{len(chunks)}", text=text, metadata=metadata))
    return chunks, doc.contact


def find_documents(docs_dir: Path) -> list[Path]:
    """Supported files under docs_dir, skipping hidden files; others are logged and skipped."""
    files = []
    for p in sorted(docs_dir.rglob("*")):
        if not p.is_file() or any(part.startswith(".") for part in p.relative_to(docs_dir).parts):
            continue
        if p.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(p)
        else:
            log(f"  skipped (unsupported file type): {p.relative_to(docs_dir)}")
    return files


def build_chunks(docs_dir: Path) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    contacts: dict[str, str] = {}  # contact line -> first file it appeared in
    for path in find_documents(docs_dir):
        try:
            chunks, contact = chunk_document(path, docs_dir)
        except Exception as e:  # one bad file shouldn't stop the whole index
            log(f"  skipped {path.relative_to(docs_dir)}: {e}")
            continue
        all_chunks.extend(chunks)
        if contact and contact not in contacts:
            contacts[contact] = path.relative_to(docs_dir).as_posix()
        log(f"  {path.relative_to(docs_dir)}: {len(chunks)} chunks")

    # Footer contact lines are usually identical on every page; store each distinct one once.
    for i, (contact, source) in enumerate(contacts.items()):
        all_chunks.append(Chunk(
            id=f"contact::{i}",
            text=f"Contact information\nSource file: {source}\n\n{contact}",
            metadata={"source": source, "title": "Contact information", "section": "Contact",
                      "version": "", "status": "current", "chunk_index": 0},
        ))
    return all_chunks


# --------------------------------------------------------------------------------------
# Chroma database
# --------------------------------------------------------------------------------------

_index_lock = threading.Lock()   # tools run in worker threads; build/open one at a time
_collection = None


def docs_fingerprint() -> str:
    """Hash of every document's contents, used to notice added/removed/changed files."""
    return json.dumps({
        p.relative_to(DOCS_DIR).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        for p in find_documents(DOCS_DIR)
    }, sort_keys=True)


def chroma_client():
    import chromadb
    from chromadb.config import Settings
    return chromadb.PersistentClient(path=str(DB_DIR), settings=Settings(anonymized_telemetry=False))


def embedding_function():
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    return DefaultEmbeddingFunction()  # Chroma's built-in all-MiniLM-L6-v2 (runs locally)


def build_index():
    """(Re)build the database from DOCS_DIR and return the collection."""
    if not DOCS_DIR.is_dir():
        raise RuntimeError(f"HR documents folder not found: {DOCS_DIR}")
    log(f"Building the HR document index from {DOCS_DIR} ...")
    chunks = build_chunks(DOCS_DIR)
    if not chunks:
        raise RuntimeError(f"No chunks were created - is {DOCS_DIR} empty?")

    # Keep any stray output from Chroma or the embedding-model download off stdout.
    with contextlib.redirect_stdout(sys.stderr):
        client = chroma_client()
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass  # didn't exist yet
        collection = client.create_collection(
            name=COLLECTION_NAME,
            embedding_function=embedding_function(),
            configuration={"hnsw": {"space": "cosine"}},
            metadata={
                "fingerprint": docs_fingerprint(),
                "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        collection.add(
            ids=[c.id for c in chunks],
            documents=[c.text for c in chunks],
            metadatas=[c.metadata for c in chunks],
        )
    log(f"Stored {len(chunks)} chunks in {DB_DIR}")
    return collection


def get_collection():
    """Return the collection, building it if missing or rebuilding it if the docs changed."""
    global _collection
    with _index_lock:
        current = docs_fingerprint()
        if _collection is None and DB_DIR.is_dir():
            with contextlib.redirect_stdout(sys.stderr):
                try:
                    _collection = chroma_client().get_collection(
                        COLLECTION_NAME, embedding_function=embedding_function())
                except Exception:
                    _collection = None
        if (_collection is None or _collection.count() == 0
                or (_collection.metadata or {}).get("fingerprint") != current):
            if _collection is not None:
                log("HR documents changed since the index was built; rebuilding.")
            _collection = build_index()
        return _collection


def retrieve(query: str, k: int = TOP_K) -> list[dict]:
    collection = get_collection()
    with contextlib.redirect_stdout(sys.stderr):
        res = collection.query(query_texts=[query], n_results=k,
                               include=["documents", "metadatas", "distances"])
    hits = []
    for rank, (text, meta, dist) in enumerate(
        zip(res["documents"][0], res["metadatas"][0], res["distances"][0]), start=1
    ):
        hits.append({
            "rank": rank,
            "source_file": meta["source"],
            "document_title": meta["title"],
            "section": meta["section"],
            "version": meta.get("version", ""),
            "status": meta.get("status", "current"),
            "similarity": round(1.0 - dist, 3),
            "text": text,
        })
    return hits


# --------------------------------------------------------------------------------------
# Employee records
# --------------------------------------------------------------------------------------

def normalize_email(value: str) -> str:
    """'Dana <Dana.Whitfield@x.example> ' -> 'dana.whitfield@x.example'."""
    return parseaddr(value or "")[1].strip().lower()


def find_employee(email: str) -> dict | None:
    """Exact (case-insensitive) email match in employees.csv, re-read on every call."""
    wanted = normalize_email(email)
    if not wanted:
        return None
    with EMPLOYEES_CSV.open(newline="", encoding="utf-8") as f:
        matches = [row for row in csv.DictReader(f)
                   if normalize_email(row.get("email", "")) == wanted]
    return matches[0] if len(matches) == 1 else None


def no_record_error(email: str):
    from mcp.server.mcpserver.exceptions import ToolError
    return ToolError(
        f"No employee record matches '{email}'. Do not state, estimate, or guess any leave "
        "balance for this person. Say that their leave balance could not be found and that a "
        "person from HR will follow up."
    )


def balance_for(email: str) -> dict:
    row = find_employee(email)
    if row is None:
        raise no_record_error(email)
    try:
        balances = {name: int(row[name]) for name in BALANCE_FIELDS}
    except (KeyError, TypeError, ValueError):
        raise no_record_error(email) from None  # incomplete record: don't guess a number
    return {
        "email": row["email"],
        "name": row["name"],
        "department": row["department"],
        "manager": row["manager"] or None,
        **balances,
        "source_file": "employees.csv",
    }


# --------------------------------------------------------------------------------------
# MCP server
# --------------------------------------------------------------------------------------

def create_server(as_employee: str | None):
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    read_only = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)

    if as_employee:
        instructions = (f"HR tools for Hartwell Foods, limited to one employee ({as_employee}). "
                        "Policy facts and leave numbers must come from these tools.")
    else:
        instructions = ("HR tools for Hartwell Foods HR staff. Policy facts and leave numbers "
                        "must come from these tools.")
    mcp = MCPServer(name="hartwell-hr", instructions=instructions)

    @mcp.tool(annotations=read_only)
    def search_policy(query: str) -> dict:
        """Search Hartwell Foods' HR policy documents (vacation and time off, parental and
        family leave, benefits enrollment, remote work, reporting workplace concerns).

        Returns the 4 document chunks closest to the query, best match first. Each result has
        the source file, document title, section, version/status, a similarity score, and the
        chunk text. Base policy statements only on this text, cite the source_file for each
        fact, and prefer chunks whose status is "current" over "superseded" ones.

        Args:
            query: What to look up, in plain words, e.g. "carry over unused vacation days".
        """
        query = (query or "").strip()
        if not query:
            from mcp.server.mcpserver.exceptions import ToolError
            raise ToolError("The search query is empty.")
        return {"query": query, "results": retrieve(query)}

    if as_employee:
        @mcp.tool(annotations=read_only)
        def get_leave_balance() -> dict:
            """Get the leave balance of the employee this server is limited to: days of
            vacation, sick, and personal leave left this year, plus name, department, and
            manager. It cannot look up any other employee."""
            return balance_for(as_employee)
    else:
        @mcp.tool(annotations=read_only)
        def get_leave_balance(email: str) -> dict:
            """Get an employee's leave balance: days of vacation, sick, and personal leave
            left this year, plus name, department, and manager. For HR staff.

            Args:
                email: The employee's work email, e.g. "dana.whitfield@hartwellfoods.example".
                    Must match exactly (case doesn't matter); names are not accepted.
            """
            return balance_for(email)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP server with Hartwell Foods HR tools.")
    parser.add_argument("--as-employee", metavar="EMAIL",
                        help="limit get_leave_balance to this one employee (it then takes no inputs)")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild the Chroma database from the HR documents, then exit")
    parser.add_argument("--list-chunks", action="store_true",
                        help="print every chunk the HR documents produce, then exit")
    args = parser.parse_args()

    if args.list_chunks:
        for c in build_chunks(DOCS_DIR):
            print(f"\n===== {c.id}  ({len(c.text)} chars)\n{c.text}")
        return
    if args.rebuild:
        global _collection
        with _index_lock:
            _collection = build_index()
        return

    as_employee = None
    if args.as_employee is not None:
        as_employee = normalize_email(args.as_employee)
        if not as_employee:
            parser.error(f"--as-employee needs an email address, got {args.as_employee!r}")
        if find_employee(as_employee) is None:
            log(f"Warning: no record in employees.csv matches {as_employee}; "
                "get_leave_balance will return an error.")

    get_collection()  # open (or build) the index now, so the first search is fast
    log(f"hartwell-hr MCP server ready ({'employee: ' + as_employee if as_employee else 'HR staff mode'}).")
    create_server(as_employee).run("stdio")


if __name__ == "__main__":
    main()
