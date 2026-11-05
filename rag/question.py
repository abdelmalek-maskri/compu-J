"""read from a question what search alone cannot see: the kind of picture it asks for, and the
banks it compares

"cartoons about Iran" is a question about a format, but search sees topics: the emails are full
of the Iran war, so hundreds of passages match "Iran" better than the one cartoon does (it ranked
52nd by meaning). a format is metadata, like a bank or a date, so it becomes a filter instead of
a search word. this is a fixed list of words, not a model call: what it does can always be said
in one sentence, and undone
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from pipeline.clean_emails import BANKS
from rag.search import Filters, Hit, tokens

# the words that ask for a kind of picture; "picture" and "image" ask for any. "table" is left
# out: "on the table" is common in research and asks for no picture
PICTURE_WORDS = {
    "cartoon": "cartoon", "cartoons": "cartoon",
    "chart": "chart", "charts": "chart", "graph": "chart", "graphs": "chart",
    "infographic": "infographic", "infographics": "infographic",
    "map": "map", "maps": "map",
    "photo": "photo", "photos": "photo", "photograph": "photo", "photographs": "photo",
    "picture": "any", "pictures": "any", "image": "any", "images": "any",
}  # fmt: skip


def picture_asked(question: str) -> str | None:
    """the kind of picture the question names; "any" when it names several or just "picture" """
    kinds = {PICTURE_WORDS[w] for w in tokens(question) if w in PICTURE_WORDS}
    if not kinds:
        return None
    return kinds.pop() if len(kinds) == 1 else "any"


def read_question(question: str, filters: Filters) -> tuple[Filters, str | None]:
    """the filters with the picture kind the question names, and that kind (None when the
    question names none, or the person already chose a picture filter)"""
    if filters.picture is not None or (kind := picture_asked(question)) is None:
        return filters, None
    return replace(filters, picture=kind), kind


# a question naming two or more banks, or all of them, is a comparison: one search would give
# the slots to whichever bank's words dominate (six Goldman disclaimers and no Goldman view, in
# one test), so each bank is searched on its own, with its own filter
NAMED_BANKS = {name: re.compile(rf"\b(?:{p})\b", re.IGNORECASE) for name, p in BANKS.items()}
ALL_BANKS = re.compile(
    r"\b(?:(?:all|each|every|different|various)(?: of)?(?: the)? banks|the banks|each bank|"
    r"every bank)\b",
    re.IGNORECASE,
)
# in a comparison, the usual number of passages is shared between the banks (8 for two banks
# gives 4 each), but every bank gets at least this many, however many are compared
PER_BANK_MIN = 2


def banks_asked(question: str, known: list[str]) -> list[str]:
    """the banks a question compares, in the order it names them, or every known bank for "all
    the banks"; empty when it names fewer than two"""
    if ALL_BANKS.search(question):
        return sorted(known)
    found = sorted(
        (m.start(), name)
        for name, pattern in NAMED_BANKS.items()
        if name in known and (m := pattern.search(question))
    )
    return [name for _, name in found] if len(found) >= 2 else []


@dataclass
class Reading:
    """what the question changed about the search, so it can be said and undone"""

    picture: str | None = None
    banks: list[str] = field(default_factory=list)
    # compared banks the search found nothing for
    banks_without: list[str] = field(default_factory=list)


def search_as_read(
    question: str,
    filters: Filters,
    k: int,
    known_banks: list[str],
    run: Callable[[Filters, int], list[Hit]],
) -> tuple[list[Hit], Reading]:
    """the searches the question calls for; run(filters, k) is one search. a kind of picture
    narrows them (dropped when it finds nothing), and a comparison runs one per bank"""
    narrowed, picture = read_question(question, filters)
    if picture and not run(narrowed, k):
        narrowed, picture = filters, None
    banks = banks_asked(question, known_banks) if filters.bank is None else []
    if not banks:
        return run(narrowed, k), Reading(picture)
    # the passages asked for, shared between the banks; never fewer than PER_BANK_MIN each
    each = max(PER_BANK_MIN, -(-k // len(banks)))
    hits, without = [], []
    for bank in banks:
        found = run(replace(narrowed, bank=bank), each)
        if found:
            hits += found
        else:
            without.append(bank)
    return hits, Reading(picture, banks, without)
