#!/usr/bin/env python3
"""orchestrator.py - Claude decides which specialists to use for one supplier email.

An agent (claude-sonnet-5) with the system prompt in <company folder>/prompts/orchestrator.txt
gets four tools:
  run_supply_analyst     runs the supply analyst on the email; returns its brief
  draft_supplier_reply   drafts, reviews, and saves a reply to the supplier (needs the brief)
  draft_customer_notice  drafts, reviews, and saves a notice for one order at risk
  finish                 ends the job with a summary for a person, and whether a person must
                         make a decision
The drafting tools run the same review step as pipeline.py (writer -> reviewer, at most 2
revisions, name checks, saved to week-05/drafts/<company folder>). The agent stops after
10 tool calls. Each choice it makes is printed, then the same summary as pipeline.py.

--org names the company folder (CSV files + prompts/); without it, week-05/brookfield-bikes.

Usage (from the repo root):
  .venv/bin/python week-05/orchestrator.py --email week-05/brookfield-bikes/supplier-emails/02-kendall-tire-options.eml
  .venv/bin/python week-05/orchestrator.py --org week-05/copperline-coffee \
      --email week-05/copperline-coffee/supplier-emails/01-danforth-pump-delay.eml \
      --save week-05/runs/copperline-01-orchestrator.txt

--save also writes everything printed to the named text file (UTF-8).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import specialists as sp
from pipeline import Tee, print_summary

MAX_TOOL_CALLS = 10

TOOLS = [
    {
        "name": "run_supply_analyst",
        "description": ("Run the supply analyst on the supplier email. It checks stock, "
                        "shipments, and orders with the supply tools and returns its brief: "
                        "part_id, what_changed, orders_at_risk, options, "
                        "decisions_for_a_person, supplier_questions."),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "draft_supplier_reply",
        "description": ("Draft a reply to the supplier from the email and the analyst's brief "
                        "(run the analyst first). The draft is reviewed, checked, and saved "
                        "for a person; nothing is sent. Returns the review result."),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "draft_customer_notice",
        "description": ("Draft a notice to the customer of one order at risk, by order ID from "
                        "the analyst's orders_at_risk. The draft is reviewed, checked, and "
                        "saved for a person; nothing is sent. Returns the review result."),
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string",
                                        "description": "Order ID, e.g. \"O-1043\"."}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "finish",
        "description": ("End the job. Give a short summary for the company's purchasing manager "
                        "and say whether a person must make a decision."),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string",
                            "description": "Short summary for the purchasing manager."},
                "person_must_decide": {"type": "boolean",
                                       "description": "True if a person must make a decision."},
            },
            "required": ["summary", "person_must_decide"],
            "additionalProperties": False,
        },
    },
]


def draft_result_for_agent(r: dict) -> dict:
    """What the orchestrator sees of a draft: the outcome, not the text."""
    out = {k: r.get(k) for k in ("kind", "order_id", "part_id", "needs_person", "flags", "path")
           if r.get(k) is not None}
    out["reviewer"] = f"{r['verdict']['verdict']} after {r['revisions']} revision(s)"
    if r["draft"].strip() == sp.NO_REPLY:
        out["result"] = "The writer found no reply needed; nothing was saved."
    return out


def run_orchestrator(email_path: Path, org: Path | None = None) -> None:
    sp.set_org(org)
    email = email_path.read_text(encoding="utf-8")
    print(f"Email: {email_path}")
    print(f"Model: {sp.MODEL}")

    brief: dict | None = None
    results: list[dict] = []                 # every draft result, in order
    notices: dict[str, dict] = {}            # order_id -> result, so no order is drafted twice
    supplier_result: dict | None = None
    finished: dict | None = None
    tool_calls = 0

    def run_tool(name: str, args: dict) -> tuple[str, bool]:
        """Run one tool. Returns (result text for the agent, is_error)."""
        nonlocal brief, supplier_result, finished
        if name == "run_supply_analyst":
            if brief is None:
                brief = sp.run_analyst(email)
            return json.dumps(brief), False
        if name == "draft_supplier_reply":
            if brief is None:
                return "Run run_supply_analyst first; the supplier reply needs its brief.", True
            if supplier_result is None:
                supplier_result = sp.draft_supplier_reply(email, brief)
                results.append(supplier_result)
            return json.dumps(draft_result_for_agent(supplier_result)), False
        if name == "draft_customer_notice":
            if brief is None:
                return "Run run_supply_analyst first; notices are only for orders at risk.", True
            order_id = str(args.get("order_id", "")).strip().upper()
            order = next((o for o in brief.get("orders_at_risk", [])
                          if str(o.get("order_id", "")).upper() == order_id), None)
            if order is None:
                at_risk = ", ".join(o.get("order_id", "?") for o in brief.get("orders_at_risk", []))
                return f"{order_id or '(none)'} is not an order at risk. At risk: {at_risk or 'none'}.", True
            if order_id not in notices:
                notices[order_id] = sp.draft_customer_notice(order)
                results.append(notices[order_id])
            return json.dumps(draft_result_for_agent(notices[order_id])), False
        if name == "finish":
            summary, decide = args.get("summary"), args.get("person_must_decide")
            if not isinstance(summary, str) or not summary.strip() or not isinstance(decide, bool):
                return "finish needs summary (text) and person_must_decide (true or false).", True
            finished = {"summary": summary.strip(), "person_must_decide": decide}
            return "Done.", False
        return f"Unknown tool: {name}", True

    messages = [{"role": "user", "content":
                 f"Handle this supplier email.\n\n<email>\n{email.strip()}\n</email>"}]
    stop_note = ""

    while finished is None:
        response = sp.client().messages.create(
            model=sp.MODEL, max_tokens=sp.MAX_TOKENS, system=sp.load_prompt("orchestrator"),
            tools=TOOLS, messages=messages,
        )
        sp.record_usage("orchestrator", response.usage)
        for block in response.content:
            if block.type == "text" and block.text.strip():
                print(f"\nOrchestrator: {block.text.strip()}")

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "refusal":
            stop_note = "The orchestrator declined the request (stop_reason: refusal)."
            break
        if response.stop_reason != "tool_use" or not tool_uses:
            stop_note = f"The orchestrator stopped without calling finish (stop_reason: {response.stop_reason})."
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tu in tool_uses:
            if tool_calls >= MAX_TOOL_CALLS:      # every tool_use still needs a result
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id,
                                     "content": "Not run: the tool-call limit was reached.",
                                     "is_error": True})
                continue
            tool_calls += 1
            args = tu.input or {}
            shown = f"({json.dumps(args, ensure_ascii=False)})" if args and tu.name != "finish" else ""
            print(f"\n>>> CHOICE {tool_calls}/{MAX_TOOL_CALLS}: {tu.name}{shown}")
            try:
                text, is_error = run_tool(tu.name, args)
            except sp.SpecialistError as e:        # tell the agent, don't crash
                text, is_error = f"The specialist failed: {e}", True
            if is_error:
                print(f"    (error) {text}")
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id,
                                 "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": tool_results})

        if finished is None and tool_calls >= MAX_TOOL_CALLS:
            stop_note = f"Stopped after reaching the limit of {MAX_TOOL_CALLS} tool calls without finish."
            break

    print("\n" + "=" * 60)
    print("ORCHESTRATOR'S RESULT")
    print("=" * 60)
    print(f"Tool calls: {tool_calls} of {MAX_TOOL_CALLS}")
    if finished:
        print(f"Person must decide: {'YES' if finished['person_must_decide'] else 'no'}")
        print(f"Summary for a person:\n{finished['summary']}")
    else:
        print(f"Did not finish. {stop_note}")
    if brief is None:
        print("The supply analyst was not run.")

    print_summary(brief, results)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Let Claude choose a company's specialists for one supplier email.")
    parser.add_argument("--org", type=Path, metavar="FOLDER",
                        help="company folder with the CSV files and prompts/ "
                             "(default: week-05/brookfield-bikes)")
    parser.add_argument("--email", required=True, type=Path, help="path of one supplier email")
    parser.add_argument("--save", type=Path, metavar="FILE",
                        help="also write everything printed to this text file (UTF-8)")
    args = parser.parse_args()
    if not args.email.is_file():
        raise SystemExit(f"Email not found: {args.email}")

    if not args.save:
        run_orchestrator(args.email, args.org)
        return

    args.save.parent.mkdir(parents=True, exist_ok=True)
    with args.save.open("w", encoding="utf-8") as f:
        original = sys.stdout
        sys.stdout = Tee(original, f)
        try:
            run_orchestrator(args.email, args.org)
        finally:
            sys.stdout = original
    print(f"\nSaved output to {args.save}")


if __name__ == "__main__":
    main()
