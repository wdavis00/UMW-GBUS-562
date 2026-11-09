#!/usr/bin/env python3
"""agent.py - command-line agent that drafts replies to HR emails for any organization.

--org PATH names the organization folder (default week-04/hartwell-hr). It must hold
hr-docs/, employees.csv and system_prompt.txt directly; the system prompt is read from it
and the MCP server is started with the same --org (its own Chroma database, its own
employee-file columns). A path that isn't found from the current directory is also tried
inside week-04/, so --org ridgeline-hotels works too.

Ways to run it:

  --email FILE   Handle one email file. save_reply writes a text draft to week-04/drafts/
                 (week-04/drafts/<org folder>/ for organizations other than the default).
  --inbox        Sign in to the Gmail sandbox with IMAP (same login as load_inbox.py, from
                 Agent-Email.txt in the folder above the repository) and handle each unread
                 email in INBOX, one at a time, each as its own separate agent run:
                   - the email is marked as read BEFORE the run starts, so it is never
                     handled twice (even if the run fails);
                   - save_reply creates a real Gmail draft replying to the sender in the same
                     thread. If needs_human_review is true, the draft is flagged three ways:
                     its subject starts with "[NEEDS HR REVIEW]", a warning is placed at the
                     top of its body, and the Gmail label "NEEDS HR REVIEW" is added to the
                     thread (the original email and the draft).
                 --inbox only reads mail and creates drafts. It never sends.
  --watch        Every 30 seconds, check for unread mail and handle it as in --inbox, with
                 these rules enforced in code (not left to Claude):
                   - only senders listed in Agent-Allowlist.txt (beside Agent-Email.txt) are
                     handled, one "real@address = employee@company.example" per line;
                     anyone else's mail is left unread and never sent to Claude;
                   - an allowed sender is treated as the employee named on their line;
                   - automatic mail (Auto-Submitted, or Precedence bulk/auto_reply) is ignored;
                   - after save_reply, if needs_human_review is false the code sends the reply
                     with Gmail SMTP (same login); otherwise it stays a draft. Claude has no
                     send tool;
                   - at most 5 replies are sent, then it stops; Ctrl+C also stops it;
                   - the real addresses and the password are never printed or saved.

For every email the agent:
  1. reads the sender's address from the From: header,
  2. starts hr_mcp_server.py --as-employee <sender> and offers Claude that server's tools,
  3. adds one local tool, save_reply (reply text + needs_human_review),
  4. runs Claude's tool-use loop until Claude replies without requesting a tool, or until
     10 tool calls have been made, and says why it stopped.

Each run prints the sender and subject first, then each step: the tool, its inputs, and the
first 300 characters of its result. At the end it prints a line containing only DRAFT, the
reply text, a line "Needs human review: true" or "Needs human review: false", and the run's
input and output tokens.

--save FILE also writes everything printed to FILE (UTF-8). It works with every mode.

The system prompt is re-read from <org folder>/system_prompt.txt on every run.

Secrets: the Anthropic API key (ANTHROPIC_API_KEY, or API-Key.txt / APIKey.txt above the repo)
and the Gmail app password (Agent-Email.txt above the repo) are read at run time only. They
are never printed, logged, or written to any file.

Usage (from the repo root):
  .venv/bin/python week-04/agent.py --email week-04/hartwell-hr/sample-emails/03-megan-time-off.eml
  .venv/bin/python week-04/agent.py --org week-04/ridgeline-hotels \
      --email week-04/ridgeline-hotels/sample-emails/01-jenna-pto.eml --save week-04/runs/ridgeline-01.txt
  .venv/bin/python week-04/agent.py --inbox
  .venv/bin/python week-04/agent.py --inbox --save week-04/runs/inbox-run.txt
  .venv/bin/python week-04/agent.py --watch --save week-04/runs/watch-run.txt
"""

from __future__ import annotations

import argparse
import asyncio
import imaplib
import json
import os
import re
import smtplib
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path
from typing import Callable

import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent                 # .../UMW-GBUS-562/week-04
REPO_ROOT = HERE.parent                                # .../UMW-GBUS-562
KEY_FILES = [REPO_ROOT.parent / "API-Key.txt", REPO_ROOT.parent / "APIKey.txt"]
SERVER_SCRIPT = HERE / "hr_mcp_server.py"
DRAFTS_DIR = HERE / "drafts"

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096
MAX_TOOL_CALLS = 10
PREVIEW_CHARS = 300

# Organization folder; main() sets it from --org (default week-04/hartwell-hr).
sys.path.insert(0, str(HERE))
from hr_mcp_server import DEFAULT_ORG_DIR, resolve_org  # noqa: E402
ORG_DIR: Path = DEFAULT_ORG_DIR

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
INBOX = "INBOX"

# --watch settings (enforced in code, not by Claude)
ALLOWLIST_FILE = REPO_ROOT.parent / "Agent-Allowlist.txt"   # beside Agent-Email.txt
WATCH_INTERVAL_SECONDS = 30
MAX_SENT_REPLIES = 5
AUTO_PRECEDENCE = {"bulk", "auto_reply"}
REVIEW_PREFIX = "[NEEDS HR REVIEW]"
REVIEW_LABEL = "NEEDS HR REVIEW"     # Gmail label added to the thread (original + draft)
# Put at the top of the draft body; unlike the subject, Gmail never hides body text.
REVIEW_WARNING = (
    "[NEEDS HR REVIEW]\n"
    "WARNING: This draft was prepared by the HR assistant and must be reviewed by a person "
    "from HR before it is sent. Delete this warning before sending.\n"
    "------------------------------------------------------------\n\n"
)

SAVE_REPLY_TOOL = {
    "name": "save_reply",
    "description": (
        "Save the finished reply to the employee as a draft for the HR team to review. "
        "This only saves the draft; it never sends anything. Call it exactly once, at the end."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reply_text": {
                "type": "string",
                "description": "The full text of the reply email to the employee.",
            },
            "needs_human_review": {
                "type": "boolean",
                "description": (
                    "true if a person from HR must handle or check this before anything is "
                    "sent (sensitive topics, or the policies don't answer the question); "
                    "otherwise false."
                ),
            },
        },
        "required": ["reply_text", "needs_human_review"],
        "additionalProperties": False,
    },
}

# In --watch mode the code (not Claude) sends replies that don't need review, so the tool
# description tells Claude what its needs_human_review choice will cause.
SAVE_REPLY_TOOL_WATCH = {
    **SAVE_REPLY_TOOL,
    "description": (
        "Finish the reply to the employee. Call it exactly once, at the end. "
        "If needs_human_review is false, the reply is sent to the employee automatically, "
        "with no further human check. If needs_human_review is true, it is kept as a draft "
        "for a person from HR to review. When in doubt, set needs_human_review to true."
    ),
}


# --------------------------------------------------------------------------------------
# Output: print to the screen and, with --save, to a UTF-8 file as well
# --------------------------------------------------------------------------------------

class Tee:
    """File-like object that writes to several streams (screen + --save file)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            s.write(text)
        return len(text)

    def flush(self):
        for s in self.streams:
            s.flush()


class Redactor:
    """File-like wrapper that replaces secret strings before anything reaches the screen or
    the --save file. --watch uses it for the real Gmail addresses and the password."""

    def __init__(self, stream, replacements: dict[str, str]):
        self.stream = stream
        self.map = {k.lower(): v for k, v in replacements.items() if k}
        keys = sorted(self.map, key=len, reverse=True)
        self.pattern = re.compile("|".join(re.escape(k) for k in keys), re.IGNORECASE) if keys else None

    def write(self, text):
        if self.pattern:
            text = self.pattern.sub(lambda m: self.map[m.group(0).lower()], text)
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()


# --------------------------------------------------------------------------------------
# Emails
# --------------------------------------------------------------------------------------

@dataclass
class Email:
    label: str            # shown in output, used for draft file names
    address: str          # sender's address (lowercase)
    name: str
    subject: str
    body: str
    message_id: str = ""  # original Message-ID, for threading the reply
    references: str = ""  # original References header
    reply_address: str = ""  # --watch: the real address to reply to (never printed)


def parse_email(raw: bytes, label: str) -> Email:
    """Parse raw RFC 822 bytes. Raises ValueError if there's no usable sender address."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    name, address = parseaddr(str(msg.get("From", "")))
    address = address.strip().lower()
    if not address or "@" not in address:
        raise ValueError("no sender address in the From: header")
    part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if part is not None:
        body = part.get_content()
        if part.get_content_type() == "text/html":
            from bs4 import BeautifulSoup
            body = BeautifulSoup(body, "html.parser").get_text("\n")
    # Drop quoted earlier messages ("On <date>, <someone> wrote:" and "> ..." lines).
    body = re.split(r"\n\s*On [^\n]{0,200}?(?:\n[^\n]{0,200}?)?wrote:\s*\n", "\n" + body, maxsplit=1)[0]
    body = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith(">"))
    return Email(
        label=label,
        address=address,
        name=name,
        subject=str(msg.get("Subject", "")),
        body=body.strip(),
        message_id=str(msg.get("Message-ID", "")).strip(),
        references=str(msg.get("References", "")).strip(),
    )


def header_info(raw: bytes) -> tuple[str, bool]:
    """Return (sender address, is_automatic) from the headers only."""
    msg = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
    sender = parseaddr(str(msg.get("From", "")))[1].strip().lower()
    precedence = str(msg.get("Precedence", "")).strip().lower()
    automatic = msg.get("Auto-Submitted") is not None or precedence in AUTO_PRECEDENCE
    return sender, automatic


def load_allowlist() -> dict[str, str]:
    """Read Agent-Allowlist.txt: 'real@address = employee@company.example' per line.
    Error messages give line numbers only, never the addresses."""
    if not ALLOWLIST_FILE.is_file():
        raise SystemExit(f"Allowlist not found: {ALLOWLIST_FILE.name} (beside Agent-Email.txt).")
    email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    allow: dict[str, str] = {}
    for n, line in enumerate(ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        real, sep, employee = (part.strip().lower() for part in line.partition("="))
        if not sep or not email_re.fullmatch(real) or not email_re.fullmatch(employee):
            raise SystemExit(f"{ALLOWLIST_FILE.name} line {n} isn't 'real address = employee address'.")
        if real in allow and allow[real] != employee:
            raise SystemExit(f"{ALLOWLIST_FILE.name} line {n} lists a sender a second time.")
        allow[real] = employee
    if not allow:
        raise SystemExit(f"{ALLOWLIST_FILE.name} has no entries, so no email would be handled.")
    return allow


def draft_body(reply_text: str, needs_review: bool) -> str:
    body = reply_text.strip() + "\n"
    return REVIEW_WARNING + body if needs_review else body


def reply_subject(subject: str, needs_review: bool) -> str:
    subject = subject.strip()
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}" if subject else "Re: your email"
    return f"{REVIEW_PREFIX} {subject}" if needs_review else subject


# --------------------------------------------------------------------------------------
# Secrets (read at run time; never printed or written)
# --------------------------------------------------------------------------------------

def load_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    for path in KEY_FILES:
        if path.is_file():
            key = path.read_text(encoding="utf-8").strip()
            if key:
                return key
    names = " or ".join(str(p) for p in KEY_FILES)
    raise SystemExit(f"No API key found. Set ANTHROPIC_API_KEY or create {names}.")


# --------------------------------------------------------------------------------------
# Gmail over IMAP: read unread mail, mark read, create drafts. No sending.
# --------------------------------------------------------------------------------------

def read_login() -> tuple[str, str]:
    sys.path.insert(0, str(HERE))
    from load_inbox import load_login  # same login file and parser as load_inbox.py
    return load_login()


class Gmail:
    """Minimal Gmail client: reads mail and creates drafts over IMAP.

    It can send only if created with allow_send=True (used by --watch alone), and then only
    through send_reply(), which the code calls - Claude has no send tool.
    """

    def __init__(self, login: tuple[str, str] | None = None, allow_send: bool = False):
        self.address, password = login or read_login()
        self._password = password if allow_send else None   # kept only for SMTP in --watch
        print(f"Signing in to {IMAP_HOST} as {self.address} ...")
        self.imap = imaplib.IMAP4_SSL(IMAP_HOST)
        try:
            self.imap.login(self.address, password)
        except imaplib.IMAP4.error as e:
            reason = e.args[0].decode(errors="replace") if e.args and isinstance(e.args[0], bytes) else str(e)
            raise SystemExit(f"Sign-in failed: {reason}") from None
        finally:
            del password
        self.drafts = self._find_drafts_mailbox()
        self._select(INBOX)

    def _find_drafts_mailbox(self) -> str:
        """Gmail marks its drafts folder with the \\Drafts attribute (name can be localized)."""
        status, lines = self.imap.list()
        if status == "OK":
            for line in lines or []:
                text = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
                m = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', text)
                if m and "\\drafts" in m.group("flags").lower():
                    return m.group("name").strip().strip('"')
        return "[Gmail]/Drafts"

    def _select(self, mailbox: str, readonly: bool = False) -> None:
        status, data = self.imap.select(f'"{mailbox}"', readonly=readonly)
        if status != "OK":
            raise RuntimeError(f"Could not open mailbox {mailbox}: {data}")

    def unread_uids(self) -> list[bytes]:
        self._select(INBOX)
        status, data = self.imap.uid("SEARCH", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError(f"Could not search the inbox: {data}")
        return data[0].split() if data and data[0] else []

    def fetch(self, uid: bytes) -> tuple[bytes, str]:
        """Return (raw message, Gmail thread id) without marking it read (BODY.PEEK)."""
        self._select(INBOX)
        status, data = self.imap.uid("FETCH", uid, "(X-GM-THRID BODY.PEEK[])")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            raise RuntimeError(f"Could not fetch message UID {uid.decode()}")
        meta, raw = data[0]
        m = re.search(rb"X-GM-THRID (\d+)", meta)
        return raw, (m.group(1).decode() if m else "")

    def mark_read(self, uid: bytes) -> None:
        self._select(INBOX)
        status, data = self.imap.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        if status != "OK":
            raise RuntimeError(f"Could not mark message UID {uid.decode()} as read: {data}")

    def add_label(self, mailbox: str, uid: bytes | str) -> None:
        """Add the Gmail review label to one message (Gmail's X-GM-LABELS IMAP extension)."""
        uid = uid.decode() if isinstance(uid, bytes) else uid
        self._select(mailbox)
        status, data = self.imap.uid("STORE", uid, "+X-GM-LABELS", f'("{REVIEW_LABEL}")')
        if status != "OK":
            raise RuntimeError(f"Gmail refused the label: {data}")

    def ensure_label(self) -> None:
        """Create the review label if it doesn't exist yet (labels are IMAP mailboxes)."""
        status, data = self.imap.create(f'"{REVIEW_LABEL}"')
        if status != "OK" and b"ALREADYEXISTS" not in b" ".join(d for d in data if isinstance(d, bytes)).upper():
            raise RuntimeError(f"Could not create the label {REVIEW_LABEL}: {data}")

    def build_reply(self, original: Email, reply_text: str, needs_review: bool) -> tuple[EmailMessage, str]:
        """Build a reply in the original's thread. Returns (message, body text)."""
        to_addr = original.reply_address or original.address
        msg = EmailMessage()
        msg["From"] = self.address
        if original.reply_address or not original.name:
            msg["To"] = to_addr
        else:
            msg["To"] = f"{original.name} <{to_addr}>"
        msg["Subject"] = reply_subject(original.subject, needs_review)
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.address.split("@")[-1])
        if original.message_id:
            msg["In-Reply-To"] = original.message_id
            msg["References"] = f"{original.references} {original.message_id}".strip()
        body = draft_body(reply_text, needs_review)
        msg.set_content(body)
        return msg, body

    def send_reply(self, original: Email, reply_text: str) -> str:
        """Send a reply that did NOT need review, over Gmail SMTP. Called by code only, and
        only to the allowlisted address the email came from. Returns text for display."""
        if self._password is None:
            raise RuntimeError("sending is not enabled for this connection")
        if not original.reply_address:
            raise RuntimeError("no allowlisted reply address; refusing to send")
        msg, body = self.build_reply(original, reply_text, needs_review=False)
        with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=60) as smtp:
            smtp.login(self.address, self._password)
            refused = smtp.send_message(msg, from_addr=self.address, to_addrs=[original.reply_address])
        if refused:
            raise RuntimeError("Gmail refused the recipient")
        shown = "\n".join(f"{k}: {v}" for k, v in msg.items() if k in ("From", "To", "Subject", "In-Reply-To"))
        return shown + "\n\n" + body

    def create_draft(self, original: Email, original_uid: bytes, reply_text: str,
                     needs_review: bool) -> tuple[str, str, str]:
        """Put a reply draft in the Drafts folder.

        If needs_review: the subject starts with [NEEDS HR REVIEW], a warning goes at the top of
        the body, and the NEEDS HR REVIEW label is added to the original email and the draft.
        Returns (draft text for display, draft thread id, label note).
        """
        msg, body = self.build_reply(original, reply_text, needs_review)

        status, data = self.imap.append(f'"{self.drafts}"', "(\\Draft \\Seen)",
                                        imaplib.Time2Internaldate(time.time()),
                                        msg.as_bytes(policy=policy.SMTP))
        if status != "OK":
            raise RuntimeError(f"Gmail refused the draft: {data}")

        # Look up the new draft's thread id (Gmail returns its UID via APPENDUID).
        thread_id = ""
        m = re.search(rb"APPENDUID \d+ (\d+)", data[0] if data and data[0] else b"")
        draft_uid = m.group(1).decode() if m else ""
        if draft_uid:
            self._select(self.drafts, readonly=True)
            st, fd = self.imap.uid("FETCH", draft_uid, "(X-GM-THRID)")
            if st == "OK" and fd and fd[0]:
                raw = fd[0][0] if isinstance(fd[0], tuple) else fd[0]
                t = re.search(rb"X-GM-THRID (\d+)", raw)
                thread_id = t.group(1).decode() if t else ""

        # Label the thread. A label problem is reported but doesn't undo the saved draft.
        label_note = ""
        if needs_review:
            try:
                self.ensure_label()
                self.add_label(INBOX, original_uid)
                if draft_uid:
                    self.add_label(self.drafts, draft_uid)
                label_note = f'Label "{REVIEW_LABEL}" added to the thread.'
            except Exception as e:
                label_note = f'Could not add the label "{REVIEW_LABEL}": {e}'
        self._select(INBOX)

        shown = "\n".join(f"{k}: {v}" for k, v in msg.items() if k in ("From", "To", "Subject", "In-Reply-To"))
        return shown + "\n\n" + body, thread_id, label_note

    def close(self) -> None:
        self._password = None
        try:
            self.imap.logout()
        except Exception:
            pass


# --------------------------------------------------------------------------------------
# One agent run (one email)
# --------------------------------------------------------------------------------------

# save_fn(reply_text, needs_review) -> (message for Claude, note printed before the draft,
# e.g. where it was saved). run_agent itself prints DRAFT, the reply, and the review flag.
SaveFn = Callable[[str, bool], tuple[str, str]]


def preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "..."


def mcp_result_text(result) -> str:
    parts = []
    for block in result.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
        else:
            parts.append(f"[{getattr(block, 'type', 'unknown')} content omitted]")
    if not parts and result.structured_content is not None:
        parts.append(json.dumps(result.structured_content))
    return "\n".join(parts) or "(empty result)"


async def run_agent(client: anthropic.AsyncAnthropic, email: Email, save_fn: SaveFn,
                    save_tool: dict = SAVE_REPLY_TOOL) -> tuple[int, int]:
    """Handle one email in its own agent run. Returns (input_tokens, output_tokens)."""
    system_prompt = (ORG_DIR / "system_prompt.txt").read_text(encoding="utf-8").strip()

    sender = f"{email.name} <{email.address}>" if email.name else email.address
    print(f"Sender:  {sender}")
    print(f"Subject: {email.subject}")
    print(f"Email:   {email.label}")
    print(f"Org:     {ORG_DIR.name}")
    print(f"Model:   {MODEL}\n")

    server = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT), "--org", str(ORG_DIR), "--as-employee", email.address],
        cwd=str(REPO_ROOT),
    )

    tool_calls = input_tokens = output_tokens = 0
    draft_note = ""
    final_reply: str | None = None
    final_review: bool | None = None
    stop_reason_text = ""

    async with stdio_client(server, errlog=sys.__stderr__) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = (await session.list_tools()).tools
            mcp_tool_names = {t.name for t in mcp_tools}
            tools = [
                {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
                for t in mcp_tools
            ] + [save_tool]
            print(f"Tools offered: {', '.join(t['name'] for t in tools)}\n")

            # The email goes in as data, clearly marked, not as instructions.
            messages = [{
                "role": "user",
                "content": (
                    "Prepare a reply to this employee email.\n\n"
                    "<email>\n"
                    f"From: {email.name} <{email.address}>\n"
                    f"Subject: {email.subject}\n\n"
                    f"{email.body}\n"
                    "</email>"
                ),
            }]

            while True:
                response = await client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=system_prompt,
                    tools=tools,
                    messages=messages,
                )
                input_tokens += response.usage.input_tokens
                output_tokens += response.usage.output_tokens

                for block in response.content:
                    if block.type == "text" and block.text.strip():
                        print(f"Claude: {block.text.strip()}\n")

                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason != "tool_use" or not tool_uses:
                    stop_reason_text = (f"Claude replied without requesting a tool "
                                        f"(stop_reason: {response.stop_reason}).")
                    break

                messages.append({"role": "assistant", "content": response.content})
                results = []
                limit_hit = False
                for tu in tool_uses:
                    if tool_calls >= MAX_TOOL_CALLS:
                        limit_hit = True
                        break
                    tool_calls += 1
                    print(f"Step {tool_calls}: {tu.name}")
                    print(f"  inputs: {json.dumps(tu.input, ensure_ascii=False)}")

                    is_error = False
                    if tu.name == "save_reply":
                        reply = tu.input.get("reply_text", "")
                        review = tu.input.get("needs_human_review")
                        if not isinstance(reply, str) or not reply.strip() or not isinstance(review, bool):
                            text = "save_reply needs reply_text (non-empty text) and needs_human_review (true or false)."
                            is_error = True
                        else:
                            try:
                                text, draft_note = save_fn(reply, review)
                                final_reply, final_review = reply, review
                            except Exception as e:
                                text = f"Saving the draft failed: {e}"
                                is_error = True
                    elif tu.name in mcp_tool_names:
                        try:
                            result = await session.call_tool(tu.name, tu.input or {})
                            text = mcp_result_text(result)
                            is_error = bool(result.is_error)
                        except Exception as e:  # report the failure to Claude, don't crash
                            text = f"Tool call failed: {e}"
                            is_error = True
                    else:
                        text = f"Unknown tool: {tu.name}"
                        is_error = True

                    print(f"  result{' (error)' if is_error else ''}: {preview(text)}\n")
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": text, "is_error": is_error})

                if limit_hit or tool_calls >= MAX_TOOL_CALLS:
                    stop_reason_text = f"Stopped after reaching the limit of {MAX_TOOL_CALLS} tool calls."
                    break
                messages.append({"role": "user", "content": results})

    print("-" * 60)
    print(f"Stopped: {stop_reason_text}")
    print("-" * 60)
    if final_reply is not None:
        if draft_note:
            print(draft_note)
        print("DRAFT")
        print(final_reply.strip())
        print(f"Needs human review: {'true' if final_review else 'false'}")
    else:
        print("No draft was saved.")
        print("Needs human review: true")
    print()
    print(f"Tool calls: {tool_calls}")
    print(f"Tokens: {input_tokens} input, {output_tokens} output")
    return input_tokens, output_tokens


# --------------------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------------------

async def run_file(email_path: Path) -> None:
    """--email: one email file; the draft is written to week-04/drafts/."""
    email = parse_email(email_path.read_bytes(), email_path.name)
    client = anthropic.AsyncAnthropic(api_key=load_api_key())

    def save_fn(reply: str, review: bool) -> tuple[str, str]:
        folder = DRAFTS_DIR if ORG_DIR == DEFAULT_ORG_DIR else DRAFTS_DIR / ORG_DIR.name
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", email_path.stem).strip("-") or "email"
        path = folder / f"{slug}-{stamp}.txt"
        content = "\n".join([
            "DRAFT - NOT SENT",
            f"To: {email.address}",
            f"Subject: {reply_subject(email.subject, review)}",
            f"Needs human review: {'true' if review else 'false'}",
            f"Source email: {email_path.name}",
            f"Drafted: {datetime.now().isoformat(timespec='seconds')} by {MODEL}",
            "-" * 60,
        ]) + "\n\n" + draft_body(reply, review)
        path.write_text(content, encoding="utf-8")
        rel = path.relative_to(REPO_ROOT)
        return f"Draft saved to {rel}. It has not been sent.", f"Draft file: {rel}"

    await run_agent(client, email, save_fn)


async def run_inbox() -> None:
    """--inbox: each unread Gmail message, one at a time, as its own agent run."""
    client = anthropic.AsyncAnthropic(api_key=load_api_key())
    gmail = Gmail()
    total_in = total_out = handled = failed = 0
    try:
        uids = gmail.unread_uids()
        print(f"Unread emails in {INBOX}: {len(uids)}  (drafts go to {gmail.drafts})\n")
        for n, uid in enumerate(uids, start=1):
            print("=" * 60)
            print(f"Inbox email {n} of {len(uids)} (UID {uid.decode()})")
            print("=" * 60)
            try:
                raw, thread_id = gmail.fetch(uid)
                gmail.mark_read(uid)   # before working on it, so it's never handled twice
                print("Marked as read.")
                email = parse_email(raw, f"inbox UID {uid.decode()}")
            except Exception as e:
                print(f"Skipped: {e}\n")
                failed += 1
                continue

            def save_fn(reply: str, review: bool, email=email, uid=uid,
                        thread_id=thread_id) -> tuple[str, str]:
                shown, draft_thread, label_note = gmail.create_draft(email, uid, reply, review)
                if thread_id and draft_thread:
                    same = draft_thread == thread_id
                    thread_note = ("in the same thread as the original email" if same
                                   else "but Gmail put it in a different thread")
                else:
                    thread_note = "(thread could not be confirmed)"
                print(f"  Gmail draft created {thread_note}.")
                if label_note:
                    print(f"  {label_note}")
                return (f"Gmail draft created in {gmail.drafts} {thread_note}. "
                        f"{label_note + ' ' if label_note else ''}It has not been sent.",
                        "Gmail draft:\n" + shown.split("\n\n", 1)[0])

            try:
                i, o = await run_agent(client, email, save_fn)
                total_in += i
                total_out += o
                handled += 1
            except anthropic.APIError as e:
                print(f"Claude API error, run abandoned: {e}\n")
                failed += 1
            except Exception as e:
                print(f"Run failed: {e}\n")
                failed += 1
            print()
    finally:
        gmail.close()

    print("=" * 60)
    print(f"Inbox done: {handled} handled, {failed} failed or skipped. Nothing was sent.")
    print(f"Total tokens: {total_in} input, {total_out} output")


async def run_watch() -> None:
    """--watch: every 30 seconds, handle unread mail from allowlisted senders.

    Rules enforced here in code (Claude can't change them):
      - only senders in Agent-Allowlist.txt are handled; other mail is left unread and is
        never sent to Claude;
      - an allowed sender is treated as the employee on their allowlist line;
      - automatic mail (Auto-Submitted header, or Precedence bulk/auto_reply) is ignored;
      - after save_reply: needs_human_review false -> the code sends the reply by SMTP to the
        sender's allowlisted address; true -> it stays a draft. Claude has no send tool;
      - at most MAX_SENT_REPLIES replies are sent, then the watch stops (Ctrl+C also stops it);
      - the real addresses and the password are replaced before any output is printed/saved.
    """
    allow = load_allowlist()
    login = read_login()
    account = login[0].lower()
    if account in allow:
        raise SystemExit(f"{ALLOWLIST_FILE.name} must not list the sandbox account itself "
                         "(its replies would be answered in a loop).")

    # From here on, everything printed (screen and --save file) passes through the redactor.
    replacements = {account: "<sandbox-account>", login[1]: "<redacted>"}
    replacements.update({real: f"<allowed-sender:{emp}>" for real, emp in allow.items()})
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout = Redactor(saved_out, replacements)
    sys.stderr = Redactor(saved_err, replacements)

    client = anthropic.AsyncAnthropic(api_key=load_api_key())
    state = {"sent": 0, "drafted": 0, "runs": 0, "failed": 0, "in": 0, "out": 0}
    passed_over: set[bytes] = set()     # unread mail we chose not to handle (left unread)
    gmail: Gmail | None = None
    stop_reason = ""

    async def handle(uid: bytes) -> None:
        tag = f"UID {uid.decode()}"
        raw, thread_id = gmail.fetch(uid)              # BODY.PEEK: stays unread
        sender, automatic = header_info(raw)
        if sender not in allow:
            print(f"{datetime.now():%H:%M:%S} {tag}: sender not on the allowlist; "
                  "left unread and not sent to Claude.")
            passed_over.add(uid)
            return
        if automatic:
            print(f"{datetime.now():%H:%M:%S} {tag}: automatic mail (Auto-Submitted or "
                  "Precedence); ignored and left unread.")
            passed_over.add(uid)
            return

        print("=" * 60)
        print(f"{datetime.now():%H:%M:%S} {tag} from an allowlisted sender -> handled as {allow[sender]}")
        print("=" * 60)
        gmail.mark_read(uid)                            # before working on it
        print("Marked as read.")
        try:
            email = parse_email(raw, f"inbox {tag}")
        except ValueError as e:
            print(f"Skipped: {e}\n")
            state["failed"] += 1
            return
        email.reply_address = sender                    # real address: replies go here only
        email.address = allow[sender]                   # the employee Claude works for
        email.name = ""

        saved: list[str] = []

        def save_fn(reply: str, review: bool) -> tuple[str, str]:
            if saved:
                raise RuntimeError("save_reply was already called for this email; "
                                   "nothing more was saved or sent")
            if not review and state["sent"] < MAX_SENT_REPLIES:
                shown = gmail.send_reply(email, reply)
                state["sent"] += 1
                saved.append("sent")
                print(f"  Reply SENT by the agent code ({state['sent']} of {MAX_SENT_REPLIES}).")
                return "The reply was sent to the employee.", "Sent:\n" + shown.split("\n\n", 1)[0]
            shown, _, label_note = gmail.create_draft(email, uid, reply, review)
            state["drafted"] += 1
            saved.append("draft")
            why = ("needs_human_review is true" if review
                   else f"the {MAX_SENT_REPLIES}-reply sending limit was reached")
            print(f"  Kept as a Gmail draft ({why}). {label_note}".rstrip())
            return (f"The reply was kept as a draft for HR because {why}. {label_note}".strip(),
                    "Gmail draft:\n" + shown.split("\n\n", 1)[0])

        try:
            i, o = await run_agent(client, email, save_fn, save_tool=SAVE_REPLY_TOOL_WATCH)
            state["in"] += i
            state["out"] += o
            state["runs"] += 1
        except anthropic.APIError as e:
            print(f"Claude API error, run abandoned: {e}\n")
            state["failed"] += 1
        except Exception as e:
            print(f"Run failed: {e}\n")
            state["failed"] += 1
        print()

    try:
        gmail = Gmail(login=login, allow_send=True)
        print(f"Watching {INBOX} every {WATCH_INTERVAL_SECONDS} seconds for allowlisted senders "
              f"({len(allow)} on the list). Sends at most {MAX_SENT_REPLIES} replies. "
              "Press Ctrl+C to stop.\n")
        while not stop_reason:
            try:
                for uid in [u for u in gmail.unread_uids() if u not in passed_over]:
                    await handle(uid)
                    if state["sent"] >= MAX_SENT_REPLIES:
                        stop_reason = f"sent the maximum of {MAX_SENT_REPLIES} replies"
                        break
            except (imaplib.IMAP4.abort, OSError) as e:
                print(f"Connection lost ({type(e).__name__}); reconnecting ...")
                gmail.close()
                gmail = Gmail(login=login, allow_send=True)
                continue
            if not stop_reason:
                await asyncio.sleep(WATCH_INTERVAL_SECONDS)
    except (KeyboardInterrupt, asyncio.CancelledError):
        stop_reason = "stopped with Ctrl+C"
    finally:
        if gmail:
            gmail.close()
        print("=" * 60)
        print(f"Watch ended: {stop_reason or 'stopped by an error'}.")
        print(f"Runs: {state['runs']}  sent: {state['sent']}  kept as drafts: {state['drafted']}  "
              f"failed: {state['failed']}  left unread (not allowlisted or automatic): {len(passed_over)}")
        print(f"Total tokens: {state['in']} input, {state['out']} output")
        sys.stdout.flush()
        sys.stdout, sys.stderr = saved_out, saved_err


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft replies to HR emails for one organization.")
    parser.add_argument("--org", metavar="PATH",
                        help="organization folder holding hr-docs/, employees.csv and "
                             "system_prompt.txt (default: week-04/hartwell-hr)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--email", type=Path, help="path of one email file (.eml)")
    source.add_argument("--inbox", action="store_true",
                        help="handle every unread email in the Gmail sandbox inbox")
    source.add_argument("--watch", action="store_true",
                        help="every 30 s, handle unread mail from allowlisted senders; sends "
                             "replies that don't need review (max 5), Ctrl+C stops")
    parser.add_argument("--save", type=Path, metavar="FILE",
                        help="also write everything printed to FILE (UTF-8)")
    args = parser.parse_args()
    if args.email and not args.email.is_file():
        parser.error(f"email file not found: {args.email}")
    global ORG_DIR
    try:
        ORG_DIR = resolve_org(args.org)
    except ValueError as e:
        parser.error(str(e))

    save_file = None
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        save_file = args.save.open("w", encoding="utf-8")
        sys.stdout = Tee(sys.__stdout__, save_file)

    try:
        if args.watch:
            asyncio.run(run_watch())
        elif args.inbox:
            asyncio.run(run_inbox())
        else:
            asyncio.run(run_file(args.email.resolve()))
    except KeyboardInterrupt:
        print("Stopped with Ctrl+C.")
    except anthropic.APIError as e:
        print(f"Claude API error: {e}")
        raise SystemExit(1)
    except SystemExit as e:
        if isinstance(e.code, str):   # print the message so --save captures it too
            print(e.code)
            raise SystemExit(1)
        raise
    finally:
        if save_file:
            sys.stdout.flush()
            sys.stdout = sys.__stdout__
            save_file.close()
            print(f"Output saved to {args.save}")


if __name__ == "__main__":
    main()
