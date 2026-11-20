#!/usr/bin/env python3
"""supply_mcp_server.py - MCP server with a company's supply data tools.

It reads the CSV files in a company folder (default: week-05/brookfield-bikes; choose another
with --org) and offers three read-only tools:

  get_part             a part's stock on hand, its scheduled shipments, and the products that use it
  get_orders_for_part  the open orders that need a part: units needed (quantity x parts per
                       unit), ship day, and late penalty
  check_coverage       given a part and a new list of arrivals (which replaces that part's
                       scheduled shipments), says for each order whether it is covered, or how
                       many units it is short and the first day it can ship

A company folder holds parts.csv, inbound.csv, bill-of-materials.csv, orders.csv, and
suppliers.csv. Column names differ between companies (Brookfield's orders have model, qty,
ship_in_days; Copperline's have product, units, ship_by_day), so each file's header row is
matched to the roles the tools need (see COLUMN_ROLES), and the rest of the code only sees
those role names.

All days are counted from today (day 0). Stock on hand is available on day 0; a shipment that
arrives on day N can be used for an order that ships on day N.

Coverage rule: orders are filled complete, in ship-day order (ties by order id). An order is
never shipped partly, and a later order never jumps ahead of an earlier one, so an order that
is short holds up every order after it.

The CSV files are re-read on every call, so edits take effect without restarting the server.

Usage (from the repo root):
  .venv/bin/python week-05/supply_mcp_server.py [--org week-05/copperline-coffee]      # run (stdio)
  .venv/bin/python week-05/supply_mcp_server.py --org week-05/copperline-coffee --check PU-20
  .venv/bin/python week-05/supply_mcp_server.py --org week-05/copperline-coffee --columns

The server talks MCP over stdio, so stdout is reserved for protocol messages: everything
else goes to stderr.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------------------
# Configuration (paths are relative to this file, so the server works from any directory)
# --------------------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent              # .../UMW-GBUS-562/week-05
DEFAULT_ORG_DIR = HERE / "brookfield-bikes"
DATA_DIR = DEFAULT_ORG_DIR                           # changed by set_org()
SERVER_NAME = "supply-tools"
CSV_FILES = ["parts.csv", "inbound.csv", "bill-of-materials.csv", "orders.csv", "suppliers.csv"]

COVERAGE_RULE = ("Orders are filled complete, in ship-day order; a short order holds up the "
                 "orders after it. Days are counted from today (day 0); stock on hand is "
                 "available on day 0.")


def log(message: str) -> None:
    """Write a message to stderr (stdout carries the MCP protocol)."""
    print(message, file=sys.stderr, flush=True)


class DataError(Exception):
    """A problem with a request or with the CSV data, reported back to the caller."""


def resolve_org(path: str | Path | None) -> Path:
    """The company folder for path (default: brookfield-bikes), checked for the CSV files."""
    org = Path(path).expanduser().resolve() if path else DEFAULT_ORG_DIR
    if not org.is_dir():
        raise SystemExit(f"Company folder not found: {org}")
    missing = [f for f in CSV_FILES if not (org / f).is_file()]
    if missing:
        raise SystemExit(f"{org} is missing {', '.join(missing)}.")
    return org


def set_org(path: str | Path | None) -> Path:
    """Point the tools at a company folder. Returns the resolved folder."""
    global DATA_DIR
    DATA_DIR = resolve_org(path)
    return DATA_DIR


# --------------------------------------------------------------------------------------
# Column roles: which header holds what, worked out from each file's header row
# --------------------------------------------------------------------------------------

def _tokens(header: str) -> list[str]:
    """'Ship By Day' -> ['ship', 'by', 'day']; 'qty_per_bike' -> ['qty', 'per', 'bike']."""
    return [t for t in re.split(r"[^a-z0-9]+", header.lower()) if t]


def _has(*words: str) -> Callable[[list[str]], bool]:
    return lambda t: all(w in t for w in words)


def _any(*words: str) -> Callable[[list[str]], bool]:
    return lambda t: any(w in t for w in words)


def _starts(*prefixes: str) -> Callable[[list[str]], bool]:
    return lambda t: any(tok.startswith(p) for tok in t for p in prefixes)


def _not(test: Callable[[list[str]], bool]) -> Callable[[list[str]], bool]:
    return lambda t: not test(t)


def _all(*tests: Callable[[list[str]], bool]) -> Callable[[list[str]], bool]:
    return lambda t: all(test(t) for test in tests)


QUANTITY_WORDS = ("qty", "quantity", "units", "count", "amount", "bikes", "machines")
PRODUCT_WORDS = ("product", "model", "item", "sku", "machine")

# For each file: role -> test on a header's tokens. A role must match exactly one header.
COLUMN_ROLES: dict[str, dict[str, Callable[[list[str]], bool]]] = {
    "parts.csv": {
        "part_id": _all(_has("part"), _not(_any("description", "desc"))),
        "description": _starts("desc"),
        "on_hand": _any("hand", "stock", "inventory"),
        "supplier": _all(_any("supplier", "vendor"), _not(_any("email", "contact"))),
    },
    "inbound.csv": {
        "po_number": _any("po", "purchase"),
        "part_id": _has("part"),
        "supplier": _all(_any("supplier", "vendor"), _not(_any("email", "contact"))),
        "qty": _all(_any(*QUANTITY_WORDS), _not(_any("per"))),
        "arrives_in_days": _starts("arriv", "eta", "due"),
    },
    "bill-of-materials.csv": {
        "product": _any(*PRODUCT_WORDS),
        "part_id": _has("part"),
        "per_unit": _any("per"),                       # per_unit, qty_per_bike, parts_per_unit
    },
    "orders.csv": {
        "order_id": _all(_has("order"), _not(_any("email"))),
        "customer": _all(_any("customer", "client"), _not(_any("email"))),
        "contact_email": _any("email"),
        "product": _any(*PRODUCT_WORDS),
        "qty": _all(_any(*QUANTITY_WORDS), _not(_any("per"))),
        "ship_day": _starts("ship"),                   # ship_in_days, ship_by_day
        "late_penalty": _starts("penalt"),
    },
    "suppliers.csv": {
        "supplier": _all(_any("supplier", "vendor", "company"), _not(_any("email", "contact"))),
        "contact_name": _all(_any("contact"), _not(_any("email"))),
        "contact_email": _any("email"),
        "part_id": _has("part"),
    },
}


def column_map(name: str, headers: list[str]) -> dict[str, str]:
    """Role -> header for one file, from its header row. Raises DataError if unclear."""
    roles = COLUMN_ROLES[name]
    found: dict[str, str] = {}
    for role, test in roles.items():
        exact = [h for h in headers if h.lower() == role]
        matches = exact or [h for h in headers if test(_tokens(h))]
        if len(matches) != 1:
            what = "no column" if not matches else f"several columns ({', '.join(matches)})"
            raise DataError(f"{name}: found {what} for '{role}'. Header row: {', '.join(headers)}.")
        found[role] = matches[0]
    if len(set(found.values())) != len(found):
        raise DataError(f"{name}: one column matched two roles: {found}.")
    return found


def read_csv(name: str) -> list[dict[str, str]]:
    """A file's rows with its own column names, from the current company folder."""
    path = DATA_DIR / name
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            return [{k.strip(): (v or "").strip() for k, v in row.items() if k}
                    for row in csv.DictReader(f)]
    except OSError as e:
        raise DataError(f"Could not read {name}: {e}") from e


def read_headers(name: str) -> list[str]:
    path = DATA_DIR / name
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            return [h.strip() for h in next(csv.reader(f), []) if h.strip()]
    except OSError as e:
        raise DataError(f"Could not read {name}: {e}") from e


def read_table(name: str) -> list[dict[str, str]]:
    """A file's rows keyed by role (e.g. orders.csv -> order_id, product, qty, ship_day...)."""
    cols = column_map(name, read_headers(name))
    return [{role: row.get(header, "") for role, header in cols.items()} for row in read_csv(name)]


def describe_columns() -> str:
    """One line per file: role=header, for printing which columns were found."""
    lines = []
    for name in CSV_FILES:
        cols = column_map(name, read_headers(name))
        lines.append(f"  {name}: " + ", ".join(f"{r}={h}" for r, h in cols.items()))
    return "\n".join(lines)


def to_int(value: str, what: str) -> int:
    try:
        return int(value)
    except ValueError as e:
        raise DataError(f"{what} is not a whole number: {value!r}") from e


def to_bool(value: str) -> bool:
    return value.strip().lower() in {"yes", "y", "true", "1"}


def find_part(part_id: str) -> dict[str, str]:
    """Return the parts.csv row for part_id (case doesn't matter), or raise DataError."""
    wanted = (part_id or "").strip().upper()
    parts = read_table("parts.csv")
    for row in parts:
        if row["part_id"].upper() == wanted:
            return row
    known = ", ".join(r["part_id"] for r in parts) or "none"
    raise DataError(f"Unknown part_id {part_id!r}. Known parts: {known}.")


def scheduled_shipments(part_id: str) -> list[dict]:
    rows = [r for r in read_table("inbound.csv") if r["part_id"].upper() == part_id]
    shipments = [{
        "po_number": r["po_number"],
        "supplier": r["supplier"],
        "qty": to_int(r["qty"], f"inbound.csv quantity for {r['po_number']}"),
        "arrives_in_days": to_int(r["arrives_in_days"],
                                  f"inbound.csv arrival day for {r['po_number']}"),
    } for r in rows]
    return sorted(shipments, key=lambda s: (s["arrives_in_days"], s["po_number"]))


def parts_per_unit(part_id: str) -> dict[str, int]:
    """Product -> how many of this part one unit of that product uses."""
    uses: dict[str, int] = {}
    for r in read_table("bill-of-materials.csv"):
        if r["part_id"].upper() == part_id:
            qty = to_int(r["per_unit"], f"bill-of-materials.csv parts per unit for {r['product']}")
            uses[r["product"]] = uses.get(r["product"], 0) + qty
    return uses


def orders_needing(part_id: str) -> list[dict]:
    """Open orders that need part_id, in ship-day order (ties by order id)."""
    uses = parts_per_unit(part_id)
    orders = []
    for r in read_table("orders.csv"):
        per_unit = uses.get(r["product"])
        if not per_unit:
            continue
        quantity = to_int(r["qty"], f"orders.csv quantity for {r['order_id']}")
        orders.append({
            "order_id": r["order_id"],
            "customer": r["customer"],
            "product": r["product"],
            "quantity": quantity,
            "parts_per_unit": per_unit,
            "units_needed": quantity * per_unit,
            "ship_day": to_int(r["ship_day"], f"orders.csv ship day for {r['order_id']}"),
            "late_penalty": to_bool(r["late_penalty"]),
        })
    return sorted(orders, key=lambda o: (o["ship_day"], o["order_id"]))


# --------------------------------------------------------------------------------------
# Tool logic (plain functions, so they can be tested without MCP)
# --------------------------------------------------------------------------------------

def part_info(part_id: str) -> dict:
    part = find_part(part_id)
    pid = part["part_id"]
    shipments = scheduled_shipments(pid)
    return {
        "part_id": pid,
        "description": part["description"],
        "supplier": part["supplier"],
        "on_hand": to_int(part["on_hand"], f"parts.csv on_hand for {pid}"),
        "scheduled_shipments": shipments,
        "total_scheduled": sum(s["qty"] for s in shipments),
        "used_in_products": [{"product": p, "parts_per_unit": n}
                             for p, n in parts_per_unit(pid).items()],
        "days_counted_from": "today (day 0)",
    }


def orders_info(part_id: str) -> dict:
    pid = find_part(part_id)["part_id"]
    orders = orders_needing(pid)
    return {
        "part_id": pid,
        "orders": orders,
        "total_units_needed": sum(o["units_needed"] for o in orders),
        "sorted_by": "ship_day, then order_id",
        "days_counted_from": "today (day 0)",
    }


def coverage(part_id: str, arrivals: list[dict]) -> dict:
    """Fill orders complete, in ship-day order, from stock on hand plus `arrivals`.

    For order i, with D_i = units needed by orders 1..i together and S(t) = stock on hand plus
    everything arriving on or before day t, the first day it can ship is the first day t
    with S(t) >= D_i (later orders wait for earlier ones, so D_i includes them). It is
    covered if that day is on or before its ship day; otherwise it is short by
    min(units_needed, D_i - S(ship_day)).
    """
    part = find_part(part_id)
    pid = part["part_id"]
    on_hand = to_int(part["on_hand"], f"parts.csv on_hand for {pid}")

    clean: list[dict] = []
    for i, a in enumerate(arrivals or [], start=1):
        qty, day = a.get("qty"), a.get("arrives_in_days")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 0:
            raise DataError(f"Arrival {i}: qty must be a whole number 0 or more, got {qty!r}.")
        if not isinstance(day, int) or isinstance(day, bool) or day < 0:
            raise DataError(f"Arrival {i}: arrives_in_days must be a whole number 0 or more "
                            f"(days from today), got {day!r}.")
        clean.append({"qty": qty, "arrives_in_days": day})
    clean.sort(key=lambda a: a["arrives_in_days"])

    def supply_by(day: int) -> int:
        return on_hand + sum(a["qty"] for a in clean if a["arrives_in_days"] <= day)

    # Days on which supply can change: today, and each arrival day.
    supply_days = sorted({0, *(a["arrives_in_days"] for a in clean)})

    results = []
    demand = 0
    for o in orders_needing(pid):
        demand += o["units_needed"]
        ready_day = next((d for d in supply_days if supply_by(d) >= demand), None)
        entry = {
            "order_id": o["order_id"],
            "customer": o["customer"],
            "product": o["product"],
            "units_needed": o["units_needed"],
            "ship_day": o["ship_day"],
            "late_penalty": o["late_penalty"],
        }
        if ready_day is not None and ready_day <= o["ship_day"]:
            entry["status"] = "covered"
        else:
            entry["status"] = "short"
            entry["units_short"] = min(o["units_needed"], demand - supply_by(o["ship_day"]))
            entry["ready_day"] = ready_day      # None: these arrivals never cover it
            entry["days_late"] = None if ready_day is None else ready_day - o["ship_day"]
        results.append(entry)

    short = [r for r in results if r["status"] == "short"]
    total = on_hand + sum(a["qty"] for a in clean)
    return {
        "part_id": pid,
        "on_hand": on_hand,
        "arrivals_used": clean,
        "total_supply": total,
        "total_units_needed": demand,
        "orders": results,
        "orders_covered": len(results) - len(short),
        "orders_short": [r["order_id"] for r in short],
        "rule": COVERAGE_RULE,
        "note": ("ready_day null means these arrivals never cover the order."
                 if any(r["ready_day"] is None for r in short) else ""),
    }


# --------------------------------------------------------------------------------------
# MCP server
# --------------------------------------------------------------------------------------

class Arrival(BaseModel):
    """One shipment of the part."""
    qty: int = Field(ge=0, description="Number of units in this shipment.")
    arrives_in_days: int = Field(ge=0, description="Day it arrives, counted from today (day 0).")


def create_server():
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    read_only = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
    mcp = MCPServer(
        name=SERVER_NAME,
        instructions=(f"Supply data tools for the company in {DATA_DIR.name}. Stock, shipment, "
                      "order and coverage numbers must come from these tools. Days are "
                      "counted from today (day 0)."),
    )

    def call(fn, *args):
        try:
            return fn(*args)
        except DataError as e:
            raise ToolError(str(e)) from e

    @mcp.tool(annotations=read_only)
    def get_part(part_id: str) -> dict:
        """Get one part's stock on hand, its scheduled shipments, and the products that use it.

        Returns the description, supplier, on_hand, scheduled_shipments (po_number, supplier,
        qty, arrives_in_days), total_scheduled, and used_in_products (product, parts_per_unit).

        Args:
            part_id: The part number, e.g. "MC-500".
        """
        return call(part_info, part_id)

    @mcp.tool(annotations=read_only)
    def get_orders_for_part(part_id: str) -> dict:
        """Get the open customer orders that need a part, in ship-day order.

        Each order has order_id, customer, product, quantity (units of the product ordered),
        parts_per_unit, units_needed (quantity times parts per unit), ship_day (days from
        today), and late_penalty (true or false).

        Args:
            part_id: The part number, e.g. "TR-29".
        """
        return call(orders_info, part_id)

    @mcp.tool(annotations=read_only)
    def check_coverage(part_id: str, arrivals: list[Arrival]) -> dict:
        """Check which orders a part's supply covers, given a new list of arrivals.

        The arrivals REPLACE all of the part's scheduled shipments; stock on hand is still
        counted. To check the current schedule, pass the shipments from get_part. Orders are
        filled complete, in ship-day order, so an order that is short holds up the orders after
        it. For each order the result gives status "covered", or status "short" with
        units_short (units missing on its ship day), ready_day (first day it can ship, or null
        if these arrivals never cover it) and days_late.

        Args:
            part_id: The part number, e.g. "MC-500".
            arrivals: Every shipment of this part still to come, each with qty and
                arrives_in_days (days from today). An empty list means nothing more arrives.
        """
        return call(coverage, part_id, [a.model_dump() for a in arrivals])

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP server with a company's supply data tools.")
    parser.add_argument("--org", metavar="FOLDER",
                        help="company folder with the CSV files (default: week-05/brookfield-bikes)")
    parser.add_argument("--check", metavar="PART",
                        help="print coverage for PART with its current scheduled shipments, then exit")
    parser.add_argument("--columns", action="store_true",
                        help="print which column holds each role in each file, then exit")
    args = parser.parse_args()
    set_org(args.org)

    try:
        if args.columns:
            print(f"Company folder: {DATA_DIR}")
            print(describe_columns())
            return
        if args.check:
            info = part_info(args.check)
            print(json.dumps(coverage(info["part_id"], info["scheduled_shipments"]), indent=2))
            return
    except DataError as e:
        raise SystemExit(f"Error: {e}")

    try:
        describe_columns()                       # fail early if a header can't be matched
    except DataError as e:
        raise SystemExit(f"Error: {e}")
    log(f"{SERVER_NAME} MCP server ready (data: {DATA_DIR}).")
    create_server().run("stdio")


if __name__ == "__main__":
    main()
