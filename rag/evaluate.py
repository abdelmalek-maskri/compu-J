"""measure retrieval on questions whose source emails are known, for each kind of search

uv run python -m rag.evaluate --modes keyword           no model calls
uv run python -m rag.evaluate                           keyword, vector and hybrid (embeds the
                                                        questions, once: their vectors are saved)

if the right passage is not retrieved, no answer model can fix it, so retrieval is measured on
its own, over the top k passages. a question is scored by email, or, when its "pages" column is
filled, by page: "035432:3" is page 3 of one of that email's PDFs, "035308:email" the email's
own text or pictures, so a 42 page PDF is not found just because any page of it came back:
found@k:  the share of questions with at least one expected source in the top k
recall@k: the share of all expected sources that appear in the top k
MRR:      the average of 1 / the rank of the first expected source (1 if first, 1/2 if second,
          0 if absent): it shows when the right source is found but ranked below a wrong one

the "wording" column groups the questions: "same" uses its source's words, "different" other
words (where keyword search fails), "hard_negative" asks for one day of a daily series whose
other days look almost identical, asked again as "hard_negative_filtered" with the date filter
the classification makes possible, "picture" is answered by a chart, table or cartoon, and
"comparison" asks what several banks think, so each bank's own notes must be found

the answers themselves are checked by rag/evaluate_answers.py
"""

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from pipeline.llm_client import StopRun
from rag.chunks import Chunk
from rag.embed import DEFAULT_EMBEDDER, EMBEDDERS, VectorStore
from rag.ingest import DOCUMENT, QUERY, load_chunks, ready
from rag.question import search_as_read
from rag.search import Filters, Hit, Keyword, search

QUESTIONS = Path("evaluation/rag_questions.csv")
COLUMNS = ["question", "expected", "bank", "date", "wording", "pages"]
GROUPS = ["same", "different", "hard_negative", "hard_negative_filtered", "picture", "comparison"]
PAGE = re.compile(r"\d{6}:(\d+|email)")


@dataclass
class Question:
    text: str
    expected: set[str]
    bank: str | None
    # one day, YYYY-MM-DD: the question is searched among that day's emails only
    date: str | None
    wording: str
    # when set, the exact pages expected, such as "035432:3"; else any part of the expected emails
    pages: set[str] = field(default_factory=set)

    @property
    def filters(self) -> Filters:
        return Filters(bank=self.bank, since=self.date, until=self.date)

    @property
    def targets(self) -> set[str]:
        return self.pages or self.expected


def location(chunk: Chunk) -> str:
    """the email and page a passage comes from, as written in the "pages" column"""
    return f"{chunk.email_id}:{chunk.page}" if chunk.page else f"{chunk.email_id}:email"


def ranked(question: Question, hits: list[Hit]) -> list[str]:
    """what the hits are scored as: their pages when the question names pages, else emails"""
    each = location if question.pages else (lambda c: c.email_id)
    return list(dict.fromkeys(each(h.chunk) for h in hits))


def load_questions(path: Path) -> list[Question]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path} must have the columns {COLUMNS}, found {reader.fieldnames}")
        rows = list(reader)
    if unknown := {r["wording"] for r in rows} - set(GROUPS):
        raise ValueError(f"{path}: unknown wording {sorted(unknown)}, expected one of {GROUPS}")
    questions = [
        Question(
            r["question"], set(r["expected"].split()), r["bank"] or None, r["date"] or None,
            r["wording"], set(r["pages"].split()),
        )
        for r in rows
    ]  # fmt: skip
    for q in questions:
        if strays := {p for p in q.pages if p.split(":")[0] not in q.expected}:
            raise ValueError(
                f"{path}: {q.text!r} names pages of emails it does not expect: {strays}"
            )
        if bad := {p for p in q.pages if not PAGE.fullmatch(p)}:
            raise ValueError(
                f"{path}: {q.text!r} has pages not written as 035432:3 or 035308:email: {bad}"
            )
    return questions


@dataclass
class Result:
    question: Question
    found: bool
    recall: float
    reciprocal_rank: float


def score(question: Question, found: list[str]) -> Result:
    """found: the sources of the passages found (see ranked), best first, each once"""
    targets = question.targets
    hits = targets & set(found)
    first = next((n for n, e in enumerate(found, 1) if e in targets), None)
    return Result(question, bool(hits), len(hits) / len(targets), 1 / first if first else 0)


def summary(results: list[Result]) -> str:
    if not results:
        return "no questions"
    n = len(results)
    found = sum(r.found for r in results) / n
    recall = sum(r.recall for r in results) / n
    mrr = sum(r.reciprocal_rank for r in results) / n
    return f"found {found:.0%}, recall {recall:.0%}, MRR {mrr:.2f} ({n} questions)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--modes", nargs="+", default=["keyword", "vector", "hybrid"])
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    parser.add_argument("--embedder", choices=EMBEDDERS, default=DEFAULT_EMBEDDER)
    args = parser.parse_args()
    load_dotenv()

    try:
        chunks = load_chunks()
        questions = load_questions(args.questions)
    except (FileNotFoundError, ValueError) as e:
        print(e)
        return 1
    known = {c.email_id for c in chunks}
    if unknown := {i for q in questions for i in q.expected} - known:
        print(f"expected emails not in the index: {sorted(unknown)}")
        return 1

    vectors, query_vectors = None, {}
    if set(args.modes) - {"keyword"}:
        embedder = EMBEDDERS[args.embedder]
        if problem := ready(embedder):
            print(problem)
            return 1
        store = VectorStore(embedder, log=lambda _: None)
        texts = [c.embedded_text for c in chunks]
        if store.missing(texts, DOCUMENT):
            print("some passages have no vector yet: run `uv run python -m rag.ingest`")
            return 1
        try:
            vectors = store.embed(texts, DOCUMENT)
            asked = [q.text for q in questions]
            query_vectors = dict(zip(asked, store.embed(asked, QUERY), strict=True))
        except StopRun as e:
            print(f"stopped: {e}")
            return 1

    keyword = Keyword(chunks)
    banks = sorted({c.bank for c in chunks if c.bank})
    for mode in args.modes:
        print(f"\n{mode} search, top {args.k}")
        results = []
        for q in questions:
            # read as the Ask tab reads it: a kind of picture, or one search per compared bank
            def run(filters: Filters, n: int, q=q, mode=mode) -> list[Hit]:
                return search(
                    q.text, chunks, keyword, filters, n, mode,
                    query_vectors.get(q.text), vectors,
                )  # fmt: skip

            hits, _ = search_as_read(q.text, q.filters, args.k, banks, run)
            result = score(q, ranked(q, hits))
            results.append(result)
            mark = "ok  " if result.found else "MISS"
            first = f"#{round(1 / result.reciprocal_rank)}" if result.reciprocal_rank else "-"
            print(f"  {mark} recall {result.recall:4.0%}  first {first:3}  [{q.wording}] {q.text}")
        print(f"  all: {summary(results)}")
        for group in GROUPS:
            if part := [r for r in results if r.question.wording == group]:
                print(f"  {group}: {summary(part)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
