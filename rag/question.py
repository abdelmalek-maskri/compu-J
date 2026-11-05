"""read from a question what search alone cannot see: the kind of picture it asks for

"cartoons about Iran" is a question about a format, but search sees topics: the emails are full
of the Iran war, so hundreds of passages match "Iran" better than the one cartoon does (it ranked
52nd by meaning). a format is metadata, like a bank or a date, so it becomes a filter instead of
a search word. this is a fixed list of words, not a model call: what it does can always be said
in one sentence, and undone
"""

from dataclasses import replace

from rag.search import Filters, tokens

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
