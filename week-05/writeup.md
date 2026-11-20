## What I Built

I built a supplier-response team with four AI specialists: a supply analyst, a supplier-response writer, a customer-notice writer, and a reviewer. The team can run under either a fixed pipeline or an orchestrator that decides which specialists to use. I generalized the Brookfield version so that `supply_mcp_server.py`, `specialists.py`, `pipeline.py`, and `orchestrator.py` all take an `--org` option naming a company folder, and read that company's CSV files and specialist prompts from it; without `--org` they still use `brookfield-bikes`. For Copperline Coffee Machines, the programs identify the needed columns from each CSV header instead of assuming the Brookfield names (for example, Copperline's `units` and `ship_by_day` columns are found as the quantity and ship day), each company's drafts are saved in its own folder under `drafts`, the analyst's full brief is printed, and every review step prints the final draft and whether it is marked for a person. I ran all four Copperline supplier emails through both coordinators and saved the eight runs as `runs/copperline-01-pipeline.txt` and `runs/copperline-01-orchestrator.txt` through `copperline-04`.

## Why This Approach

Task A: Agent, because the steps depend on the customer's situation and the tool needs to decide whether and when to look up the order and warranty information before drafting a reply.

Task B: Team, because identifying affected machines, drafting notices for affected customers, and preparing a report for the safety regulator are distinct jobs with different information and audiences.

Task C: Pipeline, because every wholesale order follows the same known sequence of checking stock, drafting an order confirmation, and reviewing it.

Task D: Orchestrator, because the general inbox receives different kinds of messages that require different combinations of specialists, and new kinds of email can require decisions that were not built into a fixed sequence.

## Example Run

```text
Company folder: /Users/wdavis/Library/CloudStorage/OneDrive-Personal/School/UMW-MS in AI in Business/GBUS-562/UMW-GBUS-562/week-05/copperline-coffee
Columns found from each header row:
  parts.csv: part_id=part_id, description=description, on_hand=on_hand, supplier=supplier
  inbound.csv: po_number=po_number, part_id=part_id, supplier=supplier, qty=qty, arrives_in_days=arrives_in_days
  bill-of-materials.csv: product=product, part_id=part_id, per_unit=per_unit
  orders.csv: order_id=order_id, customer=customer, contact_email=contact_email, product=product, qty=units, ship_day=ship_by_day, late_penalty=late_penalty
  suppliers.csv: supplier=supplier, contact_name=contact_name, contact_email=contact_email, part_id=part_id
Email: week-05/copperline-coffee/supplier-emails/02-marlow-boiler-options.eml
Model: claude-sonnet-5
  [tokens] orchestrator: +1494 in / +63 out (total 1494 in / 63 out over 1 call(s))

>>> CHOICE 1/10: run_supply_analyst

----- HANDOFF coordinator -> analyst (supplier email) -----
From: Victor Lindqvist <v.lindqvist@marlowmetal.example>
To: Purchasing <purchasing@copperlinecoffee.example>
Subject: PO-5520 - BL-12 boilers - please choose a shipping option

Hi,

About PO-5520 for 200 BL-12 boilers: our welding cell is running at half
capacity this month, so we can't ship the whole order on time. We can offer
two options:

Option A: Ship 80 boilers on the scheduled date, and the remaining 120 two
weeks after that.

Option B: Ship all 200 boilers together, six days after the scheduled date.

Please let us know which option you'd like within three business days. If we
don't hear from you by then, we'll go with Option B.

Regards,
Victor Lindqvist
Sales Coordinator, Marlow Metalworks
-----------------------------------------------------------
  [tokens] analyst: +2106 in / +153 out (total 2106 in / 153 out over 1 call(s))
  analyst tool call 1/10: get_part {"part_id": "BL-12"}
  analyst tool call 2/10: get_orders_for_part {"part_id": "BL-12"}
  [tokens] analyst: +3384 in / +296 out (total 5490 in / 449 out over 2 call(s))
  analyst tool call 3/10: check_coverage {"part_id": "BL-12", "arrivals": [{"qty": 80, "arrives_in_days": 7}, {"qty": 120, "arrives_in_days": 21}]}
  analyst tool call 4/10: check_coverage {"part_id": "BL-12", "arrivals": [{"qty": 200, "arrives_in_days": 13}]}
  [tokens] analyst: +5521 in / +584 out (total 11011 in / 1033 out over 3 call(s))
  analyst used 4 tool call(s).

----- HANDOFF analyst -> coordinator (the analyst's full brief) -----
{
  "part_id": "BL-12",
  "what_changed": "PO-5520 (200 BL-12 boilers, originally due day 7) will now arrive either as 80 units on day 7 plus 120 units on day 21 (Option A), or as all 200 units on day 13 (Option B, the supplier's default if no choice is made).",
  "orders_at_risk": [
    {
      "order_id": "O-2205",
      "customer": "Tall Pines Coffee House",
      "units_short": 5,
      "ship_day": 17,
      "ready_day": 21,
      "late_penalty": true
    },
    {
      "order_id": "O-2203",
      "customer": "Elm State University Dining",
      "units_short": 40,
      "ship_day": 12,
      "ready_day": 13,
      "late_penalty": true
    }
  ],
  "options": [
    {
      "name": "Option A (80 on day 7, 120 on day 21)",
      "order_ids": [
        "O-2205"
      ]
    },
    {
      "name": "Option B (200 on day 13)",
      "order_ids": [
        "O-2203"
      ]
    }
  ],
  "decisions_for_a_person": [
    "Choose between Option A (puts order O-2205, 5 units short, 4 days late, late penalty applies) and Option B (puts order O-2203, 40 units short, 1 day late, late penalty applies) within the supplier's 3-business-day deadline.",
    "If no decision is communicated in time, the supplier will default to Option B, which risks order O-2203."
  ],
  "supplier_questions": [
    "Which shipping option (A or B) does Copperline want for PO-5520, to be confirmed within three business days?"
  ]
}
---------------------------------------------------------------------
  [tokens] orchestrator: +2061 in / +662 out (total 3555 in / 725 out over 2 call(s))

>>> CHOICE 2/10: draft_customer_notice({"order_id": "O-2205"})

----- HANDOFF coordinator -> customer-writer (one order's facts) -----
{
  "order_id": "O-2205",
  "customer": "Tall Pines Coffee House",
  "product": "Cafe One",
  "quantity": 25,
  "planned_ship_day": 17,
  "expected_ship_day": 21,
  "days_late": 4,
  "days_counted_from": "today (day 0)",
  "note": ""
}
----------------------------------------------------------------------
  [tokens] customer-writer: +372 in / +160 out (total 372 in / 160 out over 1 call(s))

----- HANDOFF customer-writer -> reviewer (draft 1) -----
Subject: Update on Your Order O-2205

Dear Tall Pines Coffee House,

We're writing to update you on order O-2205 for 25 units of the Cafe One. The order is now expected to ship 4 days later than originally planned.

We apologize for this delay. It is due to a delay in a part from one of our suppliers.

We will keep you informed of any further updates regarding your order. Thank you for your patience and understanding.

Customer Service, Copperline Coffee Machines
---------------------------------------------------------
  [tokens] reviewer: +627 in / +260 out (total 627 in / 260 out over 1 call(s))

----- HANDOFF reviewer -> review step (verdict) -----
APPROVE
-----------------------------------------------------

FINAL DRAFT TO CUSTOMER O-2205
Subject: Update on Your Order O-2205

Dear Tall Pines Coffee House,

We're writing to update you on order O-2205 for 25 units of the Cafe One. The order is now expected to ship 4 days later than originally planned.

We apologize for this delay. It is due to a delay in a part from one of our suppliers.

We will keep you informed of any further updates regarding your order. Thank you for your patience and understanding.

Customer Service, Copperline Coffee Machines
Marked for a person: yes

----- HANDOFF review step -> coordinator (saved draft) -----
{
  "kind": "customer",
  "order_id": "O-2205",
  "needs_person": true,
  "flags": [
    "Order has a late penalty."
  ],
  "path": "/Users/wdavis/Library/CloudStorage/OneDrive-Personal/School/UMW-MS in AI in Business/GBUS-562/UMW-GBUS-562/week-05/drafts/copperline-coffee/20261120-094624-customer-O-2205.md"
}
------------------------------------------------------------

>>> CHOICE 3/10: draft_customer_notice({"order_id": "O-2203"})

----- HANDOFF coordinator -> customer-writer (one order's facts) -----
{
  "order_id": "O-2203",
  "customer": "Elm State University Dining",
  "product": "Cafe One",
  "quantity": 50,
  "planned_ship_day": 12,
  "expected_ship_day": 13,
  "days_late": 1,
  "days_counted_from": "today (day 0)",
  "note": ""
}
----------------------------------------------------------------------
  [tokens] customer-writer: +369 in / +176 out (total 741 in / 336 out over 2 call(s))

----- HANDOFF customer-writer -> reviewer (draft 1) -----
Subject: Update on Your Order O-2203

Dear Elm State University Dining,

We're writing to update you on order O-2203 for 50 Cafe One units. This order is now expected to ship 1 day later than originally planned.

We apologize for this delay. It is due to a delay in a part from one of our suppliers.

We appreciate your patience and understanding, and we will keep you informed if anything further changes with your order.

Thank you for choosing Copperline Coffee Machines.

Customer Service, Copperline Coffee Machines
---------------------------------------------------------
  [tokens] reviewer: +640 in / +7 out (total 1267 in / 267 out over 2 call(s))

----- HANDOFF reviewer -> review step (verdict) -----
APPROVE
-----------------------------------------------------

FINAL DRAFT TO CUSTOMER O-2203
Subject: Update on Your Order O-2203

Dear Elm State University Dining,

We're writing to update you on order O-2203 for 50 Cafe One units. This order is now expected to ship 1 day later than originally planned.

We apologize for this delay. It is due to a delay in a part from one of our suppliers.

We appreciate your patience and understanding, and we will keep you informed if anything further changes with your order.

Thank you for choosing Copperline Coffee Machines.

Customer Service, Copperline Coffee Machines
Marked for a person: yes

----- HANDOFF review step -> coordinator (saved draft) -----
{
  "kind": "customer",
  "order_id": "O-2203",
  "needs_person": true,
  "flags": [
    "Order has a late penalty."
  ],
  "path": "/Users/wdavis/Library/CloudStorage/OneDrive-Personal/School/UMW-MS in AI in Business/GBUS-562/UMW-GBUS-562/week-05/drafts/copperline-coffee/20261120-094626-customer-O-2203.md"
}
------------------------------------------------------------
  [tokens] orchestrator: +3120 in / +512 out (total 6675 in / 1237 out over 3 call(s))

>>> CHOICE 4/10: finish

============================================================
ORCHESTRATOR'S RESULT
============================================================
Tool calls: 4 of 10
Person must decide: YES
Summary for a person:
Marlow Metalworks can't ship PO-5520 (200 BL-12 boilers) on time due to reduced capacity. They offered two options: (A) 80 units on schedule + 120 units two weeks late, or (B) all 200 units six days late (their default if we don't respond within 3 business days). Impact analysis: Option A risks order O-2205 (Tall Pines, 5 units short, 4 days late, penalty applies); Option B risks order O-2203 (Elm State University Dining, 40 units short, 1 day late, penalty applies). I've drafted customer-risk notices for both O-2205 and O-2203 so they're ready regardless of which option is chosen. A person must choose Option A or B within the supplier's deadline - this is a business tradeoff (smaller/later shortfall vs. larger/sooner shortfall, both incurring penalties) that requires judgment on customer relationships and penalty costs. Once the decision is made, I can draft the supplier reply confirming the choice.

============================================================
SUMMARY
============================================================
Part: BL-12
What changed: PO-5520 (200 BL-12 boilers, originally due day 7) will now arrive either as 80 units on day 7 plus 120 units on day 21 (Option A), or as all 200 units on day 13 (Option B, the supplier's default if no choice is made).

Drafts saved: 2
  - customer O-2205: /Users/wdavis/Library/CloudStorage/OneDrive-Personal/School/UMW-MS in AI in Business/GBUS-562/UMW-GBUS-562/week-05/drafts/copperline-coffee/20261120-094624-customer-O-2205.md
  - customer O-2203: /Users/wdavis/Library/CloudStorage/OneDrive-Personal/School/UMW-MS in AI in Business/GBUS-562/UMW-GBUS-562/week-05/drafts/copperline-coffee/20261120-094626-customer-O-2203.md

Drafts marked for a person: 2
  - customer O-2205: Order has a late penalty.
  - customer O-2203: Order has a late penalty.

Decisions for a person: 2
  - Choose between Option A (puts order O-2205, 5 units short, 4 days late, late penalty applies) and Option B (puts order O-2203, 40 units short, 1 day late, late penalty applies) within the supplier's 3-business-day deadline.
  - If no decision is communicated in time, the supplier will default to Option B, which risks order O-2203.

=== Tokens by specialist ===
  orchestrator       3 call(s)      6675 in     1237 out
  analyst            3 call(s)     11011 in     1033 out
  customer-writer    2 call(s)       741 in      336 out
  reviewer           2 call(s)      1267 in      267 out
  TOTAL                            19694 in     2873 out

Total tokens: 22567 (19694 in / 2873 out)
```

## Reflection

Email 1 reading: Matches. Diane wrote that 40 pumps would arrive on the scheduled date and "the other 160 will follow 15 days later," and the what_changed line in my saved pipeline run gave day 19 for the 160 pumps, which is 15 days after the scheduled day 4.

Email 1 customer names: No. The supplier reply in my saved pipeline run named no customer; it answered Diane's request for a list of customer orders by saying Copperline is "not able to share customer names or order details," and gave only totals instead: 55 units at risk across multiple orders, 10 to 25 units short per order.

Email 4 orchestrator: Supply analyst. After the analyst found no orders at risk, the orchestrator went straight to finish without calling either writer or the reviewer. The pipeline also found no orders at risk and skipped the customer notices, but its fixed sequence still ran the supplier writer, which returned NO REPLY NEEDED, so no draft was reviewed or saved.
