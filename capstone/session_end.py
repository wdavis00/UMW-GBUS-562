"""The end of a session: the view a user confirms or pauses with, the frozen basis, and what is kept.

Everything here is plain code working from the semantic basis the Framer built at /end. No model is
called and nothing is reworded. The view the user inspects and every file kept afterwards are
rendered from that one basis. Kept files may hold private content, so their folder is ignored by git.
"""

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

import outputs
from outputs import CONFIRM_LIMIT, CONFIRM_MEANING, PAUSE_MEANING, amount_label  # noqa: F401 (kept for callers)

STATUS_LINES = {"confirm": "CONFIRMED BY THE USER", "pause": "PAUSED, NOT CONFIRMED"}
MEANINGS = {"confirm": f"{CONFIRM_MEANING}\n{CONFIRM_LIMIT}", "pause": PAUSE_MEANING}
REPORT_FILE, HANDOFF_FILE = "problem-framing-report.md", "ai-handoff.md"
BASIS_FILE, RECORD_FILE = "basis.json", "session-record.txt"


def can_confirm(basis: dict, held: list[dict]) -> bool:
    """Whether there is a problem statement to confirm, with no amount held as unsupported."""
    return bool(basis["understanding"]["statement"].strip()) and not held


def understanding(basis: dict, held: list[dict]) -> str:
    """Return the basis as the view the user confirms or pauses with."""
    parts = ["Where your understanding stands"]
    for heading, blocks in outputs.framing_sections(basis, held, outputs.STATEMENT_LABELS["view"]):
        lines = [heading]
        for block in blocks:
            lines += [f"- {item}" for item in block] if isinstance(block, list) else [block]
        parts.append("\n".join(lines))
    parts.append("An Independent Review is added to the report after you confirm or pause. It does not change any of this.")
    return "\n\n".join(parts)


def freeze(basis: dict, held: list[dict], choice: str, ended: datetime) -> dict:
    """Return the session's fixed framing state: the basis the user saw, with the status they chose."""
    return copy.deepcopy({"status": choice, "ended": ended.isoformat(timespec="seconds"), "held": held, "basis": basis})


def fingerprint(record: dict) -> str:
    """A hash of the frozen state. It must be the same after the review as before it."""
    text = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def session_record(record: dict, view: str, said: list[str]) -> str:
    """Return the working record. The user's own words are kept so meaning and corrections are not lost."""
    choice = record["status"]
    return "\n\n".join([
        "SESSION RECORD\nA working record of one session. The Problem-Framing Report and the AI handoff are kept beside it.",
        f"Status: {STATUS_LINES[choice]}\n{MEANINGS[choice]}",
        f"Ended: {record['ended']}",
        view,
        "What the user said, in their own words. Some of it may since have been corrected or superseded. Where\n"
        "things stand is above.\n" + "\n".join(f"- {message}" for message in said),
    ]) + "\n"


def keep(folder: Path, session_id: str, ended: datetime, files: dict[str, str]) -> Path:
    """Create a new session folder and write files into it. Never overwrites. Raises OSError on failure."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"session-{ended.strftime('%Y%m%dT%H%M%S')}-{session_id}"
    path.mkdir()
    add(path, files)
    return path


def add(path: Path, files: dict[str, str]) -> None:
    """Write new files into an existing session folder. Never overwrites."""
    for name, text in files.items():
        with (path / name).open("x", encoding="utf-8") as file:
            file.write(text)
