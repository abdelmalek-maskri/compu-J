"""split the emails and their PDFs into short passages that can each be found on their own

one vector for a whole 42 page PDF averages every topic in it into one point, so nothing in it
can be found; a passage of a few hundred words is about one thing. each passage starts with a
header from the classification (bank, date, title, page), so it still makes sense on its own
"""

import hashlib
from collections import Counter
from dataclasses import asdict, dataclass

# about 400 tokens: long enough to hold a whole argument, short enough to be about one thing
MAX_CHARS = 1600
# the end of each passage is repeated at the start of the next, so a sentence cut at the
# boundary is still whole in one of them
OVERLAP_CHARS = 200
# a line found in this many emails is a disclaimer, footer or "Read more" button, not research
BOILERPLATE_EMAILS = 5


@dataclass
class Source:
    """one email or one PDF page, with what the classification found about its email"""

    email_id: str
    text: str
    title: str
    bank: str | None
    date: str | None
    market_wrap: str
    asset_tags: list[str]
    companies: list[str]
    pdf: str | None = None
    page: int | None = None


@dataclass
class Chunk:
    id: str
    email_id: str
    text: str
    title: str
    bank: str | None
    date: str | None
    market_wrap: str
    asset_tags: list[str]
    companies: list[str]
    pdf: str | None
    page: int | None

    @property
    def where(self) -> str:
        return f"{self.pdf}, page {self.page}" if self.pdf else "email body"

    @property
    def header(self) -> str:
        tags = ", ".join(self.asset_tags) or "no tags"
        parts = [self.bank or "Unknown bank", self.date or "no date", self.title, tags, self.where]
        return " | ".join(parts)

    @property
    def embedded_text(self) -> str:
        """what is embedded and searched: the header gives a page from the middle of a PDF the
        context its text alone lacks, such as which bank wrote it"""
        return f"{self.header}\n{self.text}"

    def to_json(self) -> dict:
        return asdict(self)


def _normal(line: str) -> str:
    return " ".join(line.split()).casefold()


def boilerplate(bodies: list[str]) -> set[str]:
    """lines repeated across many emails, normalised; each email counts a line once"""
    seen = Counter(line for body in bodies for line in {_normal(x) for x in body.splitlines()})
    return {line for line, count in seen.items() if line and count >= BOILERPLATE_EMAILS}


def strip_lines(text: str, remove: set[str]) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line and line.casefold() not in remove)


def _pieces(text: str) -> list[str]:
    """lines, with any line longer than a passage cut at word boundaries"""
    pieces = []
    for line in text.splitlines():
        words, current = line.split(), ""
        for word in words:
            if current and len(current) + 1 + len(word) > MAX_CHARS:
                pieces.append(current)
                current = word
            else:
                current = f"{current} {word}" if current else word
        if current:
            pieces.append(current)
    return pieces


def split_text(text: str) -> list[str]:
    """whole lines packed into passages of at most MAX_CHARS, each starting with the last lines
    of the one before (up to OVERLAP_CHARS); a table row or bullet is never cut in half"""
    passages, current = [], []
    for piece in _pieces(text):
        if current and len("\n".join([*current, piece])) > MAX_CHARS:
            passages.append("\n".join(current))
            overlap = []
            for line in reversed(current):
                if len("\n".join([line, *overlap, piece])) > MAX_CHARS:
                    break
                if len("\n".join([line, *overlap])) > OVERLAP_CHARS:
                    break
                overlap.insert(0, line)
            current = overlap
        current.append(piece)
    if current:
        passages.append("\n".join(current))
    return passages


def make_chunks(sources: list[Source]) -> list[Chunk]:
    """passages never cross a PDF page, so every answer can cite the page it came from"""
    chunks = []
    for src in sources:
        for i, text in enumerate(split_text(src.text)):
            where = f"{src.email_id}|{src.pdf}|{src.page}|{i}"
            chunk_id = hashlib.sha256(where.encode()).hexdigest()[:12]
            fields = {k: v for k, v in asdict(src).items() if k != "text"}
            chunks.append(Chunk(id=chunk_id, text=text, **fields))
    return chunks
