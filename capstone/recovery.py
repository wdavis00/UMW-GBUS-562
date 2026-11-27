"""Work-in-progress protection: zero or one unfinished session kept on local disk. Plain code, no model.

The recovery file holds only what is needed to continue the same unfinished conversation: the transcript
as the user saw it, the user's own messages, and the session's identity and settings. It is not framing
state and has no authority of its own; the frame is still built from the conversation, exactly as before.
It is written whenever the conversation changes and removed when the session's outputs are safely saved
or the user discards it. Nothing here reads or writes the terminal, so any front end can use it.
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import session_end

FORMAT_VERSION = 1
FIELDS = {"format_version": int, "session_id": str, "created": str, "updated": str, "model": str, "effort": str,
          "transcript": list, "said": list}


class RecoveryError(Exception):
    """The recovery file exists but cannot be trusted. It is never used as input."""


def checksum(payload: dict) -> str:
    """A hash of every field except the checksum itself."""
    body = {k: payload[k] for k in FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def save(path: Path, session_id: str, created: str, model: str, effort: str,
         transcript: list[str], said: list[str]) -> None:
    """Replace the recovery file in one step: write a private temporary file, flush it, then rename it."""
    payload = {"format_version": FORMAT_VERSION, "session_id": session_id, "created": created,
               "updated": datetime.now().astimezone().isoformat(timespec="seconds"), "model": model,
               "effort": effort, "transcript": list(transcript), "said": list(said)}
    payload["checksum"] = checksum(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".active-", suffix=".tmp", dir=path.parent)  # mode 0600
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False, indent=1))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def load(path: Path) -> dict | None:
    """Return the saved unfinished session, None if there is none, or raise RecoveryError if it is unusable."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RecoveryError("The file could not be read.") from None
    if not isinstance(payload, dict) or set(payload) != set(FIELDS) | {"checksum"}:
        raise RecoveryError("The file does not have the expected fields.")
    if not all(isinstance(payload[k], kind) for k, kind in FIELDS.items()) or payload["format_version"] != FORMAT_VERSION:
        raise RecoveryError("The file is from an unknown version or has the wrong types.")
    if payload["checksum"] != checksum(payload):
        raise RecoveryError("The file failed its integrity check.")
    transcript, said = payload["transcript"], payload["said"]
    if not said or not payload["session_id"] or not all(isinstance(x, str) for x in transcript + said):
        raise RecoveryError("The file holds no usable conversation.")
    if not all(line.startswith(("User: ", "Tool: ")) for line in transcript) \
            or [line[len("User: "):] for line in transcript if line.startswith("User: ")] != said:
        raise RecoveryError("The conversation and the user's messages do not match.")
    return payload


def pending(state: dict) -> bool:
    """Whether the last thing in the conversation is a user message that was never answered."""
    return bool(state["transcript"]) and state["transcript"][-1].startswith("User: ")


def completed(sessions: Path, session_id: str) -> Path | None:
    """The saved session folder for this session if its outputs were both written, else None."""
    for folder in sorted(sessions.glob(f"session-*-{session_id}")):
        if (folder / session_end.REPORT_FILE).exists() and (folder / session_end.HANDOFF_FILE).exists():
            return folder
    return None


def set_aside(path: Path) -> Path:
    """Move an unusable recovery file out of the way without deleting it. Return where it went."""
    target = path.with_name(path.name + ".unreadable")
    if target.exists():
        target = path.with_name(f"{path.name}.{datetime.now().strftime('%Y%m%dT%H%M%S')}.unreadable")
    os.replace(path, target)
    return target


def discard(path: Path) -> None:
    """Remove the recovery file. No copy is kept."""
    path.unlink(missing_ok=True)
