"""Service desk assistant for Alder Creek Heating & Cooling.

Takes a customer's service request as text, sends it to Claude, and returns the JSON reply
with three fields: "priority", "reply", and "needs_person".

The system prompt is alder-creek/assistant-prompt.txt followed by alder-creek/service-guide.md.
Both are read on every run and sent as written, so editing either file changes the assistant.

Two guardrails run in code, outside the prompt:
  1. Before Claude is called: a request that mentions gas, carbon monoxide, smoke, or a burning
     smell never reaches Claude. It gets a fixed Safety reply with needs_person true.
  2. After Claude replies: a reply with a dollar amount that is not allowed, "booked" or
     "confirmed", a clock time, or "covered" or "under warranty" is held for a person:
     needs_person becomes true, and a "held_because" field gives the reason. The reply text
     itself is not changed.

Usage (from the repository root):
    .venv/bin/python week-06/assistant.py --request "Our heat isn't working."

The JSON goes to stdout; problems go to stderr with a non-zero exit code.

API key: read at run time from API-Key.txt (or APIKey.txt) in the folder above the repository.
It is never printed or written to a file.
"""

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
KEY_FILES = [REPO_ROOT.parent / "API-Key.txt", REPO_ROOT.parent / "APIKey.txt"]
PROMPT_FILE = HERE / "alder-creek" / "assistant-prompt.txt"
GUIDE_FILE = HERE / "alder-creek" / "service-guide.md"

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TOKENS = 16000

# The API holds the reply to this shape, so it always parses as JSON with exactly these fields.
REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "priority": {"type": "string", "enum": ["Safety", "Emergency", "Urgent", "Routine"]},
        "reply": {"type": "string"},
        "needs_person": {"type": "boolean"},
    },
    "required": ["priority", "reply", "needs_person"],
    "additionalProperties": False,
}

# Guardrail 1: requests that must never wait for Claude.
SAFETY_REPLY = (
    "Please leave the building now and call the gas company or 911 from outside. "
    "Someone from Alder Creek will call you right away."
)
SAFETY_PATTERN = re.compile(
    r"\bgas(?:es)?\b"
    r"|\bcarbon[\s-]+monoxide\b"
    r"|\bco[\s-]+(?:alarm|detector|monitor|leak)"  # "CO alarm" is carbon monoxide
    r"|\bsmok(?:e|es|ed|ing|ey|y)\b"
    # "burning smell", "smells like something is burning", "a burnt odor"
    r"|\bburn(?:ing|t|ed)\b[^.!?]{0,40}\b(?:smell|odou?r|scent)"
    r"|\b(?:smell|odou?r|scent)\w*\b[^.!?]{0,40}\bburn(?:ing|t|ed)\b",
    re.IGNORECASE,
)

# Guardrail 2: replies that must not go out until a person has read them.
ALLOWED_AMOUNTS = {Decimal(0), Decimal(89), Decimal(149), Decimal(129)}
NUMBER = r"\d[\d,]*(?:\.\d+)?"
SCALE = r"(?:\s*(?:k|m|thousand|hundred|million)\b)?"
# "$89", "$1,200", "$5k", "89 dollars", and both ends of "$129-450". evaluate.py keeps its own
# version of this check so that it tests the guardrail independently.
AMOUNT_PATTERN = re.compile(
    rf"\$\s*(?P<low>{NUMBER})(?P<low_scale>{SCALE})"
    rf"(?:[-\u2013](?P<high>{NUMBER})(?P<high_scale>{SCALE}))?"
    rf"|(?P<words>{NUMBER})(?P<words_scale>{SCALE})\s*(?:dollars?|bucks|usd)\b",
    re.IGNORECASE,
)
HOUR = r"(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
CLOCK_PATTERN = re.compile(
    rf"\b\d{{1,2}}:\d{{2}}\b"
    rf"|\b{HOUR}\s*[ap]\.?\s?m\b\.?"
    rf"|\b{HOUR}\s+o['\u2019]clock\b"
    rf"|\b(?:noon|midnight)\b",
    re.IGNORECASE,
)
BOOKING_PATTERN = re.compile(r"\b(?:booked|confirmed)\b", re.IGNORECASE)
WARRANTY_PATTERN = re.compile(r"\bcovered\b|\bunder\s+warranty\b", re.IGNORECASE)


class AssistantError(Exception):
    """The assistant could not produce a reply."""


def load_api_key() -> str:
    """Return the API key from the key file above the repository."""
    for path in KEY_FILES:
        if path.is_file():
            key = path.read_text(encoding="utf-8-sig").strip()
            if key:
                return key
    names = " or ".join(path.name for path in KEY_FILES)
    raise AssistantError(f"No API key found. Put it in {names} in {REPO_ROOT.parent}.")


def build_system_prompt() -> str:
    """Return the assistant prompt followed by the service guide."""
    try:
        prompt = PROMPT_FILE.read_text(encoding="utf-8").strip()
        guide = GUIDE_FILE.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise AssistantError(f"Could not read {error.filename}: {error.strerror}") from error
    return f"{prompt}\n\n{guide}"


def safety_reply(request: str) -> dict | None:
    """Guardrail 1: return the fixed Safety reply if the request calls for it, otherwise None."""
    if SAFETY_PATTERN.search(request):
        return {"priority": "Safety", "reply": SAFETY_REPLY, "needs_person": True}
    return None


def bad_amounts(reply: str) -> list[str]:
    """Return each dollar amount in the reply, as written, that is not allowed."""
    found = []
    for match in AMOUNT_PATTERN.finditer(reply):
        for name in ("low", "high", "words"):
            number, scale = match[name], match[f"{name}_scale"]
            # "$89k" is not $89, so an amount with a scale word is never allowed.
            if number and (scale or Decimal(number.replace(",", "")) not in ALLOWED_AMOUNTS):
                found.append(match.group().strip(" ,"))
                break
    return found


def matches(pattern: re.Pattern, text: str) -> str:
    """Return the distinct matches in the text, in order, as a quoted list."""
    found = dict.fromkeys(match.group().lower() for match in pattern.finditer(text))
    return ", ".join(f'"{item}"' for item in found)


def hold_if_needed(result: dict) -> dict:
    """Guardrail 2: mark the result for a person if its reply says something it must not."""
    reply = result["reply"]
    reasons = []
    if amounts := bad_amounts(reply):
        reasons.append("gives a dollar amount that is not allowed: " + ", ".join(amounts))
    if found := matches(BOOKING_PATTERN, reply):
        reasons.append(f"says {found}")
    if found := matches(CLOCK_PATTERN, reply):
        reasons.append(f"gives a clock time: {found}")
    if found := matches(WARRANTY_PATTERN, reply):
        reasons.append(f"says {found} (warranty)")
    if reasons:
        result["needs_person"] = True
        result["held_because"] = "Reply " + "; ".join(reasons)
    return result


def answer_request(request: str, client: anthropic.Anthropic | None = None) -> dict:
    """Return the JSON reply to one customer request as a dict, with both guardrails applied."""
    request = request.strip()
    if not request:
        raise AssistantError("The request is empty.")
    # Before anything else, so a safety reply needs neither the API nor a key.
    fixed = safety_reply(request)
    if fixed is not None:
        return fixed
    if client is None:
        client = anthropic.Anthropic(api_key=load_api_key())

    try:
        # If Claude's safety classifiers decline a request, "default" has the API retry it on a
        # fallback model, so a customer reporting a gas smell still gets an answer.
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=build_system_prompt(),
            messages=[{"role": "user", "content": request}],
            output_config={
                "effort": EFFORT,
                "format": {"type": "json_schema", "schema": REPLY_SCHEMA},
            },
        )
    except anthropic.AuthenticationError as error:
        raise AssistantError("The API rejected the key. Check the key file.") from error
    except anthropic.RateLimitError as error:
        raise AssistantError("Rate limited by the API. Wait a minute and try again.") from error
    except anthropic.APIStatusError as error:
        raise AssistantError(f"API error {error.status_code}: {error.message}") from error
    except anthropic.APIConnectionError as error:
        raise AssistantError("Could not reach the API. Check your connection.") from error

    if response.stop_reason != "end_turn":
        raise AssistantError(f"No complete reply (stop reason: {response.stop_reason}).")
    text = "".join(block.text for block in response.content if block.type == "text")
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise AssistantError(f"The reply was not valid JSON: {text!r}") from error
    return hold_if_needed(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Alder Creek service desk assistant")
    parser.add_argument("--request", required=True, help="the customer's service request, as text")
    args = parser.parse_args()
    try:
        reply = answer_request(args.request)
    except AssistantError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(reply, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
