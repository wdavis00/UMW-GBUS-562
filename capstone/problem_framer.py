"""Problem-framing tool: a Framer that helps one person frame a problem, one question at a time.

The Framer turns what a user has said into a tentative, solution-neutral problem frame and asks
one next question. A code guardrail then holds any framing that presents an unsupported quantity as
established (see guardrail.py). Each turn shows only a brief reflection and the next question; the
whole frame is shown when the user ends the session. Only the user can confirm a frame.

At /end the Framer builds the complete semantic basis once, from the whole conversation, and the user
sees it rendered and confirms or pauses. That exact basis is frozen. One Independent Review call then
assesses the frozen basis, and its output can go only to the review section of the human report. Two
files are kept: a Problem-Framing Report for people and an AI handoff built from the basis alone.
Nothing flows backward: the review cannot change the basis, the status, or the handoff.

Usage (from the repository root):
    .venv/bin/python capstone/problem_framer.py --request "..."     one turn, prints JSON
    .venv/bin/python capstone/problem_framer.py                     interactive; /end or /quit
    Add --model or --effort to change the model settings.

Files outside the repository, in the folder above it:
    API-Key.txt or APIKey.txt               the API key, read at run time, never printed or written
    Week8/Mitre/framer-guidance.txt         framing guidance for the Framer
    Week8/Mitre/reviewer-criteria.txt       quality guidance for the Independent Review
    Week8/capstone-runs/run-log.jsonl       provisional diagnostic log

Every request the tool handles is also recorded in capstone/runs/log.jsonl (see request_log.py).
A session the user ends is kept in capstone/sessions, which git ignores (see session_end.py and outputs.py).

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

import outputs
import request_log
import session_end
from guardrail import apply_guardrail, find_amounts, user_words

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TOKENS = 16000

HERE = Path(__file__).resolve().parent
COURSE_DIR = HERE.parent.parent
KEY_FILES = [COURSE_DIR / "API-Key.txt", COURSE_DIR / "APIKey.txt"]
RUN_LOG = COURSE_DIR / "Week8" / "capstone-runs" / "run-log.jsonl"
SESSIONS = HERE / "sessions"
PROMPT_FILES = {"framer": HERE / "prompts" / "framer.txt", "reviewer": HERE / "prompts" / "reviewer.txt"}
END_PROMPT = HERE / "prompts" / "framer-end.txt"  # added to the Framer prompt for the one call at /end
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
QUANTITIES = FRAMER_SCHEMA["properties"]["quantities"]
# The semantic basis the Framer builds once at /end. Status is not here: only the user sets it.
BASIS_SCHEMA = object_schema(
    user_material={"type": "array", "items": object_schema(
        kind={"type": "string", "enum": outputs.KINDS},
        text=TEXT,
        standing={"type": "string", "enum": ["reported", "belief", "estimate"]},
        relation=TEXT,
    )},
    understanding=object_schema(
        problem=TEXT, affected=TEXT_LIST, cases=TEXT_LIST, desired_state=TEXT, solution_standing=TEXT,
        assumptions=TEXT_LIST, unknowns=TEXT_LIST, statement=TEXT,
    ),
    quantities=QUANTITIES,
)
# The Independent Review. Review fields only: nothing here can stand for or replace framing state.
REVIEW_SCHEMA = object_schema(
    overall=TEXT,
    strengths=TEXT_LIST,
    limitations={"type": "array", "items": object_schema(observation=TEXT, why_it_matters=TEXT)},
    statement_fit=TEXT,
    optional_evidence={"type": "array", "items": object_schema(evidence=TEXT, why_it_matters=TEXT)},
)
MAX_EVIDENCE = 3
IDENTITY_WORDS = re.compile(r"\b(he|him|his|himself|she|her|hers|herself|mr|mrs|ms)\b", re.IGNORECASE)


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
    if role == "framer_end":
        if not END_PROMPT.is_file():
            raise FramingError("missing_file", f"Required file not found for the Framer: {END_PROMPT}")
        return load_system_prompt("framer") + "\n\n" + END_PROMPT.read_text(encoding="utf-8")
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
    """Reject a review that is empty where it must not be or has too many evidence items. Never repair it."""
    if not review["overall"].strip() or not review["statement_fit"].strip():
        raise FramingError("invalid", "The review is missing its overall assessment or statement fit.")
    if len(review["optional_evidence"]) > MAX_EVIDENCE:
        raise FramingError("invalid", f"The review lists more than {MAX_EVIDENCE} evidence items.")
    texts = review["strengths"] + [v for x in review["limitations"] + review["optional_evidence"] for v in x.values()]
    if not all(text.strip() for text in texts):
        raise FramingError("invalid", "The review has an empty item.")


def identity_words(basis: dict, user_text: str) -> set[str]:
    """Gendered words or titles in the basis that the user never used."""
    used = {w.lower() for w in IDENTITY_WORDS.findall(user_text)}
    return {w.lower() for w in IDENTITY_WORDS.findall(json.dumps(basis, ensure_ascii=False))} - used


def check_basis(basis: dict, user_text: str) -> None:
    """Enforce the basis rules code can check. A basis that breaks one is not shown or kept."""
    kinds = {item["kind"] for item in basis["user_material"]}
    u = basis["understanding"]
    if not all(item["text"].strip() for item in basis["user_material"]):
        raise FramingError("invalid", "The basis has an empty item.")
    if u["desired_state"].strip() and "desired_state" not in kinds:
        raise FramingError("invalid", "The basis gives a desired state the user did not supply.")
    if bool(u["solution_standing"].strip()) != ("proposed_solution" in kinds):
        raise FramingError("invalid", "The basis gives a solution standing without a proposed solution, or the reverse.")
    if "solution_reason" in kinds and "proposed_solution" not in kinds:
        raise FramingError("invalid", "The basis gives reasons for a solution the user did not raise.")
    if identity_words(basis, user_text):
        raise FramingError("invalid", "The basis uses a gendered word or title the user did not use.")


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


def build_basis(conversation: str, said: list[str], run: Run) -> tuple[dict, list[dict]]:
    """The Framer's one call at /end: the complete semantic basis, and any amounts held as unsupported.

    The basis is checked and its amounts are checked as the guardrail checks a turn. A held basis can be
    paused but not confirmed. One canonical log line is written for the request.
    """
    if run.client is None:
        run.client = anthropic.Anthropic(api_key=load_api_key())
    if not isinstance(run.client, anthropic.Anthropic) and request_log.LOG_FILE == request_log.PRODUCTION_LOG:
        raise FramingError("log", "A stand-in client may not write to the real run log.")
    user_text = "\n".join(said)
    request = request_log.RequestRecord(run.model, conversation)
    run_id, request_hash = uuid.uuid4().hex[:12], short_hash(conversation)
    content = f"<conversation>\n{without_findings(conversation)}\n</conversation>"
    try:
        basis = call_role("framer_end", content, BASIS_SCHEMA, lambda b: check_basis(b, user_text),
                          run, run_id, request_hash, request)
    except BaseException as error:
        if request.calls:
            append_request(request, f"Error: {public_reason(error)}")
        raise
    u = basis["understanding"]
    as_frame = {"stated": [item["text"] for item in basis["user_material"]], "draft_statement": u["statement"],
                "quantities": basis["quantities"], "reflection": "", "assumptions": [], "status": "ready",
                "next_question": ""}
    reasons = apply_guardrail(as_frame, user_text)[1]
    if reasons:
        write_log({"event": "guardrail_hold", "run_id": run_id, "session_id": run.session_id,
                   "source": run.source, "case_id": "end", "framing_held": True, "held": reasons})
    written = {}  # each held amount as the basis wrote it, for display
    for text in as_frame["stated"] + [u["statement"]]:
        written.update(find_amounts(text))
    held = [{"value": written.get(r["value"], r["value"]), "reason": r["reason"]} for r in reasons]
    append_request(request, json.dumps(basis, ensure_ascii=False))
    return basis, held


def independent_review(review_text: str, run: Run) -> dict | None:
    """One Independent Review call on the fixed review input. Returns None if no usable review came back.

    It receives text only, so it has no way to reach the frozen state, and its result is returned to the
    caller for the report alone. One canonical log line is written for the request.
    """
    request = request_log.RequestRecord(run.model, review_text)
    run_id, request_hash = uuid.uuid4().hex[:12], short_hash(review_text)
    try:
        review = call_role("reviewer", review_text, REVIEW_SCHEMA, check_review, run, run_id, request_hash, request)
    except FramingError as error:
        if request.calls:
            append_request(request, f"Error: {public_reason(error)}")
        return None
    append_request(request, json.dumps(review, ensure_ascii=False))
    return review


def finish(run: Run, record: dict, said: list[str], view: str) -> Path:
    """Keep the frozen state, then review it, then write the two outputs. Return the session folder.

    Order matters: the basis is saved and fingerprinted before the review runs, and the fingerprint is
    checked again before anything is rendered from it.
    """
    before = session_end.fingerprint(record)
    basis_text = json.dumps({**record, "fingerprint": before}, indent=2, ensure_ascii=False) + "\n"
    path = session_end.keep(SESSIONS, run.session_id, datetime.fromisoformat(record["ended"]),
                            {session_end.BASIS_FILE: basis_text,
                             session_end.RECORD_FILE: session_end.session_record(record, view, said)})
    print("\nWriting the Independent Review...")
    review = independent_review(outputs.review_input(record, said), run)
    if session_end.fingerprint(record) != before:
        raise RuntimeError("The frozen framing state changed during the review.")
    session_end.add(path, {session_end.REPORT_FILE: outputs.report_markdown(record, review),
                           session_end.HANDOFF_FILE: outputs.handoff_markdown(record)})
    if review is None:
        print("The Independent Review could not be produced. The report says so, and the framing is unaffected.",
              file=sys.stderr)
    return path


def end_session(run: Run, conversation: str, said: list[str]) -> bool:
    """Build the basis, show it, and let the user confirm, pause, or continue. Return True to leave."""
    print("\nPutting together where things stand...")
    try:
        basis, held = build_basis(conversation, said, run)
    except FramingError as error:
        print(f"Error: {error} Nothing was saved. You can type /end again or keep going.", file=sys.stderr)
        return False
    view = session_end.understanding(basis, held)
    choices = ["confirm", "pause", "continue"] if session_end.can_confirm(basis, held) else ["pause", "continue"]
    print(f"\n{view}\n")
    if "confirm" in choices:
        print(f"confirm: {session_end.CONFIRM_MEANING}\n         {session_end.CONFIRM_LIMIT}")
    else:
        print("There is no problem statement you can confirm yet, so you can pause or continue.")
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
            record = session_end.freeze(basis, held, choice, datetime.now().astimezone())
            try:
                path = finish(run, record, said, view)
            except OSError as error:
                print(f"Error: the session could not be saved ({error.strerror}).", file=sys.stderr)
                continue
            print(f"\n{session_end.STATUS_LINES[choice]}. Saved in {path.relative_to(SESSIONS.parent)}:")
            print(f"  {session_end.REPORT_FILE}  the Problem-Framing Report, with the Independent Review")
            print(f"  {session_end.HANDOFF_FILE}  the framing state, for use with another AI")
            return True


def run_loop(run: Run) -> None:
    """Let the user refine a frame. The transcript lives in memory and holds only what was displayed."""
    run.source, run.session_id = "interactive", uuid.uuid4().hex[:12]
    transcript: list[str] = []
    said: list[str] = []
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
            elif end_session(run, "\n\n".join(transcript), said):
                return
            continue
        if message.startswith("/") and len(message.split()) == 1:  # never send a mistyped command to the model
            print("\nThe commands are /end and /quit.")
            continue
        transcript.append(f"User: {message}")
        said.append(message)
        try:
            result = frame_turn("\n\n".join(transcript), run, "\n".join(said))
        except FramingError as error:
            print(f"Error: {error}", file=sys.stderr)
            continue
        shown = turn_text(result)
        print(f"\n{shown}")
        transcript.append(f"Tool: {shown}")


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
