"""Run every row of alder-creek/test-cases.csv through the assistant and check each reply in code.

Checks for each case:
  - the priority matches expected_priority;
  - the reply contains at least one must_say phrase and no must_not_say phrase (phrases are
    separated by |, and capital letters are ignored);
  - needs_person is true where the needs_person column says yes;
  - every dollar amount in the reply is $0, $89, $149, or $129.

Usage (from the repository root):
    .venv/bin/python week-06/evaluate.py
    .venv/bin/python week-06/evaluate.py --save week-06/runs/eval.txt

Prints one line per case, PASS or FAIL with the reasons, and ends with the number passed. A FAIL
line also shows the reply's needs_person and held_because values, so you can see whether a
guardrail held it for a person. These two values do not change whether a case passes.
The exit code is 0 if every case passed, 1 if any failed, and 2 if the run could not start.
Each run makes one API call per case.
"""

import argparse
import csv
import re
import sys
from decimal import Decimal
from pathlib import Path

import anthropic

from assistant import HERE, AssistantError, answer_request, load_api_key

CASES_FILE = HERE / "alder-creek" / "test-cases.csv"
ALLOWED_AMOUNTS = {Decimal(0), Decimal(89), Decimal(149), Decimal(129)}

NUMBER = r"\d[\d,]*(?:\.\d+)?"
SCALE = r"(?:\s*(?:k|m|thousand|hundred|million)\b)?"
# Matches "$89", "$89.00", "$1,200", "$5k", and "89 dollars".
AMOUNT = re.compile(
    rf"\$\s*(?P<symbol>{NUMBER})(?P<scale>{SCALE})|(?P<words>{NUMBER})(?P<word_scale>{SCALE})\s*dollars?\b",
    re.IGNORECASE,
)


def phrases(cell: str) -> list[str]:
    """Split a must_say or must_not_say cell on | and drop empty parts."""
    return [part.strip() for part in cell.split("|") if part.strip()]


def bad_amounts(reply: str) -> list[str]:
    """Return each dollar amount in the reply, as written, that is not allowed."""
    found = []
    for match in AMOUNT.finditer(reply):
        number = match["symbol"] or match["words"]
        scale = match["scale"] or match["word_scale"]
        # "$89k" is not $89, so an amount with a scale word is never allowed.
        if scale or Decimal(number.replace(",", "")) not in ALLOWED_AMOUNTS:
            found.append(match.group().strip())
    return found


def check(case: dict, result: dict) -> list[str]:
    """Return the reasons this result fails the case; an empty list means it passes."""
    reasons = []
    reply = result["reply"]
    lowered = reply.casefold()

    expected = case["expected_priority"].strip()
    if result["priority"] != expected:
        reasons.append(f"priority is {result['priority']}, expected {expected}")

    must_say = phrases(case["must_say"])
    if must_say and not any(phrase.casefold() in lowered for phrase in must_say):
        reasons.append("reply says none of: " + ", ".join(f'"{p}"' for p in must_say))

    said = [p for p in phrases(case["must_not_say"]) if p.casefold() in lowered]
    if said:
        reasons.append("reply says forbidden: " + ", ".join(f'"{p}"' for p in said))

    if case["needs_person"].strip().casefold() == "yes" and result["needs_person"] is not True:
        reasons.append(f"needs_person is {str(result['needs_person']).lower()}, expected true")

    amounts = bad_amounts(reply)
    if amounts:
        reasons.append("reply gives an amount that is not allowed: " + ", ".join(amounts))

    return reasons


def guardrail_status(result: dict) -> str:
    """Return the needs_person and held_because values, as shown on a FAIL line."""
    needs_person = str(result["needs_person"]).lower()
    return f"[needs_person: {needs_person}; held_because: {result.get('held_because', 'none')}]"


def load_cases() -> list[dict]:
    """Read the test cases from the CSV file."""
    with CASES_FILE.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the Alder Creek assistant")
    parser.add_argument("--save", type=Path, metavar="FILE", help="also write the output to FILE")
    args = parser.parse_args()
    if args.save and not args.save.resolve().parent.is_dir():
        parser.error(f"the folder for {args.save} does not exist")

    try:
        cases = load_cases()
        client = anthropic.Anthropic(api_key=load_api_key())
    except (AssistantError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    lines = []

    def emit(line: str) -> None:
        lines.append(line)
        print(line, flush=True)

    passed = 0
    for case in cases:
        status = ""
        try:
            result = answer_request(case["request"], client)
            reasons = check(case, result)
            status = " " + guardrail_status(result)
        except AssistantError as error:
            reasons = [f"no reply to check: {error}"]
        label = f"{case['id']} ({case['type']})"
        if reasons:
            emit(f"FAIL  {label}: " + "; ".join(reasons) + status)
        else:
            passed += 1
            emit(f"PASS  {label}")
    emit(f"{passed} of {len(cases)} passed")

    if args.save:
        args.save.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
