"""split the emails and their PDFs into short passages that can each be found on their own

one vector for a whole 42 page PDF averages every topic in it into one point, so nothing in it
can be found; a passage of a few hundred words is about one thing. each passage starts with a
header from the classification (bank, date, title, page), so it still makes sense on its own
"""

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

# about 400 tokens: long enough to hold a whole argument, short enough to be about one thing
MAX_CHARS = 1600
# the end of each passage is repeated at the start of the next, so a sentence cut at the
# boundary is still whole in one of them
OVERLAP_CHARS = 200
# a line found in this many emails is a disclaimer, footer or "Read more" button, not research
BOILERPLATE_EMAILS = 5
# a bank repeats its own legal text in every issue of a series, even a series of two, which the
# rule above misses: a line in this many of one bank's documents is removed when it reads like
# legal text. the wording test matters: banks also repeat their own research (a daily digest
# quotes a report's key sentence), which must stay
SAME_BANK_DOCUMENTS = 2
LEGAL_WORDING = re.compile(
    r"\b(?:warrant|disclaim|liabilit|solicitation|past performance|regulated by|"
    r"authori[sz]ed by|creditworthiness|counterparty|conflicts? of interest|investment advice|"
    r"construed|not intended|marketing communication|for information(?:al)? purposes|"
    r"confidential|copyright|all rights reserved|redistribut|reproduc|disclosures?|"
    r"intended (?:only )?for (?:institutional|professional))",
    re.IGNORECASE,
)
# shorter repeated lines are often headings, dates, names or ratings ("Europe", "12 April 2026",
# "Stock rating Overweight"); disclaimers are long, so this keeps nearly all of the cleanup
BOILERPLATE_MIN_WORDS = 4


@dataclass
class Source:
    """one email, one PDF page, or the description of a picture in either, with what the
    classification found about its email"""

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
    # set when the text is a model's description of a picture (see rag/images.py), not the
    # email's own words: the picture's kind, such as "chart" or "cartoon"
    picture: str | None = None
    # an email's own image, relative to its folder: "inline/image001.png"
    image: str | None = None


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
    # defaults, so an index written before pictures were described still loads
    picture: str | None = None
    image: str | None = None

    @property
    def where(self) -> str:
        place = f"{self.pdf}, page {self.page}" if self.pdf else "email body"
        return f"picture in {place}" if self.picture else place

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
    """long lines repeated across many emails, normalised; each email counts a line once"""
    seen = Counter(line for body in bodies for line in {_normal(x) for x in body.splitlines()})
    return {
        line
        for line, count in seen.items()
        if count >= BOILERPLATE_EMAILS and len(line.split()) >= BOILERPLATE_MIN_WORDS
    }


def bank_boilerplate(documents: list[tuple[str | None, str]]) -> set[str]:
    """legal lines a bank repeats across its own documents, normalised; documents are (bank,
    text), and each document counts a line once"""
    seen: dict[str, Counter] = defaultdict(Counter)
    for bank, text in documents:
        if bank:
            seen[bank].update({_normal(x) for x in text.splitlines()})
    return {
        line
        for counts in seen.values()
        for line, n in counts.items()
        if line and n >= SAME_BANK_DOCUMENTS and LEGAL_WORDING.search(line)
    }


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
    """passages never cross a PDF page, so every answer can cite the page it came from; a
    picture's description stays one passage, since its lines only make sense together"""
    chunks = []
    for src in sources:
        for i, text in enumerate([src.text] if src.picture else split_text(src.text)):
            where = f"{src.email_id}|{src.pdf}|{src.page}|{i}"
            if src.picture:
                where += f"|picture|{src.image}"
            chunk_id = hashlib.sha256(where.encode()).hexdigest()[:12]
            fields = {k: v for k, v in asdict(src).items() if k != "text"}
            chunks.append(Chunk(id=chunk_id, text=text, **fields))
    return chunks
