"""Problem-framing tool: a Framer that helps one person frame a problem, one question at a time.

The Framer turns what a user has said into a tentative, solution-neutral problem frame and asks
one next question. A code guardrail then holds any framing that presents an unsupported quantity as
established (see guardrail.py). Each turn shows only a brief reflection and the next question; the
whole frame is shown when the user ends the session. Only the user can confirm a frame.

The Reviewer does not run during framing. Its prompt and output format are kept for a later
independent review of the finished frame.

Usage (from the repository root):
    .venv/bin/python capstone/problem_framer.py --request "..."     one turn, prints JSON
    .venv/bin/python capstone/problem_framer.py                     interactive; /end or /quit
    Add --model or --effort to change the model settings.

Files outside the repository, in the folder above it:
    API-Key.txt or APIKey.txt               the API key, read at run time, never printed or written
    Week8/Mitre/framer-guidance.txt         framing guidance for the Framer
    Week8/Mitre/reviewer-criteria.txt       quality guidance for the Reviewer (not used during framing)
    Week8/capstone-runs/run-log.jsonl       provisional diagnostic log

Every request the tool handles is also recorded in capstone/runs/log.jsonl (see request_log.py).
A session the user ends is kept in capstone/sessions, which git ignores (see session_end.py).

The guidance is from the MITRE Innovation Toolkit's Problem Framing tool
(https://itk.mitre.org/toolkit-tools/problem-framing/). MITRE Innovation Toolkit materials are
copyright The MITRE Corporation and remain governed by MITRE's terms, separately from this
repository's license, so their text is kept outside it.
"""

import argparse
import hashlib
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import anthropic

import request_log
import session_end
from guardrail import apply_guardrail, user_words

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TOKENS = 16000

HERE = Path(__file__).resolve().parent
COURSE_DIR = HERE.parent.parent
KEY_FILES = [COURSE_DIR / "API-Key.txt", COURSE_DIR / "APIKey.txt"]
RUN_LOG = COURSE_DIR / "Week8" / "capstone-runs" / "run-log.jsonl"
SESSIONS = HERE / "sessions"
PROMPT_FILES = {"framer": HERE / "prompts" / "framer.txt", "reviewer": HERE / "prompts" / "reviewer.txt"}
GUIDANCE_FILES = {
    "framer": COURSE_DIR / "Week8" / "Mitre" / "framer-guidance.txt",
    "reviewer": COURSE_DIR / "Week8" / "Mitre" / "reviewer-criteria.txt",
}

# How a Reviewer finding is shown. The Framer's context leaves these out (see without_findings).
FINDING_HEADING = "Potential issue: Consider revising"
RECOMMENDATION_HEADING = "Recommendation to strengthen"
SHOWN_FINDING = re.compile(rf"\n\n{FINDING_HEADING}\n[^\n]*\n{RECOMMENDATION_HEADING}\n[^\n]*(?=\n\n|\Z)")
NEXT_SPEAKER = re.compile(r"\n\n(?=(?:User|Tool): )")

BASES = ["derived", "estimate", "assumption", "hypothetical", "placeholder", "pending_validation"]
TEXT = {"type": "string"}
TEXT_LIST = {"type": "array", "items": TEXT}


def object_schema(**properties) -> dict:
    """A JSON schema for an object with exactly these properties, all required."""
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


FRAMER_SCHEMA = object_schema(
    reflection=TEXT,
    stated=TEXT_LIST,
    assumptions=TEXT_LIST,
    unknowns=TEXT_LIST,
    quantities={
        "type": "array",
        "items": object_schema(value=TEXT, basis={"type": "string", "enum": BASES}, **{"from": TEXT_LIST}, note=TEXT),
    },
    proposed_solution=TEXT,
    status={"type": "string", "enum": ["ready", "not_ready"]},
    draft_statement=TEXT,
    next_question=TEXT,
)
REVIEWER_SCHEMA = object_schema(
    findings={"type": "array", "items": object_schema(potential_issue=TEXT, recommendation=TEXT)}
)


class FramingError(Exception):
    """The tool could not produce a usable result. `kind` is a short label for the run log."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass
class Run:
    """Settings and identifiers shared by the model calls of one turn."""

    source: str = "one_turn"  # interactive, one_turn, or evaluation
    case_id: str | None = None
    session_id: str | None = None
    model: str = MODEL
    effort: str = EFFORT
    client: anthropic.Anthropic | None = None
    last_run_id: str | None = None


# --- Files outside the repository -----------------------------------------------------------


def load_api_key() -> str:
    """Return the API key. The key never appears in an error message."""
    for path in KEY_FILES:
        if path.is_file():
            key = path.read_text(encoding="utf-8-sig", errors="replace").strip()
            if not key or not key.isascii() or any(c.isspace() for c in key):
                raise FramingError("key", f"{path.name} does not contain a usable API key.")
            return key
    names = " or ".join(path.name for path in KEY_FILES)
    raise FramingError("key", f"No API key file found. Expected {names} in the folder above the repository.")


def load_system_prompt(role: str) -> str:
    """Return the role's product prompt with its external guidance inserted."""
    prompt_file, guidance_file = PROMPT_FILES[role], GUIDANCE_FILES[role]
    for path in (prompt_file, guidance_file):
        if not path.is_file():
            raise FramingError("missing_file", f"Required file not found for the {role}: {path}")
    lines = guidance_file.read_text(encoding="utf-8").splitlines()
    guidance = "\n".join(line for line in lines if not line.startswith("#")).strip()
    if not guidance:
        raise FramingError("missing_file", f"Required file has no content for the {role}: {guidance_file}")
    return prompt_file.read_text(encoding="utf-8").replace("{{GUIDANCE}}", guidance)


def write_log(record: dict) -> None:
    """Append one record to the provisional run log."""
    record = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
    try:
        RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RUN_LOG.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        raise FramingError("log", f"Could not write the run log: {error.strerror}") from None


# --- Model calls ----------------------------------------------------------------------------


def check_shape(value, schema: dict, where: str) -> None:
    """Raise FramingError unless the value matches the schema (the subset of JSON schema used here)."""
    expected = {"object": dict, "array": list, "string": str}[schema["type"]]
    if not isinstance(value, expected):
        raise FramingError("malformed", f"{where} should be of type {schema['type']}.")
    if "enum" in schema and value not in schema["enum"]:
        raise FramingError("malformed", f"{where} has a value that is not allowed.")
    if expected is list:
        for item in value:
            check_shape(item, schema["items"], f"an item in {where}")
    if expected is dict:
        if set(value) != set(schema["properties"]):
            raise FramingError("malformed", f"{where} does not have exactly the expected fields.")
        for name, subschema in schema["properties"].items():
            check_shape(value[name], subschema, name)


def check_frame(frame: dict) -> None:
    if frame["status"] == "ready" and not frame["draft_statement"].strip():
        raise FramingError("invalid", "The Framer returned ready without a draft statement.")
    if frame["status"] == "not_ready" and frame["draft_statement"]:
        raise FramingError("invalid", "The Framer returned a draft statement with not_ready.")
    if not frame["next_question"].strip():
        raise FramingError("invalid", "The Framer returned no next question.")


def check_review(review: dict) -> None:
    for finding in review["findings"]:
        if not finding["potential_issue"].strip() or not finding["recommendation"].strip():
            raise FramingError("invalid", "The Reviewer returned a finding with an empty part.")


def call_role(role: str, content: str, schema: dict, check, run: Run, run_id: str, request_hash: str,
              request: request_log.RequestRecord) -> dict:
    """Make one model call and return its validated JSON. Every call is logged, including failures."""
    system = load_system_prompt(role)
    record = {
        "event": "model_call",
        "run_id": run_id,
        "session_id": run.session_id,
        "source": run.source,
        "case_id": run.case_id,
        "request_hash": request_hash,
        "role": role,
        "model": run.model,
        "effort": run.effort,
        "prompt_hash": short_hash(system),
        "input_tokens": None,
        "output_tokens": None,
        "elapsed_seconds": None,
        "stop_reason": None,
        "error": None,
    }
    started = time.monotonic()
    request.add_call()
    try:
        try:
            response = run.client.messages.create(
                model=run.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": run.effort, "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIStatusError as error:
            raise FramingError("api_error", f"The API returned an error (status {error.status_code}).") from None
        except anthropic.AnthropicError as error:
            raise FramingError("api_error", f"The API call failed ({type(error).__name__}).") from None
        finally:
            elapsed = time.monotonic() - started
            record["elapsed_seconds"] = round(elapsed, 2)
            request.add_seconds(elapsed)
        record["input_tokens"] = response.usage.input_tokens
        record["output_tokens"] = response.usage.output_tokens
        record["stop_reason"] = response.stop_reason
        request.add_usage(response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason != "end_turn":
            raise FramingError("unusable", f"The {role} gave no complete reply (stop reason: {response.stop_reason}).")
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            raise FramingError("malformed", f"The {role} reply was not valid JSON.") from None
        check_shape(value, schema, f"the {role} reply")
        check(value)
        return value
    except FramingError as error:
        record["error"] = error.kind
        raise
    finally:
        write_log(record)


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def without_findings(conversation: str) -> str:
    """Return the conversation without the Reviewer findings the tool showed.

    Advice the user has not taken up in their own words is not information about the problem. Only
    text labeled as the tool's is changed, so anything the user wrote or pasted is kept.
    """
    parts = NEXT_SPEAKER.split(conversation)
    return "\n\n".join(SHOWN_FINDING.sub("", part) if part.startswith("Tool: ") else part for part in parts)


def frame_turn(conversation: str, run: Run | None = None, user_text: str | None = None) -> dict:
    """Run one framing turn and return the structured V1 result.

    `conversation` is a single request, or a transcript of everything the user was shown and said.
    The evaluation, --request, and the interactive loop all use this function. The loop also passes
    `user_text`, the user's own messages, so that amounts the tool displayed never count as the user's.
    """
    run = run or Run()
    if not conversation.strip():
        raise FramingError("empty", "The request is empty.")
    load_system_prompt("framer")  # fail before any call if a required file is missing
    if run.client is None:
        run.client = anthropic.Anthropic(api_key=load_api_key())
    if not isinstance(run.client, anthropic.Anthropic) and request_log.LOG_FILE == request_log.PRODUCTION_LOG:
        raise FramingError("log", "A stand-in client may not write to the real run log.")

    request = request_log.RequestRecord(run.model, conversation)
    try:
        result = handle_request(conversation, run, user_text, request)
    except BaseException as error:
        if request.calls:  # work was done, so the request is recorded even though it failed
            append_request(request, f"Error: {public_reason(error)}")
        raise
    append_request(request, json.dumps(result, ensure_ascii=False))
    return result


def public_reason(error: BaseException) -> str:
    """Return an error description that is safe in a published log: no local paths or exception detail."""
    if not isinstance(error, FramingError):
        return f"unexpected {type(error).__name__}"
    return "A required file is missing." if error.kind == "missing_file" else str(error)


def append_request(request: request_log.RequestRecord, output: str) -> None:
    """Record a handled request. A request whose record is lost must not look successful."""
    try:
        request.append(output)
    except OSError:
        raise FramingError("log", "The run log could not be written, so this request was not completed.") from None


def handle_request(conversation: str, run: Run, user_text: str | None, request: request_log.RequestRecord) -> dict:
    """Run the Framer and the guardrail. No review runs during framing."""
    run_id, request_hash = uuid.uuid4().hex[:12], short_hash(conversation)
    run.last_run_id = run_id
    framer_content = f"<conversation>\n{without_findings(conversation)}\n</conversation>"

    frame = call_role("framer", framer_content, FRAMER_SCHEMA, check_frame, run, run_id, request_hash, request)

    if user_text is None:
        user_text = user_words(conversation)
    frame, held = apply_guardrail(frame, user_text)
    if held:
        write_log({"event": "guardrail_hold", "run_id": run_id, "session_id": run.session_id,
                   "source": run.source, "case_id": run.case_id, "framing_held": True, "held": held})

    # Set by code, never by a model. Only the user can confirm, by ending a session in the loop.
    return {**frame, "review": [], "reviewer_ran": False, "confirmed": False}


# --- Interactive loop -----------------------------------------------------------------------


def turn_text(result: dict) -> str:
    """Return what the user is shown after a turn. This text also joins the transcript.

    Only the brief reflection and the next question. The rest of the frame is kept and shown at /end.
    """
    return "\n\n".join(part for part in (result["reflection"].strip(), result["next_question"]) if part)


def end_session(run: Run, result: dict | None, current: bool, said: list[str]) -> bool:
    """Show where things stand and let the user confirm, pause, or continue. Return True to leave."""
    view = session_end.understanding(result, current)
    choices = ["confirm", "pause", "continue"] if session_end.can_confirm(result, current) else ["pause", "continue"]
    print(f"\n{view}\n")
    if "confirm" in choices:
        print(f"confirm: {session_end.CONFIRM_MEANING}\n         {session_end.CONFIRM_LIMIT}")
    else:
        print("There is no current problem statement to confirm, so you can pause or continue.")
    print(f"pause: {session_end.PAUSE_MEANING}\ncontinue: Correct something or keep going. Nothing is saved.")
    while True:
        try:
            choice = input(f"\nType {', '.join(choices[:-1])} or continue: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nNothing was saved.")
            return True
        if choice == "continue":
            print("\nTell me what to correct or add.")
            return False
        if choice in choices:
            ended = datetime.now().astimezone()
            text = session_end.session_record(choice, view, said, ended)
            try:
                path = session_end.keep(SESSIONS, text, run.session_id, ended)
            except OSError as error:
                print(f"Error: the session could not be saved ({error.strerror}).", file=sys.stderr)
                continue
            print(f"\n{session_end.STATUS_LINES[choice]}. Saved as {path.relative_to(SESSIONS.parent)}.")
            return True


def run_loop(run: Run) -> None:
    """Let the user refine a frame. The transcript lives in memory and holds only what was displayed."""
    run.source, run.session_id = "interactive", uuid.uuid4().hex[:12]
    transcript: list[str] = []
    said: list[str] = []
    result, current = None, False  # what the user was last shown, and whether it reflects the latest message
    print("Tell me about the concern, opportunity, idea, or proposed solution you are working through.")
    print("Type /end to see where things stand and confirm or pause, or /quit to leave without saving.")
    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not message:
            continue
        if message == "/quit":
            return
        if message == "/end":
            if not said:
                print("\nThere is nothing to end yet.")
            elif end_session(run, result, current, said):
                return
            continue
        if message.startswith("/") and len(message.split()) == 1:  # never send a mistyped command to the model
            print("\nThe commands are /end and /quit.")
            continue
        transcript.append(f"User: {message}")
        said.append(message)
        current = False  # a new message reopens the frame until a new result is shown
        try:
            result = frame_turn("\n\n".join(transcript), run, "\n".join(said))
        except FramingError as error:
            print(f"Error: {error}", file=sys.stderr)
            continue
        shown = turn_text(result)
        print(f"\n{shown}")
        transcript.append(f"Tool: {shown}")
        current = True


def main() -> int:
    parser = argparse.ArgumentParser(description="Problem-framing tool, Week 6 V1")
    parser.add_argument("--request", help="one request, as text; prints the structured result as JSON")
    parser.add_argument("--model", default=MODEL, help=f"model for both roles (default: {MODEL})")
    parser.add_argument("--effort", default=EFFORT, choices=["low", "medium", "high", "xhigh", "max"],
                        help=f"effort for both roles (default: {EFFORT})")
    args = parser.parse_args()
    run = Run(model=args.model, effort=args.effort)
    try:
        if args.request is None:
            run_loop(run)
        else:
            print(json.dumps(frame_turn(args.request, run), indent=2, ensure_ascii=False))
    except FramingError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
