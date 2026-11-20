#!/usr/bin/env python3
"""pipeline.py - a fixed-order pipeline over the specialists in specialists.py.

For one supplier email it runs, always in this order:
  1. the supply analyst (run_analyst), which returns its brief;
  2. a customer notice for each order at risk (skipped if there are none);
  3. a reply to the supplier.
Every draft goes through the review step (writer -> reviewer, at most 2 revisions, name
checks, saved to week-05/drafts/<company folder>). At the end it prints a summary: drafts
saved, drafts marked for a person, decisions for a person, and total tokens.

--org names the company folder (CSV files + prompts/); without it, week-05/brookfield-bikes.

Usage (from the repo root):
  .venv/bin/python week-05/pipeline.py --email week-05/brookfield-bikes/supplier-emails/01-northgate-controller-delay.eml
  .venv/bin/python week-05/pipeline.py --org week-05/copperline-coffee \
      --email week-05/copperline-coffee/supplier-emails/01-danforth-pump-delay.eml \
      --save week-05/runs/copperline-01-pipeline.txt

--save also writes everything printed to the named text file (UTF-8).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import specialists as sp


class Tee:
    """Writes to the terminal and to a file at the same time."""

    def __init__(self, stream, file):
        self.stream, self.file = stream, file

    def write(self, text):
        self.stream.write(text)
        self.file.write(text)
        return len(text)

    def flush(self):
        self.stream.flush()
        self.file.flush()


def run_pipeline(email_path: Path, org: Path | None = None) -> None:
    sp.set_org(org)
    email = email_path.read_text(encoding="utf-8")
    print(f"Email: {email_path}")
    print(f"Model: {sp.MODEL}")
    results = []

    print("\n=== Step 1: supply analyst ===")
    brief = sp.run_analyst(email)

    print("\n=== Step 2: customer notices ===")
    orders = brief.get("orders_at_risk") or []
    if not orders:
        print("No orders at risk; skipping customer notices.")
    for order in orders:
        results.append(sp.draft_customer_notice(order))

    print("\n=== Step 3: supplier reply ===")
    results.append(sp.draft_supplier_reply(email, brief))

    print_summary(brief, results)


def print_summary(brief: dict | None, results: list[dict]) -> None:
    """Drafts saved, drafts marked for a person, decisions for a person, total tokens.

    brief is the analyst's brief, or None if the analyst never ran (orchestrator.py).
    """
    brief = brief or {}
    saved = [r for r in results if r.get("path")]
    flagged = [r for r in saved if r.get("needs_person")]
    decisions = brief.get("decisions_for_a_person") or []

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Part: {brief.get('part_id') or '(unknown)'}")
    print(f"What changed: {brief.get('what_changed') or '(nothing reported)'}")

    print(f"\nDrafts saved: {len(saved)}")
    for r in saved:
        print(f"  - {r['kind']} {r.get('order_id') or r.get('part_id')}: {r['path']}")
    if any(r["draft"].strip() == sp.NO_REPLY for r in results):
        print("  (supplier reply: NO REPLY NEEDED, nothing saved)")

    print(f"\nDrafts marked for a person: {len(flagged)}")
    for r in flagged:
        print(f"  - {r['kind']} {r.get('order_id') or r.get('part_id')}: {'; '.join(r['flags'])}")

    print(f"\nDecisions for a person: {len(decisions)}")
    for d in decisions:
        print(f"  - {d}")

    usage = sp.token_report()
    total_in = sum(u["input"] for u in usage.values())
    total_out = sum(u["output"] for u in usage.values())
    print(f"\nTotal tokens: {total_in + total_out} ({total_in} in / {total_out} out)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a company's specialists on one supplier email.")
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
        run_pipeline(args.email, args.org)
        return

    args.save.parent.mkdir(parents=True, exist_ok=True)
    with args.save.open("w", encoding="utf-8") as f:
        original = sys.stdout
        sys.stdout = Tee(original, f)
        try:
            run_pipeline(args.email, args.org)
        finally:
            sys.stdout = original
    print(f"\nSaved output to {args.save}")


if __name__ == "__main__":
    main()
