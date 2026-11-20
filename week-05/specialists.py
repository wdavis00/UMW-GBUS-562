#!/usr/bin/env python3
"""specialists.py - the four specialists a company's coordinators share.

  run_analyst(email)                  agent with the supply MCP tools (at most 10 tool calls);
                                      returns the analyst's brief as a dict (JSON)
  write_supplier_reply(email, brief)  one model call; customer names are removed first
  write_customer_notice(order)        one model call, given only that one order's facts
  review(draft, facts, recipient)     one model call; returns APPROVE or REVISE with reasons

  draft_supplier_reply(email, brief)  review step: writer -> reviewer, at most 2 revisions,
  draft_customer_notice(order)        then name checks in code, then save to
                                      week-05/drafts/<company folder>/; the final draft is
                                      printed once, with "Marked for a person: yes/no"

set_org(folder) chooses the company folder (CSV files + prompts/; default brookfield-bikes).
Every specialist reads its system prompt from <company folder>/prompts/ on every call, so
prompt edits take effect on the next run. CSV columns are found by role from each header
row (see supply_mcp_server.COLUMN_ROLES), so companies may name them differently. Every
handoff between a coordinator and a specialist (or between two specialists) is printed,
including the analyst's full brief, as are the tokens each call used; token_report() prints
the totals per specialist.

The Anthropic API key comes from ANTHROPIC_API_KEY or from API-Key.txt / APIKey.txt in the
folder above the repository. It is read at run time and never printed or written.

Usage (from the repo root), as a quick end-to-end check on one supplier email:
  .venv/bin/python week-05/specialists.py week-05/brookfield-bikes/supplier-emails/01-northgate-controller-delay.eml
  .venv/bin/python week-05/specialists.py --org week-05/copperline-coffee <email.eml>
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent                  # .../UMW-GBUS-562/week-05
REPO_ROOT = HERE.parent
SERVER_SCRIPT = HERE / "supply_mcp_server.py"
KEY_FILES = [REPO_ROOT.parent / "API-Key.txt", REPO_ROOT.parent / "APIKey.txt"]

MODEL = "claude-sonnet-5"
MAX_TOKENS = 16000
MAX_TOOL_CALLS = 10          # analyst stops after this many tool calls
MAX_REVISIONS = 2            # review step: the writer may revise at most this many times
NO_REPLY = "NO REPLY NEEDED"

sys.path.insert(0, str(HERE))
import supply_mcp_server as data  # noqa: E402  (same CSV reader and column roles as the server)
from supply_mcp_server import read_table  # noqa: E402

# The company folder (CSV files + prompts/). Change it with set_org(); drafts go to
# week-05/drafts/<company folder name>/.
ORG_DIR = data.DEFAULT_ORG_DIR
PROMPTS_DIR = ORG_DIR / "prompts"
DRAFTS_DIR = HERE / "drafts" / ORG_DIR.name


def set_org(path: str | Path | None) -> Path:
    """Point every specialist at a company folder (default: brookfield-bikes)."""
    global ORG_DIR, PROMPTS_DIR, DRAFTS_DIR
    ORG_DIR = data.set_org(path)
    PROMPTS_DIR = ORG_DIR / "prompts"
    DRAFTS_DIR = HERE / "drafts" / ORG_DIR.name
    if not PROMPTS_DIR.is_dir():
        raise SystemExit(f"{ORG_DIR} has no prompts folder.")
    try:
        columns = data.describe_columns()
    except data.DataError as e:
        raise SystemExit(f"Error: {e}")
    print(f"Company folder: {ORG_DIR}")
    print(f"Columns found from each header row:\n{columns}")
    return ORG_DIR


class SpecialistError(Exception):
    """A specialist could not produce its result (refusal, unreadable output, ...)."""


# --------------------------------------------------------------------------------------
# Secrets, clients, prompts
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


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=load_api_key())
    return _client


def load_prompt(name: str) -> str:
    """Read a system prompt fresh on every call (e.g. 'analyst' -> prompts/analyst.txt)."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


# --------------------------------------------------------------------------------------
# Printing: handoffs and token use
# --------------------------------------------------------------------------------------

USAGE: dict[str, dict[str, int]] = {}


def record_usage(specialist: str, usage) -> None:
    """Add one API call's tokens to the specialist's total and print them."""
    u = USAGE.setdefault(specialist, {"calls": 0, "input": 0, "output": 0})
    u["calls"] += 1
    u["input"] += usage.input_tokens
    u["output"] += usage.output_tokens
    print(f"  [tokens] {specialist}: +{usage.input_tokens} in / +{usage.output_tokens} out "
          f"(total {u['input']} in / {u['output']} out over {u['calls']} call(s))")


def token_report() -> dict[str, dict[str, int]]:
    """Print and return the tokens each specialist used in this process."""
    print("\n=== Tokens by specialist ===")
    total_in = total_out = 0
    for name, u in USAGE.items():
        print(f"  {name:<16} {u['calls']:>3} call(s)  {u['input']:>8} in  {u['output']:>7} out")
        total_in += u["input"]
        total_out += u["output"]
    print(f"  {'TOTAL':<16} {'':>11}  {total_in:>8} in  {total_out:>7} out")
    return USAGE


def handoff(sender: str, receiver: str, payload, label: str = "") -> None:
    """Print one handoff: who passes what to whom."""
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, ensure_ascii=False)
    title = f"HANDOFF {sender} -> {receiver}" + (f" ({label})" if label else "")
    print(f"\n----- {title} -----")
    print(text.strip())
    print("-" * (len(title) + 12))


# --------------------------------------------------------------------------------------
# Data helpers (names to keep out of drafts, order facts)
# --------------------------------------------------------------------------------------

def customer_names() -> list[str]:
    return sorted({r["customer"] for r in read_table("orders.csv") if r["customer"]},
                  key=len, reverse=True)


def supplier_names() -> list[str]:
    """Supplier companies, their first word (e.g. 'Northgate'), and their contact names."""
    names: set[str] = set()
    for r in read_table("suppliers.csv"):
        company = r["supplier"]
        names.update({company, company.split()[0] if company else "", r["contact_name"]})
    for r in read_table("parts.csv") + read_table("inbound.csv"):
        names.update({r["supplier"], r["supplier"].split()[0] if r["supplier"] else ""})
    return sorted((n for n in names if n), key=len, reverse=True)


def order_row(order_id: str) -> dict[str, str] | None:
    """The orders.csv row (keyed by role) for order_id, or None."""
    wanted = str(order_id or "").strip().upper()
    return next((r for r in read_table("orders.csv") if r["order_id"].upper() == wanted), None)


def names_found(text: str, names: list[str]) -> list[str]:
    """Names that appear in text as whole words, ignoring case."""
    return [n for n in names
            if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", text, flags=re.IGNORECASE)]


def scrub_names(value, names: list[str], placeholder: str = "[customer]"):
    """Replace names in any string inside value (str, list, or dict); returns a copy."""
    if isinstance(value, str):
        for n in names:
            value = re.sub(rf"(?<!\w){re.escape(n)}(?!\w)", placeholder, value, flags=re.IGNORECASE)
        return value
    if isinstance(value, list):
        return [scrub_names(v, names, placeholder) for v in value]
    if isinstance(value, dict):
        return {k: scrub_names(v, names, placeholder) for k, v in value.items()}
    return value


def strip_customers_from_brief(brief: dict) -> dict:
    """The brief without customer names: drop 'customer' fields, then scrub any text."""
    def drop(value):
        if isinstance(value, dict):
            return {k: drop(v) for k, v in value.items() if k != "customer"}
        if isinstance(value, list):
            return [drop(v) for v in value]
        return value
    return scrub_names(drop(brief), customer_names())


def order_facts(order: dict) -> dict:
    """Only the facts a customer notice needs, for one order.

    order is an entry of the brief's orders_at_risk (order_id, customer, ship_day,
    ready_day, ...). Product and quantity are filled in from orders.csv. Penalties, costs, and
    supplier details are left out on purpose.
    """
    row = order_row(order.get("order_id"))
    if row is None:
        raise SpecialistError(f"Unknown order_id {order.get('order_id')!r}.")
    ship_day = int(row["ship_day"])
    ready_day = order.get("ready_day")
    return {
        "order_id": row["order_id"],
        "customer": row["customer"],
        "product": row["product"],
        "quantity": int(row["qty"]),
        "planned_ship_day": ship_day,
        "expected_ship_day": ready_day,
        "days_late": (ready_day - ship_day) if isinstance(ready_day, int) else None,
        "days_counted_from": "today (day 0)",
        "note": ("" if isinstance(ready_day, int)
                 else "No new ship date is known yet."),
    }


def order_has_late_penalty(order_id: str) -> bool:
    row = order_row(order_id)
    return bool(row) and data.to_bool(row["late_penalty"])


def email_subject(email: str) -> str:
    m = re.search(r"^Subject:\s*(.+)$", email, flags=re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else "your email"


# --------------------------------------------------------------------------------------
# Model calls
# --------------------------------------------------------------------------------------

def response_text(response) -> str:
    if response.stop_reason == "refusal":
        raise SpecialistError("The model declined this request (stop_reason: refusal).")
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


def one_call(specialist: str, prompt_name: str, user_content: str) -> str:
    """One model call with a prompt file as the system prompt. Returns the text."""
    response = client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=load_prompt(prompt_name),
        messages=[{"role": "user", "content": user_content}],
    )
    record_usage(specialist, response.usage)
    return response_text(response)


def parse_json_object(text: str) -> dict:
    """The last top-level JSON object in text (code fences and prose around it are ignored).

    Objects nested inside another object are skipped, so an order inside the brief is never
    mistaken for the brief itself.
    """
    decoder = json.JSONDecoder()
    found = None
    i = 0
    while i < len(text):
        if text[i] == "{":
            try:
                obj, end = decoder.raw_decode(text, i)
            except json.JSONDecodeError:
                i += 1
                continue
            if isinstance(obj, dict):
                found = obj
            i = end                      # jump past this object, skipping nested ones
        else:
            i += 1
    if found is None:
        raise SpecialistError("The analyst's answer contained no JSON brief.")
    return found


# --------------------------------------------------------------------------------------
# Specialist 1: supply analyst (agent with the MCP tools)
# --------------------------------------------------------------------------------------

BRIEF_FIELDS = {"part_id": "", "what_changed": "", "orders_at_risk": [], "options": [],
                "decisions_for_a_person": [], "supplier_questions": []}


def mcp_result_text(result) -> str:
    parts = [b.text if getattr(b, "type", None) == "text"
             else f"[{getattr(b, 'type', 'unknown')} content omitted]" for b in result.content]
    if not parts and result.structured_content is not None:
        parts.append(json.dumps(result.structured_content))
    return "\n".join(parts) or "(empty result)"


async def run_analyst_async(email: str) -> dict:
    """Async version of run_analyst, for coordinators that already run an event loop."""
    handoff("coordinator", "analyst", email, "supplier email")
    aclient = anthropic.AsyncAnthropic(api_key=load_api_key())
    system_prompt = load_prompt("analyst")
    server = StdioServerParameters(command=sys.executable,
                                   args=[str(SERVER_SCRIPT), "--org", str(ORG_DIR)],
                                   cwd=str(REPO_ROOT))
    tool_calls = 0
    limit_hit = False

    async with stdio_client(server, errlog=sys.__stderr__) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = (await session.list_tools()).tools
            tools = [{"name": t.name, "description": t.description or "",
                      "input_schema": t.input_schema} for t in mcp_tools]
            names = {t["name"] for t in tools}

            # The email goes in as data, clearly marked, not as instructions.
            messages = [{"role": "user", "content":
                         f"Analyze this supplier email.\n\n<email>\n{email.strip()}\n</email>"}]

            while True:
                response = await aclient.messages.create(
                    model=MODEL, max_tokens=MAX_TOKENS, system=system_prompt,
                    tools=tools, messages=messages,
                    # After the tool limit, the model must answer without tools.
                    tool_choice={"type": "none"} if limit_hit else {"type": "auto"},
                )
                record_usage("analyst", response.usage)
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason != "tool_use" or not tool_uses:
                    break

                messages.append({"role": "assistant", "content": response.content})
                results = []
                for tu in tool_uses:
                    if tool_calls >= MAX_TOOL_CALLS:   # every tool_use still needs a result
                        results.append({"type": "tool_result", "tool_use_id": tu.id,
                                        "content": "Not run: the tool-call limit was reached.",
                                        "is_error": True})
                        continue
                    tool_calls += 1
                    print(f"  analyst tool call {tool_calls}/{MAX_TOOL_CALLS}: {tu.name} "
                          f"{json.dumps(tu.input, ensure_ascii=False)}")
                    if tu.name in names:
                        try:
                            result = await session.call_tool(tu.name, tu.input or {})
                            text, is_error = mcp_result_text(result), bool(result.is_error)
                        except Exception as e:      # report the failure to the model
                            text, is_error = f"Tool call failed: {e}", True
                    else:
                        text, is_error = f"Unknown tool: {tu.name}", True
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": text, "is_error": is_error})

                if tool_calls >= MAX_TOOL_CALLS and not limit_hit:
                    limit_hit = True
                    print(f"  analyst reached the limit of {MAX_TOOL_CALLS} tool calls; "
                          "asking for the brief now.")
                    results.append({"type": "text", "text":
                                    f"You have used all {MAX_TOOL_CALLS} tool calls. Write your "
                                    "brief as JSON now, using only the tool results you have."})
                messages.append({"role": "user", "content": results})

    text = response_text(response)
    try:
        brief = parse_json_object(text)
    except SpecialistError:
        raise SpecialistError(f"The analyst returned no JSON brief. Its answer was:\n{text}")
    for field, default in BRIEF_FIELDS.items():
        brief.setdefault(field, default)
    print(f"  analyst used {tool_calls} tool call(s)"
          + (" and stopped at the limit." if limit_hit else "."))
    handoff("analyst", "coordinator", brief, "the analyst's full brief")
    return brief


def run_analyst(email: str) -> dict:
    """Supply analyst: works out how a supplier email affects orders. Returns its brief."""
    return asyncio.run(run_analyst_async(email))


# --------------------------------------------------------------------------------------
# Specialists 2-4: writers and reviewer (one model call each)
# --------------------------------------------------------------------------------------

def _revision_note(feedback: str | None, previous_draft: str | None) -> str:
    if not feedback:
        return ""
    return ("\n\nA reviewer asked for changes to your previous draft. Write a new draft that "
            "fixes every point.\n\n<previous_draft>\n" + (previous_draft or "").strip()
            + "\n</previous_draft>\n\n<reviewer_feedback>\n" + feedback.strip()
            + "\n</reviewer_feedback>")


def write_supplier_reply(email: str, brief: dict, feedback: str | None = None,
                         previous_draft: str | None = None) -> str:
    """Supplier writer: one model call. Customer names are removed before the call."""
    names = customer_names()
    safe_email = scrub_names(email, names)
    safe_brief = strip_customers_from_brief(brief)
    content = ("Draft a reply to this supplier email.\n\n<email>\n" + safe_email.strip()
               + "\n</email>\n\n<analyst_brief>\n" + json.dumps(safe_brief, indent=2)
               + "\n</analyst_brief>" + _revision_note(feedback, previous_draft))
    return one_call("supplier-writer", "supplier-writer", content)


def write_customer_notice(order: dict, feedback: str | None = None,
                          previous_draft: str | None = None) -> str:
    """Customer writer: one model call, given only that one order's facts."""
    facts = order_facts(order)
    content = ("Draft a notice to the customer of this order.\n\n<order_facts>\n"
               + json.dumps(facts, indent=2) + "\n</order_facts>"
               + _revision_note(feedback, previous_draft))
    return one_call("customer-writer", "customer-writer", content)


def review(draft: str, facts, recipient: str) -> dict:
    """Reviewer: one model call. Returns {'verdict': 'APPROVE'|'REVISE', 'reasons': str}."""
    if recipient not in {"supplier", "customer"}:
        raise ValueError("recipient must be 'supplier' or 'customer'")
    facts_text = facts if isinstance(facts, str) else json.dumps(facts, indent=2)
    content = (f"Review this draft to a {recipient}.\n\n<draft>\n{draft.strip()}\n</draft>\n\n"
               f"<facts>\n{facts_text.strip()}\n</facts>")
    text = one_call("reviewer", "reviewer", content)
    # APPROVE only when the answer opens with APPROVE and never says REVISE on a line of its
    # own; anything else (including a reviewer that changes its mind) counts as REVISE.
    lines = [ln.strip().strip("*#: ").upper() for ln in text.splitlines() if ln.strip()]
    approved = bool(lines) and lines[0].startswith("APPROVE") and \
        not any(ln.startswith("REVISE") for ln in lines)
    reasons = "\n".join(ln for ln in text.splitlines()
                        if ln.strip().strip("*#: ").upper() not in {"APPROVE", "REVISE"}).strip()
    return {"verdict": "APPROVE" if approved else "REVISE", "reasons": reasons}


# --------------------------------------------------------------------------------------
# Review step: writer -> reviewer (at most 2 revisions) -> name checks -> save
# --------------------------------------------------------------------------------------

def _review_loop(writer_name: str, write, facts, recipient: str) -> tuple[str, dict, int]:
    """Run a writer, then the reviewer, revising at most MAX_REVISIONS times."""
    draft = write(None, None)
    revisions = 0
    while True:
        if draft.strip() == NO_REPLY:
            return draft, {"verdict": "APPROVE", "reasons": "No reply needed."}, revisions
        handoff(writer_name, "reviewer", draft, f"draft {revisions + 1}")
        verdict = review(draft, facts, recipient)
        handoff("reviewer", writer_name if verdict["verdict"] == "REVISE" else "review step",
                f"{verdict['verdict']}\n{verdict['reasons']}".strip(), "verdict")
        if verdict["verdict"] == "APPROVE" or revisions >= MAX_REVISIONS:
            return draft, verdict, revisions
        revisions += 1
        draft = write(verdict["reasons"], draft)


def print_final_draft(title: str, draft: str, needs_person: bool) -> None:
    """Print a review step's final draft once, between its title and its person flag."""
    print(f"\n{title}")
    print(draft.strip())
    print(f"Marked for a person: {'yes' if needs_person else 'no'}")


def _save_draft(kind: str, ident: str, to: str, subject: str, draft: str, verdict: dict,
                revisions: int, flags: list[str]) -> Path:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = DRAFTS_DIR / f"{stamp}-{kind}-{ident}.md"
    review_needed = "YES" if flags else "no"
    lines = [
        f"# Draft to {kind}: {ident}",
        "",
        f"- To: {to}",
        f"- Subject: {subject}",
        f"- Needs a person: {review_needed}",
        *[f"  - {f}" for f in flags],
        f"- Reviewer: {verdict['verdict']} after {revisions} revision(s)",
        f"- Model: {MODEL}",
        "",
        "---",
        "",
        draft.strip(),
        "",
    ]
    if verdict["verdict"] != "APPROVE":
        lines += ["---", "", "Reviewer's last notes:", "", verdict["reasons"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def draft_supplier_reply(email: str, brief: dict) -> dict:
    """Review step for a supplier reply. Returns draft, verdict, flags, and saved path."""
    handoff("coordinator", "supplier-writer", strip_customers_from_brief(brief),
            "brief, customer names removed")
    facts = ("<email>\n" + scrub_names(email, customer_names()).strip() + "\n</email>\n"
             "<analyst_brief>\n" + json.dumps(strip_customers_from_brief(brief), indent=2)
             + "\n</analyst_brief>")
    draft, verdict, revisions = _review_loop(
        "supplier-writer", lambda fb, prev: write_supplier_reply(email, brief, fb, prev),
        facts, "supplier")

    result = {"kind": "supplier", "part_id": brief.get("part_id"), "draft": draft,
              "verdict": verdict, "revisions": revisions, "flags": [], "path": None}
    if draft.strip() == NO_REPLY:
        result["needs_person"] = False
        print_final_draft("FINAL DRAFT TO SUPPLIER", draft, False)
        handoff("supplier-writer", "coordinator", NO_REPLY, "nothing saved")
        return result

    flags = []
    if verdict["verdict"] != "APPROVE":
        flags.append(f"Reviewer did not approve after {revisions} revision(s).")
    leaked = names_found(draft, customer_names())
    if leaked:
        flags.append(f"Names a customer: {', '.join(leaked)}.")

    sender = re.search(r"^From:.*<([^>]+)>", email, flags=re.MULTILINE)
    to = sender.group(1) if sender else "(supplier)"
    path = _save_draft("supplier", str(brief.get("part_id") or "part"), to,
                       f"Re: {email_subject(email)}", draft, verdict, revisions, flags)
    result.update(flags=flags, needs_person=bool(flags), path=str(path))
    print_final_draft("FINAL DRAFT TO SUPPLIER", draft, result["needs_person"])
    handoff("review step", "coordinator",
            {k: result[k] for k in ("kind", "part_id", "needs_person", "flags", "path")},
            "saved draft")
    return result


def draft_customer_notice(order: dict) -> dict:
    """Review step for one customer notice. Returns draft, verdict, flags, and saved path."""
    facts = order_facts(order)
    handoff("coordinator", "customer-writer", facts, "one order's facts")
    draft, verdict, revisions = _review_loop(
        "customer-writer", lambda fb, prev: write_customer_notice(order, fb, prev),
        facts, "customer")

    flags = []
    if verdict["verdict"] != "APPROVE":
        flags.append(f"Reviewer did not approve after {revisions} revision(s).")
    leaked = names_found(draft, supplier_names())
    if leaked:
        flags.append(f"Names a supplier: {', '.join(leaked)}.")
    if order_has_late_penalty(facts["order_id"]):
        flags.append("Order has a late penalty.")

    row = order_row(facts["order_id"])
    path = _save_draft("customer", facts["order_id"], row["contact_email"],
                       f"Order {facts['order_id']}: updated ship date", draft, verdict,
                       revisions, flags)
    result = {"kind": "customer", "order_id": facts["order_id"], "draft": draft,
              "verdict": verdict, "revisions": revisions, "flags": flags,
              "needs_person": bool(flags), "path": str(path)}
    print_final_draft(f"FINAL DRAFT TO CUSTOMER {facts['order_id']}", draft, result["needs_person"])
    handoff("review step", "coordinator",
            {k: result[k] for k in ("kind", "order_id", "needs_person", "flags", "path")},
            "saved draft")
    return result


# --------------------------------------------------------------------------------------
# Quick end-to-end check (a coordinator would make these choices itself)
# --------------------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Run every specialist once on one supplier email.")
    parser.add_argument("email", type=Path, help="path of one supplier email")
    parser.add_argument("--org", metavar="FOLDER",
                        help="company folder (default: week-05/brookfield-bikes)")
    args = parser.parse_args()
    set_org(args.org)
    email = args.email.read_text(encoding="utf-8")
    print(f"Model: {MODEL}")
    brief = run_analyst(email)
    draft_supplier_reply(email, brief)
    for order in brief.get("orders_at_risk", []):
        draft_customer_notice(order)
    token_report()


if __name__ == "__main__":
    main()
