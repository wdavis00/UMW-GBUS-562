"""Output guardrail: a quantity must not be shown with more certainty than its evidence supports.

It runs after the Framer's result passes its structural checks and before the Reviewer. `stated`
and `draft_statement` present established information. Each quantity in them must be one the user
supplied, or a derived quantity whose source values the user supplied. Otherwise the framing is
held, the user is told what was held and why, and the user decides what to do. The guardrail does
not judge whether a quantity is true.

Known limits. It compares values, not meaning or units, so a supplied "9 hours" also covers
"9 accounts". It does not check the arithmetic of a derived quantity. It misses fractions such as
"half" and spelled-out numbers that have no scale word and no listed unit after them. It treats
idioms such as "24/7" as quantities. It checks only the two established fields.
"""

import re
from decimal import Decimal

NUMBER_WORDS = {word: value for value, word in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
NUMBER_WORDS.update({word: 10 * tens for tens, word in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split(), start=2)})
SCALE_WORDS = {"dozen": 12, "hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
SHORT_SCALES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
UNIT_WORDS = {"dollar", "percent", "hour", "day", "week", "month", "year", "item", "return"}

TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+|[A-Za-z]+|[^\sA-Za-z\d]")
LIST_NUMBER = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
SPEAKER = re.compile(r"(?:^|(?<=\s))(User|Tool):\s")

NOTICE = (
    "I held {part} because it treated {amounts} as established. What you have told me "
    "does not establish {that} yet. {It} may still be useful if shown honestly as provisional. You can "
    "give evidence for {it}, mark {it} as an estimate, an assumption, hypothetical, a placeholder, or "
    "pending validation, or leave {this} unknown. It is your decision."
)
QUESTION = (
    "Do you have evidence for {amounts} that you would like to share, or would you rather keep {it} as "
    "provisional or leave {this} unknown?"
)
NOTE = "It was presented as established, but nothing you have told me establishes it yet."


def find_amounts(text: str, every_number_word: bool = False) -> dict[str, str]:
    """Return {normalized value: the amount as written}.

    With every_number_word, spelled-out numbers count even without a unit. That is used for what
    the user said and for declared values, where missing one would hold the framing needlessly.
    """
    text = LIST_NUMBER.sub("", text)
    tokens = list(TOKEN.finditer(text))
    words = [token.group().lower() for token in tokens]
    amounts: dict[str, str] = {}

    def word_at(index: int) -> str:
        return words[index] if index < len(words) else ""

    def base(word: str) -> str:
        return word[:-1] if word.endswith("s") else word

    def keep(value: str, first: int, last: int) -> None:
        """Record an amount, with any currency sign, percent sign, or unit word beside it."""
        start, end = tokens[first].start(), tokens[last].end()
        if first and words[first - 1] in "$€£":
            start = tokens[first - 1].start()
        following = last + 2 if word_at(last + 1) == "-" else last + 1
        if word_at(last + 1) == "%":
            end = tokens[last + 1].end()
        elif base(word_at(following)) in UNIT_WORDS:
            end = tokens[following].end()
        amounts.setdefault(value, text[start:end].rstrip(","))

    i = 0
    while i < len(tokens):
        word, last = words[i], i
        if word[0].isdigit() or word[0] == "." and len(word) > 1:
            touching = i > 0 and tokens[i - 1].end() == tokens[i].start() and words[i - 1].isalpha()
            if not touching:  # "Q3" is a label, not an amount
                value = Decimal(word.replace(",", ""))
                nearby = word_at(i + 1)
                if nearby in SHORT_SCALES and tokens[i + 1].start() == tokens[i].end():
                    value, last = value * SHORT_SCALES[nearby], i + 1
                elif nearby in SCALE_WORDS:
                    value, last = value * SCALE_WORDS[nearby], i + 1
                keep(normalize(value), i, last)
        elif word in NUMBER_WORDS or word in SCALE_WORDS:
            run = [word]
            while True:  # extend over "two hundred and twenty-five"
                step = 2 if word_at(last + 1) in ("-", "and") else 1
                following = word_at(last + step)
                if following not in NUMBER_WORDS and following not in SCALE_WORDS:
                    break
                run.append(following)
                last += step
            after = word_at(last + 2) if word_at(last + 1) == "-" else word_at(last + 1)
            if every_number_word or base(after) in UNIT_WORDS or any(w in SCALE_WORDS for w in run):
                keep(spelled_value(run), i, last)
        elif word.endswith("s") and base(word) in SCALE_WORDS:
            keep(word, i, i)  # "dozens", "hundreds"
        i = last + 1
    return amounts


def normalize(value: Decimal) -> str:
    """Return one spelling for equal numbers, so 4 and 4.0 match."""
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text.lstrip("0") or "0"


def spelled_value(run: list[str]) -> str:
    total = group = 0
    for word in run:
        if word in NUMBER_WORDS:
            group += NUMBER_WORDS[word]
        elif SCALE_WORDS[word] < 1_000:
            group = max(group, 1) * SCALE_WORDS[word]
        else:
            total, group = total + max(group, 1) * SCALE_WORDS[word], 0
    return normalize(Decimal(total + group))


def user_words(conversation: str) -> str:
    """Return only what the user said, leaving out lines labeled as the tool's."""
    pieces = SPEAKER.split(conversation)
    said = [pieces[0]] + [text for speaker, text in zip(pieces[1::2], pieces[2::2]) if speaker == "User"]
    return "\n".join(said)


def declared_amounts(text: str) -> set[str]:
    return set(find_amounts(text) or find_amounts(text, every_number_word=True))


def apply_guardrail(frame: dict, user_text: str) -> tuple[dict, list[dict]]:
    """Return the frame, held if it must be, and a list of what was held (empty if nothing was)."""
    supplied = set(find_amounts(user_text, every_number_word=True))
    derived, declared, bad_derived = set(), set(), set()
    for entry in frame["quantities"]:
        values = declared_amounts(entry["value"])
        declared |= values
        if entry["basis"] == "derived":
            sources = [declared_amounts(source) for source in entry["from"]]
            valid = bool(sources) and all(source and source <= supplied for source in sources)
            (derived if valid else bad_derived).update(values)
    allowed = supplied | derived

    held: dict[str, str] = {}  # normalized value: as written
    stated, set_aside = [], []
    for item in frame["stated"]:
        unsupported = {v: text for v, text in find_amounts(item).items() if v not in allowed}
        (set_aside if unsupported else stated).append(item)
        for value, text in unsupported.items():
            held.setdefault(value, text)
    in_draft = {v: text for v, text in find_amounts(frame["draft_statement"]).items() if v not in allowed}
    for value, text in in_draft.items():
        held.setdefault(value, text)
    if not held:
        return frame, []

    quantities = []
    for entry in frame["quantities"]:
        values = declared_amounts(entry["value"])
        if entry["basis"] == "derived" and values & set(held) and not values & derived:
            entry = {**entry, "basis": "pending_validation", "from": [],
                     "note": f"It was listed as derived, but not from amounts you gave me. {entry['note']}".strip()}
        quantities.append(entry)
    quantities += [{"value": text, "basis": "pending_validation", "from": [], "note": NOTE}
                   for value, text in held.items() if value not in declared]

    names = list(held.values())
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    words = ({"that": "that amount", "It": "It", "it": "it", "this": "the amount"} if len(names) == 1 else
             {"that": "those amounts", "It": "They", "it": "them", "this": "the amounts"})
    part = "the draft problem statement" if in_draft else "this framing"
    notice = NOTICE.format(part=part, amounts=listed, **words)
    held_frame = {
        **frame,
        "reflection": f"{notice}\n\n{frame['reflection']}",
        "stated": stated,
        "assumptions": frame["assumptions"] + [f'Held, not established yet: "{item}"' for item in set_aside],
        "quantities": quantities,
        "status": "not_ready",
        "draft_statement": "",
        "next_question": QUESTION.format(amounts=listed, **words),
    }
    reasons = [{"value": value, "reason": "unsupported_derivation" if value in bad_derived else
                "provisional_as_established" if value in declared else "undeclared_as_established"}
               for value in held]
    return held_frame, reasons
