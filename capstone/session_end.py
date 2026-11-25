"""The end of a session: the view a user confirms or pauses with, and the copy that is kept.

Everything here is plain code working from the last result. No model is called and nothing is
reworded. A kept copy may hold private content, so its folder is ignored by git. It is a working
record. It is not a reviewed Problem-Framing Report.
"""

from datetime import datetime
from pathlib import Path

CONFIRM_MEANING = (
    "This accurately represents my current understanding for now, including appropriately represented "
    "beliefs, unknowns and unresolved material."
)
CONFIRM_LIMIT = (
    "Confirming does not mean that anything here is proven or complete, and it does not turn an assumption "
    "into a fact or make one of the tool's assumptions yours."
)
PAUSE_MEANING = (
    "This captures useful progress and known state, but I am not confirming the integrated understanding yet."
)
STATUS_LINES = {"confirm": "CONFIRMED BY THE USER", "pause": "PAUSED, NOT CONFIRMED"}
MEANINGS = {"confirm": f"{CONFIRM_MEANING}\n{CONFIRM_LIMIT}", "pause": PAUSE_MEANING}


def amount_label(item: dict) -> str:
    """Return one quantity the user did not supply, with its basis."""
    if item["basis"] == "derived":
        return f"{item['value']} (derived from {', '.join(item['from'])}): {item['note']}"
    return f"{item['value']} ({item['basis'].replace('_', ' ')}, not established): {item['note']}"


def can_confirm(result: dict | None, current: bool) -> bool:
    """Whether there is a described problem to confirm that reflects the user's latest message."""
    return bool(result and current and result["status"] == "ready" and result["draft_statement"].strip())


def understanding(result: dict | None, current: bool) -> str:
    """Return the last result as one view of where the user's understanding stands."""
    if result is None:
        return "There is no understanding to show yet."
    parts = ["Where your understanding stands"]
    if not current:
        parts.append("Your latest message could not be processed, so it is not reflected below.")

    def section(title: str, items: list[str]) -> None:
        if items:
            parts.append(title + "\n" + "\n".join(f"- {item}" for item in items))

    section("What you have told me:", result["stated"])
    section("Beliefs and assumptions, not established:", result["assumptions"])
    section("Not known yet:", result["unknowns"])
    section("A solution you have raised, kept apart from the problem:",
            [result["proposed_solution"]] if result["proposed_solution"] else [])
    section("Amounts you did not give me:", [amount_label(item) for item in result["quantities"]])
    if result["draft_statement"]:
        parts.append("The problem in brief (draft wording):\n" + result["draft_statement"])
    else:
        parts.append("There is not enough yet for a problem statement.")
    parts.append("Where we stopped:\n" + result["next_question"])
    parts.append("No independent review is included.")
    return "\n\n".join(parts)


def session_record(choice: str, view: str, said: list[str], ended: datetime) -> str:
    """Return the text to keep. The user's own words are kept so meaning and corrections are not lost."""
    return "\n\n".join([
        "SESSION RECORD\nA working record of one session. It is not a reviewed Problem-Framing Report.",
        f"Status: {STATUS_LINES[choice]}\n{MEANINGS[choice]}",
        f"Ended: {ended.isoformat(timespec='seconds')}",
        view,
        "What the user said, in their own words. Some of it may since have been corrected or superseded. Where\n"
        "things stand is above.\n" + "\n".join(f"- {message}" for message in said),
    ]) + "\n"


def keep(folder: Path, text: str, session_id: str, ended: datetime) -> Path:
    """Write a new file and return its path. Never overwrites. Raises OSError if it cannot be written."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"session-{ended.strftime('%Y%m%dT%H%M%S')}-{session_id}.txt"
    with path.open("x", encoding="utf-8") as file:
        file.write(text)
    return path
