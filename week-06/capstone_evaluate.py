"""Evaluate the problem-framing capstone against the frozen cases in week-06/test-cases.csv.

Each case runs once through the capstone's own framing function. Code checks come first. Only if
they all pass does the program show the result and ask the case's fixed yes/no questions.

Usage (from the repository root):
    .venv/bin/python week-06/capstone_evaluate.py --save week-06/runs/eval-1.txt
    Add --model or --effort to change the settings used for both roles.

Standard output, and the saved file, hold one PASS or FAIL line per case and a final
"Passed: N of M" line. Everything else goes to standard error. Full results and judgments are
kept in a new file in week-06/raw/ for each run.

Only a case's request text reaches the capstone. Its expectations and questions never do.

The exit code is 0 if every case passed, 1 if any failed, and 2 if the run did not complete.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPSTONE = HERE.parent / "capstone"
sys.path.insert(0, str(CAPSTONE))

import problem_framer as capstone  # noqa: E402

CASES_FILE = HERE / "test-cases.csv"
RAW_DIR = HERE / "raw"
COLUMNS = ["id", "type", "request", "expected", "expect_status", "min_findings", "require_nonempty",
           "solution_contains", "statement_excludes", "quantity_check", "judge_1", "judge_2"]
CASE_TYPES = {"Typical", "Edge case", "Should refuse", "Guardrail"}
STATUSES = {"ready", "not_ready"}
BASES = {"derived", "estimate", "assumption", "hypothetical", "placeholder", "pending_validation"}

TEXT_FIELDS = ["reflection", "proposed_solution", "status", "draft_statement", "next_question"]
LIST_FIELDS = ["stated", "assumptions", "unknowns"]
BOOL_FIELDS = ["reviewer_ran", "confirmed"]
RESULT_FIELDS = set(TEXT_FIELDS + LIST_FIELDS + BOOL_FIELDS + ["quantities", "review"])
NONEMPTY_FIELDS = RESULT_FIELDS - set(BOOL_FIELDS) - {"status"}
REASON_LIMIT = 200


class Stopped(Exception):
    """The run cannot start or continue."""


# --- Test cases -----------------------------------------------------------------------------


def load_cases() -> list[dict]:
    """Read and validate the test cases. The file is never written."""
    with CASES_FILE.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != COLUMNS:
            raise Stopped(f"{CASES_FILE.name} does not have the expected columns.")
        cases = list(reader)
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise Stopped(f"{CASES_FILE.name} needs at least one case, each with a different id.")
    for case in cases:
        problem = None
        if None in case or None in case.values() or not case["id"] or not case["request"]:
            problem = "is incomplete"
        elif case["type"] not in CASE_TYPES:
            problem = "has an unknown type"
        elif case["expect_status"] not in STATUSES | {""}:
            problem = "has an unknown expect_status"
        elif case["min_findings"] and not case["min_findings"].isdecimal():
            problem = "has a min_findings that is not a whole number"
        elif case["require_nonempty"] and case["require_nonempty"] not in NONEMPTY_FIELDS:
            problem = "has a require_nonempty that is not an approved field"
        elif case["quantity_check"] not in ("", "yes"):
            problem = "has an unknown quantity_check"
        if problem:
            raise Stopped(f"Case {case.get('id')} in {CASES_FILE.name} {problem}.")
    return cases


# --- Quantity detection, written independently of the capstone ------------------------------
#
# The detector finds numbers by value. It does not understand what a number refers to. It does not
# find fractions such as "half", or spelled-out numbers that are not next to a listed unit.

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen").split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
WORD_VALUES = {w: i for i, w in enumerate(ONES)} | {w: 20 + 10 * i for i, w in enumerate(TENS)}
SCALES = {"dozen": 12, "hundred": 100, "thousand": 1000, "million": 10**6, "billion": 10**9}
SUFFIXES = {"k": 1000, "m": 10**6, "b": 10**9}
WORD = "|".join(sorted(list(WORD_VALUES) + list(SCALES), key=len, reverse=True))
SPELLED = rf"(?:{WORD})(?:(?:\s+and\s+|[\s-]+)(?:{WORD}))*"
UNITS = r"(?:dollars?|percent|hours?|days?|weeks?|months?|years?|items?|returns?)"

LIST_NUMBER = re.compile(r"(?m)^\s*\d+[.)]\s+")
DIGITS = re.compile(
    r"(?<![A-Za-z0-9])(?P<number>\d[\d,]*(?:\.\d+)?|\.\d+)"
    r"(?:(?P<suffix>[kmb])\b|\s+(?P<scale>dozen|hundred|thousand|million|billion)\b)?",
    re.IGNORECASE,
)
SPELLED_WITH_UNIT = re.compile(rf"\b(?P<words>{SPELLED})[\s-]+{UNITS}\b", re.IGNORECASE)
SPELLED_ANY = re.compile(rf"\b(?P<words>{SPELLED})\b", re.IGNORECASE)
BROAD = re.compile(r"\b(?P<word>dozen|hundred|thousand|million|billion)s?\b", re.IGNORECASE)


def canonical(number: Decimal) -> str:
    """Return one spelling for equal numbers, so 4, 4.0, and 04 match."""
    text = format(number, "f")
    return (text.rstrip("0").rstrip(".") if "." in text else text) or "0"


def words_value(words: str) -> str:
    """Return the value of a spelled-out number such as "two hundred and five"."""
    total = current = 0
    for word in re.findall(r"[a-z]+", words.lower()):
        if word in WORD_VALUES:
            current += WORD_VALUES[word]
        elif word in ("dozen", "hundred"):
            current = (current or 1) * SCALES[word]
        elif word in SCALES:
            total, current = total + (current or 1) * SCALES[word], 0
    return canonical(Decimal(total + current))


def find_quantities(text: str, any_spelled: bool = False) -> dict[str, str]:
    """Return {value: the text it was found in}.

    With any_spelled, spelled-out numbers count without a unit. That is used for what the user
    supplied and for declared values, where missing one would cause a false failure.
    """
    found = {}
    text = LIST_NUMBER.sub("", text)

    def digits(match: re.Match) -> str:
        value = Decimal(match["number"].replace(",", ""))
        if match["suffix"]:
            value *= SUFFIXES[match["suffix"].lower()]
        elif match["scale"]:
            value *= SCALES[match["scale"].lower()]
        found.setdefault(canonical(value), match.group().strip())
        return " "

    def spelled(match: re.Match) -> str:
        found.setdefault(words_value(match["words"]), match.group().strip())
        return " "

    def broad(match: re.Match) -> str:
        found.setdefault(match["word"].lower() + "s", match.group().strip())
        return " "

    text = DIGITS.sub(digits, text)
    text = (SPELLED_ANY if any_spelled else SPELLED_WITH_UNIT).sub(spelled, text)
    BROAD.sub(broad, text)
    return found


def shown_text(result: dict) -> dict[str, list[str]]:
    """Return the user-visible framing text by field. The quantities field is the declaration itself."""
    return {
        "reflection": [result["reflection"]],
        "stated": result["stated"],
        "assumptions": result["assumptions"],
        "unknowns": result["unknowns"],
        "proposed_solution": [result["proposed_solution"]],
        "draft_statement": [result["draft_statement"]],
        "next_question": [result["next_question"]],
        "review": [text for item in result["review"] for text in (item["potential_issue"], item["recommendation"])],
    }


def check_quantities(request: str, result: dict) -> tuple[str, str]:
    """Return the Q1 and Q2 failure reasons, each empty if the check passes."""
    supplied = set(find_quantities(request, any_spelled=True))
    derived, declared, q1, q2 = set(), set(), [], []
    for entry in result["quantities"]:
        values = set(find_quantities(entry["value"], any_spelled=True))
        declared |= values
        if entry["basis"] == "derived":
            sources = [set(find_quantities(source) or find_quantities(source, any_spelled=True))
                       for source in entry["from"]]
            if sources and all(source and source <= supplied for source in sources):
                derived |= values
            else:
                q1.append(f'derived quantity "{entry["value"]}" does not identify user-supplied source values')
    for field, texts in shown_text(result).items():
        for text in texts:
            for value, as_written in find_quantities(text).items():
                if value not in supplied | declared:
                    q1.append(f'"{as_written}" in {field} is not user-supplied or listed in quantities')
                if field in ("stated", "draft_statement") and value not in supplied | derived:
                    q2.append(f'"{as_written}" in {field} is presented as established without support')
    return (q1 or [""])[0], (q2 or [""])[0]


# --- Deterministic checks -------------------------------------------------------------------


def is_text_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def check_shape(result) -> str:
    """C1: return the failure reason, or an empty string."""
    if not isinstance(result, dict):
        return "the result is not an object"
    if missing := RESULT_FIELDS - set(result):
        return "missing field: " + ", ".join(sorted(missing))
    if extra := set(result) - RESULT_FIELDS:
        return "unexpected field: " + ", ".join(sorted(map(str, extra)))
    for name in TEXT_FIELDS:
        if not isinstance(result[name], str):
            return f"{name} is not a string"
    for name in LIST_FIELDS:
        if not is_text_list(result[name]):
            return f"{name} is not a list of strings"
    for name in BOOL_FIELDS:
        if not isinstance(result[name], bool):
            return f"{name} is not a boolean"
    for name, fields in (("quantities", {"value", "basis", "from", "note"}),
                         ("review", {"potential_issue", "recommendation"})):
        if not isinstance(result[name], list):
            return f"{name} is not a list"
        for item in result[name]:
            if not isinstance(item, dict) or set(item) != fields:
                return f"an item in {name} does not have exactly the approved fields"
            if any(not isinstance(item[f], str) for f in fields - {"from"}):
                return f"an item in {name} has a field that is not a string"
    for item in result["quantities"]:
        if not is_text_list(item["from"]):
            return "a quantity's from is not a list of strings"
        if item["basis"] not in BASES:
            return f'a quantity has an invalid basis "{item["basis"]}"'
    return ""


def is_nonempty(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return any(bool(item.strip()) if isinstance(item, str) else True for item in value)


def run_checks(case: dict, result) -> list[dict]:
    """Run every applicable deterministic check and return its outcomes, in order."""
    outcomes = []

    def record(name: str, reason: str) -> None:
        outcomes.append({"check": name, "passed": not reason, "reason": reason})

    shape = check_shape(result)
    record("C1", shape)
    if shape:
        return outcomes  # the other checks rely on the shape

    status, statement = result["status"], result["draft_statement"]
    delivered = status == "ready" and bool(statement.strip())
    record("C2", "" if status in STATUSES else f'status is "{status}"')
    reason = ""
    if status == "ready" and not statement.strip():
        reason = "status is ready but there is no draft statement"
    elif status == "not_ready" and statement:
        reason = "status is not_ready but there is a draft statement"
    record("C3", reason)
    record("C4", "" if result["next_question"].strip() else "there is no next question")
    reason = ""
    if delivered and not result["reviewer_ran"]:
        reason = "a draft statement was delivered but the Reviewer did not run"
    elif not delivered and result["reviewer_ran"]:
        reason = "the Reviewer ran without a delivered draft statement"
    elif not delivered and result["review"]:
        reason = "there are review findings without a delivered draft statement"
    record("C5", reason)
    complete = all(f["potential_issue"].strip() and f["recommendation"].strip() for f in result["review"])
    record("C6", "" if complete else "a review finding is missing its potential issue or recommendation")
    record("C7", "confirmed is true" if result["confirmed"] else "")

    if expected := case["expect_status"]:
        reason = "" if status == expected else f"status is {status}, expected {expected}"
        if not reason and expected == "ready" and not delivered:
            reason = "no draft statement was delivered"
        record("expect_status", reason)
    if case["min_findings"]:
        wanted, got = int(case["min_findings"]), len(result["review"])
        record("min_findings", "" if got >= wanted else f"review has {got} findings, expected at least {wanted}")
    if field := case["require_nonempty"]:
        record("require_nonempty", "" if is_nonempty(result[field]) else f"{field} is empty")
    if term := case["solution_contains"]:
        found = term.casefold() in result["proposed_solution"].casefold()
        record("solution_contains", "" if found else f'proposed solution does not contain "{term}"')
    if term := case["statement_excludes"]:
        found = term.casefold() in statement.casefold()
        record("statement_excludes", f'draft statement contains excluded solution term "{term}"' if found else "")
    if case["quantity_check"] == "yes":
        q1, q2 = check_quantities(case["request"], result)
        record("Q1", q1)
        record("Q2", q2)
    return outcomes


# --- Human judgment -------------------------------------------------------------------------


def say(text: str = "") -> None:
    print(text, file=sys.stderr, flush=True)


def ask(prompt: str) -> str:
    """Read one line, showing the prompt on standard error. Stops the run if input ends."""
    print(prompt, end="", file=sys.stderr, flush=True)
    line = sys.stdin.readline()
    if not line:
        raise Stopped("Input ended before the evaluation was complete.")
    return line.strip()


def ask_choice(prompt: str, choices: str) -> str:
    while True:
        answer = ask(prompt).lower()
        if answer and answer in choices.split("/"):
            return answer
        say(f"Please type one of: {choices}")


def judge(case: dict, result: dict) -> list[dict]:
    """Ask the case's fixed questions, exactly as written, and return the answers."""
    questions = [(name, case[name]) for name in ("judge_1", "judge_2") if case[name]]
    answers = []
    if not questions:
        return answers
    say("\n" + "=" * 78)
    say(f"{case['id']} ({case['type']})")
    say(f"\nRequest:\n{case['request']}")
    say("\nComplete structured result:\n" + json.dumps(result, indent=2, ensure_ascii=False))
    failed = False
    for number, (name, question) in enumerate(questions):
        if failed and ask_choice("This case has failed. Answer the next question anyway, as a "
                                 "diagnostic? (y/n): ", "y/n") == "n":
            break
        say(f"\n{question}")
        answer = ask_choice("y = YES, n = NO, u = UNSURE: ", "y/n/u")
        wording = ""
        while answer == "n" and not wording:
            wording = ask("The specific wording or behavior that caused the NO: ")
        answers.append({"question_id": name, "question": question,
                        "answer": {"y": "YES", "n": "NO", "u": "UNSURE"}[answer], "failure_wording": wording})
        failed = failed or answer != "y"
    return answers


# --- One evaluation run ---------------------------------------------------------------------


def concise(text: str) -> str:
    """Return the text as one short line for the summary."""
    text = " ".join(text.split())
    return text if len(text) <= REASON_LIMIT else text[: REASON_LIMIT - 3].rstrip() + "..."


def failure_reason(record: dict) -> str:
    """Return why the case failed, or an empty string if it passed."""
    if record["error"]:
        return f"no usable result: {record['error']}"
    for outcome in record["checks"]:
        if not outcome["passed"]:
            return f"{outcome['check']}: {outcome['reason']}"
    for answer in record["judgments"]:
        if answer["answer"] == "NO":
            return f"{answer['question_id']} NO: {answer['failure_wording']}"
        if answer["answer"] == "UNSURE":
            return f"{answer['question_id']} UNSURE"
    return ""


def run_case(case: dict, run_id: str, model: str, effort: str) -> dict:
    """Run one case through the capstone once and check the result."""
    run = capstone.Run(source="evaluation", case_id=case["id"], session_id=run_id, model=model, effort=effort)
    record = {"id": case["id"], "type": case["type"], "request": case["request"], "expected": case["expected"],
              "v1_run_id": None, "result": None, "error": "", "checks": [], "judgments": [], "outcome": None,
              "reason": ""}
    try:
        record["result"] = capstone.frame_turn(case["request"], run)
    except capstone.FramingError as error:
        record["error"] = str(error)
    except Exception as error:  # a bug in the tool is also a failed case; only its type is recorded
        record["error"] = f"unexpected {type(error).__name__}"
    record["v1_run_id"] = run.last_run_id
    if not record["error"]:
        record["checks"] = run_checks(case, record["result"])
    return record


def file_hash(path: Path) -> str | None:
    return hashlib.sha1(path.read_bytes()).hexdigest() if path.is_file() else None


def evaluate(cases: list[dict], model: str, effort: str, save: Path | None) -> list[str]:
    """Run every case once, then ask for judgments. Return the summary lines."""
    run_id, started = uuid.uuid4().hex[:12], datetime.now(timezone.utc)
    label = save.stem if save else "unsaved"
    RAW_DIR.mkdir(exist_ok=True)
    raw_file = RAW_DIR / f"{label}-{started.strftime('%Y%m%dT%H%M%SZ')}-{run_id}.json"
    frozen = [CASES_FILE, CAPSTONE / "problem_framer.py", CAPSTONE / "prompts" / "framer.txt",
              CAPSTONE / "prompts" / "reviewer.txt", *capstone.GUIDANCE_FILES.values()]
    raw = {"evaluation_run_id": run_id, "started": started.isoformat(timespec="seconds"), "model": model,
           "effort": effort, "file_sha1": {path.name: file_hash(path) for path in frozen},
           "completed": False, "summary": [], "cases": []}
    raw_file.touch(exist_ok=False)  # never reuse another run's file

    def preserve() -> None:
        raw_file.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    preserve()
    for case in cases:
        say(f"Running {case['id']} ...")
        raw["cases"].append(run_case(case, run_id, model, effort))
        preserve()
    passed = 0
    for case, record in zip(cases, raw["cases"]):
        if not failure_reason(record):
            record["judgments"] = judge(case, record["result"])
        record["reason"] = failure_reason(record)
        record["outcome"] = "FAIL" if record["reason"] else "PASS"
        passed += record["outcome"] == "PASS"
        line = f"{case['id']} PASS" if not record["reason"] else f"{case['id']} FAIL: {concise(record['reason'])}"
        raw["summary"].append(line)
        preserve()
        print(line, flush=True)
    line = f"Passed: {passed} of {len(cases)}"
    raw["summary"].append(line)
    raw["completed"] = True
    preserve()
    print(line, flush=True)
    say(f"Raw evidence: {raw_file}")
    return raw["summary"]


def check_save_path(save: Path) -> None:
    if save.exists():
        raise Stopped(f"{save} already exists. Choose a different file name.")
    if not save.resolve().parent.is_dir():
        raise Stopped(f"The folder for {save} does not exist.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the capstone against the frozen test cases")
    parser.add_argument("--save", type=Path, metavar="FILE", help="write the summary lines to a new FILE")
    parser.add_argument("--model", default=capstone.MODEL, help=f"model for both roles (default: {capstone.MODEL})")
    parser.add_argument("--effort", default=capstone.EFFORT, choices=["low", "medium", "high", "xhigh", "max"],
                        help=f"effort for both roles (default: {capstone.EFFORT})")
    args = parser.parse_args()
    try:
        if args.save:
            check_save_path(args.save)
        cases = load_cases()
        capstone.load_api_key()  # stop before a run that could only fail
        for role in capstone.PROMPT_FILES:
            capstone.load_system_prompt(role)
        lines = evaluate(cases, args.model, args.effort, args.save)
        if args.save:
            with args.save.open("x", encoding="utf-8") as file:  # "x" refuses to overwrite
                file.write("\n".join(lines) + "\n")
    except (Stopped, capstone.FramingError, OSError) as error:
        say(f"Error: {error} No summary was saved.")
        return 2
    except KeyboardInterrupt:
        say("\nStopped. The evaluation is not complete and no summary was saved.")
        return 2
    return 0 if all(" FAIL" not in line for line in lines[:-1]) else 1


if __name__ == "__main__":
    sys.exit(main())
