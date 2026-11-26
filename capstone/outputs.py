"""The two durable outputs, and the fixed input for the Independent Review. Plain code, no model.

Both outputs are projections of one frozen framing state:
- the Problem-Framing Report, for people, which alone carries the Independent Review in its last section;
- the AI handoff, for another AI, built from the frozen state only. It takes no review argument, so no
  review content can reach it.
The review input is built from the frozen state and the user's own words only. Tool turns, reflections,
questions and examples the tool offered are never passed to it.
"""

CONFIRM_MEANING = (
    "This accurately represents my current understanding for now, including appropriately represented "
    "beliefs, unknowns and unresolved material."
)
CONFIRM_LIMIT = (
    "Confirming does not mean that anything here is proven or complete, and it does not turn an assumption "
    "into a fact or make one of the tool's assumptions yours."
)
PAUSE_MEANING = (
    "This captures useful progress and known state, but I am not confirming the integrated understanding yet."
)

KINDS = ["situation", "effect", "scope", "constraint", "desired_state", "proposed_solution", "solution_reason",
         "not_known"]
STANDING_REPORT = {"reported": "", "belief": " (the user's view)", "estimate": " (the user's estimate)"}
STANDING_STATE = {"reported": "", "belief": " [the user's belief]", "estimate": " [the user's estimate]"}
STATEMENT_LABELS = {
    "view": "Draft wording.",
    "confirm": "The user confirmed this wording for now.",
    "pause": "Draft wording, not confirmed.",
}
NO_STATEMENT = "There is not enough yet for a problem statement."
NO_DESIRED_STATE = "Not described yet. The session did not establish what a better situation would look like."
SOLUTION_NOTE = ("This is an idea under consideration, kept apart from the problem. This report does not assess "
                 "whether it is a good solution.")
CONTRACT = [
    "Part A is what the user supplied, with its standing. It is the basis.",
    "Part B is the tool's integrated interpretation of Part A. It is derived, not the user's words.",
    "Keep beliefs, estimates, unknowns and qualifications as they are. Do not silently resolve ambiguity, turn a "
    "belief or estimate into a fact, or present an interpretation as something the user said.",
    "A proposed solution is an idea the user is considering. It is not a requirement or a decision, and nothing "
    "here shows it is right.",
    "A desired state describes what a better condition would look like, not how it would be brought about.",
    "Nothing here says what the user wants to do next. Use it as context for whatever they ask.",
]
STATUS_TEXT = {  # what the user affirmed, quoted, then what it does not mean
    "confirm": ("CONFIRMED BY THE USER", f'The user confirmed: "{CONFIRM_MEANING}" {CONFIRM_LIMIT} '
                                         "It does not mean a solution was chosen."),
    "pause": ("PAUSED, NOT CONFIRMED", f'The user paused: "{PAUSE_MEANING}" The problem statement is a draft.'),
}


def items(basis: dict, kind: str, standing: dict, relation: str) -> list[str]:
    """Return the user's items of one kind, each with its standing and any relationship."""
    return [item["text"] + standing[item["standing"]] + (relation.format(item["relation"]) if item["relation"] else "")
            for item in basis["user_material"] if item["kind"] == kind]


def amount_label(item: dict) -> str:
    """Return one quantity the user did not supply, with its basis."""
    if item["basis"] == "derived":
        return f"{item['value']} (derived from {', '.join(item['from'])}): {item['note']}"
    return f"{item['value']} ({item['basis'].replace('_', ' ')}, not established): {item['note']}"


def held_lines(held: list[dict]) -> list[str]:
    return [f"{entry['value']}: presented as established, but the user did not supply it" for entry in held]


def framing_sections(basis: dict, held: list[dict], statement_label: str) -> list[tuple[str, list]]:
    """Return the human framing sections: (heading, blocks). A block is a paragraph or a list of bullets.

    Used for the ending view and for the report, so the two cannot differ. Empty sections are left out,
    except desired state, whose absence is itself worth saying.
    """
    u = basis["understanding"]
    r = lambda kind: items(basis, kind, STANDING_REPORT, " — {}")
    sections = [("The problem in brief", [u["statement"] or NO_STATEMENT] + ([statement_label] if u["statement"] else []))]
    if u["problem"]:
        sections.append(("Current understanding", [u["problem"], "This is the tool's integrated reading of what the user said."]))

    def labeled(pairs):
        blocks = []
        for label, values in pairs:
            if values:
                blocks += ([label] if label else []) + [values]
        return blocks

    happening = labeled([("", r("situation")), ("Effects:", r("effect")), ("Who is affected:", u["affected"]),
                         ("When and where it applies:", r("scope")), ("Patterns and cases the tool sees:", u["cases"])])
    if happening:
        sections.append(("What is happening", happening))
    desired = r("desired_state")
    sections.append(("What better would look like",
                     labeled([("", desired), ("The tool's reading:", [u["desired_state"]] if u["desired_state"] else [])])
                     if desired else [NO_DESIRED_STATE]))
    limits = labeled([("Constraints:", r("constraint")), ("Assumptions the tool is making:", u["assumptions"]),
                      ("What the user said they do not know:", r("not_known")), ("Other open questions:", u["unknowns"]),
                      ("Amounts the user did not give:", [amount_label(q) for q in basis["quantities"]]),
                      ("Held, not established:", held_lines(held))])
    if limits:
        sections.append(("Constraints and open questions", limits))
    solution = r("proposed_solution")
    if solution:
        sections.append(("A solution under consideration",
                         labeled([("", solution), ("Why it appeals to the user:", r("solution_reason"))])
                         + ([u["solution_standing"]] if u["solution_standing"] else []) + [SOLUTION_NOTE]))
    return sections


def markdown_blocks(blocks: list) -> str:
    return "\n\n".join("\n".join(f"- {item}" for item in block) if isinstance(block, list) else block for block in blocks)


def review_section(review: dict | None) -> str:
    """The Independent Review, the only place review content appears."""
    lines = ["## Independent Review",
             "_A separate assessment of the framing above, made after the user confirmed or paused. It does not change "
             "the framing, and the framing does not depend on it._"]
    if review is None:
        return "\n\n".join(lines + ["The Independent Review could not be produced for this session. The framing above is unaffected."])
    lines.append(review["overall"])
    if review["strengths"]:
        lines.append("**Strengths**\n\n" + "\n".join(f"- {s}" for s in review["strengths"]))
    if review["limitations"]:
        lines.append("**Limitations**\n\n" + "\n".join(f"- {x['observation']} *Why it matters:* {x['why_it_matters']}"
                                                         for x in review["limitations"]))
    lines.append("**How well the problem statement fits the framing**\n\n" + review["statement_fit"])
    if review["optional_evidence"]:
        lines.append("**Optional evidence that could strengthen the framing**\n\nNone of this is required.\n\n"
                     + "\n".join(f"- {x['evidence']} *Why it matters:* {x['why_it_matters']}" for x in review["optional_evidence"]))
    return "\n\n".join(lines)


def report_markdown(record: dict, review: dict | None) -> str:
    """The Problem-Framing Report: framing from the frozen state, then the separately returned review."""
    title, meaning = STATUS_TEXT[record["status"]]
    parts = ["# Problem-Framing Report", f"**Status: {title}**\n\n{meaning}", f"Ended {record['ended']}."]
    for heading, blocks in framing_sections(record["basis"], record["held"], STATEMENT_LABELS[record["status"]]):
        parts.append(f"## {heading}\n\n{markdown_blocks(blocks)}")
    parts.append(review_section(review))
    return "\n\n".join(parts) + "\n"


def state_parts(record: dict) -> list[str]:
    """Part A and Part B of the semantic state, as written for an AI and for the review input."""
    basis = record["basis"]
    u = basis["understanding"]
    a = lambda kind: items(basis, kind, STANDING_STATE, " (relation: {})")
    section = lambda title, values: f"### {title}\n" + "\n".join(f"- {v}" for v in values) if values else ""
    part_a = ["## Part A. What the user supplied"]
    for title, kind in [("Situation", "situation"), ("Effects", "effect"), ("When and where it applies", "scope"),
                        ("Constraints", "constraint"), ("Desired state", "desired_state"),
                        ("Proposed solution (the user's idea, not decided)", "proposed_solution"),
                        ("Reasons the user gave for it", "solution_reason"),
                        ("What the user said they do not know", "not_known")]:
        values = a(kind)
        if kind == "desired_state" and not values:
            part_a.append("### Desired state\nNot stated by the user.")
        elif values:
            part_a.append(section(title, values))
    statement_label = "the draft the user confirmed" if record["status"] == "confirm" else "a draft, not confirmed"
    part_b = ["## Part B. Current understanding (derived by the tool)",
              f"### The problem\n{u['problem']}" if u["problem"] else "",
              section("Who is affected", u["affected"]),
              section("Patterns and cases (the tool's reading)", u["cases"]),
              f"### Desired state (the tool's reading)\n{u['desired_state']}" if u["desired_state"] else "",
              f"### Standing of the proposed solution\n{u['solution_standing']}" if u["solution_standing"] else "",
              section("The tool's assumptions (not supplied by the user)", u["assumptions"]),
              section("Not known", u["unknowns"]),
              section("Amounts the user did not give", [amount_label(q) for q in basis["quantities"]]),
              section("Held: presented as established, but not supplied by the user", [e["value"] for e in record["held"]]),
              f"### Problem statement ({statement_label})\n{u['statement']}" if u["statement"] else
              f"### Problem statement\n{NO_STATEMENT}"]
    return [p for p in part_a + part_b if p]


def handoff_markdown(record: dict) -> str:
    """The AI handoff: status, a short reading contract, and the semantic state. Nothing else."""
    title, meaning = STATUS_TEXT[record["status"]]
    return "\n\n".join([
        "# Problem-Framing State",
        "Written by a problem-framing tool at the end of one session. It stands in for the conversation, which is not included.",
        f"## Status\n{title}. {meaning}",
        "## How to read this\n" + "\n".join(f"- {line}" for line in CONTRACT),
        *state_parts(record),
    ]) + "\n"


def review_input(record: dict, said: list[str]) -> str:
    """The Independent Review's whole input: status, the frozen state, and the user's own words."""
    title, meaning = STATUS_TEXT[record["status"]]
    words = "\n".join(f"- {message}" for message in said)
    return (f"<status>\n{title}. {meaning}\n</status>\n\n<frame>\n" + "\n\n".join(state_parts(record))
            + f"\n</frame>\n\n<user_words>\n{words}\n</user_words>")
