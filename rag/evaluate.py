"""measure retrieval on questions whose source emails are known, for each kind of search

uv run python -m rag.evaluate --modes keyword           no model calls
uv run python -m rag.evaluate                           keyword, vector and hybrid (embeds the
                                                        questions, once: their vectors are saved)

if the right passage is not retrieved, no answer model can fix it, so retrieval is measured on
its own, over the emails of the top k passages:
found@k:  the share of questions with at least one expected email in the top k
recall@k: the share of all expected emails that appear in the top k
MRR:      the average of 1 / the rank of the first expected email (1 if first, 1/2 if second,
          0 if absent): it shows when the right email is found but ranked below a wrong one

the "wording" column groups the questions: "same" uses its source's words, "different" other
words (where keyword search fails), and "hard_negative" asks for one day of a daily series whose
other days look almost identical; each is asked again as "hard_negative_filtered" with the date
filter the classification makes possible
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from pipeline.llm_client import StopRun
from rag.embed import DEFAULT_EMBEDDER, EMBEDDERS, VectorStore
from rag.ingest import DOCUMENT, QUERY, load_chunks, ready
from rag.search import Filters, Keyword, search

QUESTIONS = Path("evaluation/rag_questions.csv")
COLUMNS = ["question", "expected", "bank", "date", "wording"]
GROUPS = ["same", "different", "hard_negative", "hard_negative_filtered"]


@dataclass
class Question:
    text: str
    expected: set[str]
    bank: str | None
    # one day, YYYY-MM-DD: the question is searched among that day's emails only
    date: str | None
    wording: str

    @property
    def filters(self) -> Filters:
        return Filters(bank=self.bank, since=self.date, until=self.date)


def load_questions(path: Path) -> list[Question]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path} must have the columns {COLUMNS}, found {reader.fieldnames}")
        rows = list(reader)
    if unknown := {r["wording"] for r in rows} - set(GROUPS):
        raise ValueError(f"{path}: unknown wording {sorted(unknown)}, expected one of {GROUPS}")
    return [
        Question(
            r["question"], set(r["expected"].split()), r["bank"] or None, r["date"] or None,
            r["wording"],
        )
        for r in rows
    ]  # fmt: skip


@dataclass
class Result:
    question: Question
    found: bool
    recall: float
    reciprocal_rank: float


def score(question: Question, ranked: list[str]) -> Result:
    """ranked: the emails of the passages found, best first, each once"""
    hits = question.expected & set(ranked)
    first = next((n for n, e in enumerate(ranked, 1) if e in question.expected), None)
    return Result(
        question, bool(hits), len(hits) / len(question.expected), 1 / first if first else 0
    )


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
    for mode in args.modes:
        print(f"\n{mode} search, top {args.k}")
        results = []
        for q in questions:
            hits = search(
                q.text, chunks, keyword, q.filters, args.k, mode,
                query_vectors.get(q.text), vectors,
            )  # fmt: skip
            result = score(q, list(dict.fromkeys(h.chunk.email_id for h in hits)))
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
