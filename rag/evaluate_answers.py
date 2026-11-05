"""check the answers, not only the search: does each quote back the claim it is cited for?

uv run python -m rag.evaluate_answers            answer every question not answered yet (calls
                                                 the model) and add its points to the review file
uv run python -m rag.evaluate_answers --score    count the labels

the quote check (rag/answer.py) proves a quote is really in its passage, not that it supports the
claim: "Barclays expects oil to rise", citing a real Barclays sentence about gas, passes it. so a
person labels each point in evaluation/rag_answers.csv, as for the classifier's labels: in the
"supported" column, yes (the quote backs the claim), partly (it backs some of it) or no. the
score then says how often answers are supported, and how many unsupported points the quote check
caught and how many it let through. rows already in the file are kept with their labels; delete
a question's rows to answer it again
"""

import argparse
import csv
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

from pipeline.llm_client import RETRYABLE, LLMError, Settings, StopRun
from rag.answer import rag_settings
from rag.evaluate import GROUPS, QUESTIONS, Question, load_questions
from rag.qa import Index, NotReady, Reply, answer

ANSWERS = Path("evaluation/rag_answers.csv")
COLUMNS = [
    "question", "bank", "date", "wording", "mode", "model", "point", "claim", "source", "quote",
    "quote_found", "from_picture", "supported", "note",
]  # fmt: skip
LABELS = {"yes", "partly", "no"}
# the row written for a question the model said its sources do not answer: nothing to label
NO_POINTS = "(no points: the model said the passages do not answer this)"


def question_key(row: dict) -> tuple[str, str, str]:
    """a question is the same when its text and filters are"""
    return row["question"], row["bank"] or "", row["date"] or ""


def rows_for(q: Question, reply: Reply, mode: str, model: str) -> list[dict]:
    base = {
        "question": q.text,
        "bank": q.bank or "",
        "date": q.date or "",
        "wording": q.wording,
        "mode": mode,
        "model": model,
        "supported": "",
        "note": "",
    }
    if not reply.points:
        return [{**base, "point": "0", "claim": NO_POINTS, "source": "", "quote": "",
                 "quote_found": "", "from_picture": ""}]  # fmt: skip
    rows = []
    for n, p in enumerate(reply.points, 1):
        hit = reply.hits[p.source - 1] if 1 <= p.source <= len(reply.hits) else None
        where = (
            f"[{p.source}] {hit.chunk.email_id} | {hit.chunk.bank} | {hit.chunk.date} | "
            f"{hit.chunk.where}"
            if hit
            else f"[{p.source}] (no such source)"
        )
        rows.append({
            **base, "point": str(n), "claim": p.claim, "source": where, "quote": p.quote,
            "quote_found": "yes" if p.verified else "no",
            "from_picture": "yes" if p.from_picture else "no",
        })  # fmt: skip
    return rows


def read_answers(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path} must have the columns {COLUMNS}, found {reader.fieldnames}")
        return list(reader)


def write_answers(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def answer_all(
    questions: list[Question],
    rows: list[dict],
    ask: Callable[[Question], Reply],
    mode: str,
    model: str,
    log: Callable[[str], None] = print,
) -> tuple[list[dict], str | None]:
    """rows plus the points of every question without rows yet, and why it stopped early, if it
    did: a model refusing every call stops it, keeping what was answered"""
    done = {question_key(r) for r in rows}
    todo = [q for q in questions if (q.text, q.bank or "", q.date or "") not in done]
    rows = list(rows)
    for i, q in enumerate(todo, 1):
        try:
            reply = ask(q)
        except (StopRun, NotReady) as e:
            return rows, str(e)
        except (LLMError, *RETRYABLE) as e:
            log(f"[{i}/{len(todo)}] FAILED {q.text}: {e}")
            continue
        new = rows_for(q, reply, mode, model)
        rows += new
        points = 0 if new[0]["point"] == "0" else len(new)
        log(f"[{i}/{len(todo)}] {points} points: {q.text}")
    return rows, None


def check_labels(rows: list[dict]) -> list[str]:
    """the labels a person typed that are not yes, partly or no"""
    return [
        f"row {n}: {r['supported']!r} for {r['claim'][:60]!r}"
        for n, r in enumerate(rows, 2)
        if r["point"] != "0" and r["supported"].strip().lower() not in LABELS | {""}
    ]


def report(rows: list[dict]) -> str:
    """the share of labelled points supported, and how the quote check did against the labels"""
    points = [r for r in rows if r["point"] != "0"]
    labelled = [r for r in points if r["supported"].strip()]
    declined = len({question_key(r) for r in rows if r["point"] == "0"})
    lines = [
        f"{len(points)} points from {len({question_key(r) for r in rows})} answered questions "
        f"({declined} said the passages do not answer them); {len(labelled)} labelled"
    ]
    if not labelled:
        lines.append(f"label the 'supported' column in {ANSWERS} (yes, partly or no), then score")
        return "\n".join(lines)

    def share(part: list[dict]) -> str:
        counts = Counter(r["supported"].strip().lower() for r in part)
        n = len(part)
        return (
            f"supported {counts['yes'] / n:.0%}, partly {counts['partly'] / n:.0%}, "
            f"not {counts['no'] / n:.0%} ({n} points)"
        )

    lines.append(f"all: {share(labelled)}")
    for group in GROUPS:
        if part := [r for r in labelled if r["wording"] == group]:
            lines.append(f"  {group}: {share(part)}")
    if pictures := [r for r in labelled if r["from_picture"] == "yes"]:
        lines.append(f"  citing a picture: {share(pictures)}")

    # the automatic check measured against the person: what it caught, missed and wrongly flagged
    unsupported = [r for r in labelled if r["supported"].strip().lower() != "yes"]
    caught = sum(r["quote_found"] == "no" for r in unsupported)
    flagged_but_fine = sum(
        r["quote_found"] == "no" for r in labelled if r["supported"].strip().lower() == "yes"
    )
    lines.append(
        f"quote check: caught {caught} of {len(unsupported)} points not fully supported, "
        f"let {len(unsupported) - caught} through, and flagged {flagged_but_fine} that were "
        "supported"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--score", action="store_true", help="count the labels, no model calls")
    parser.add_argument("--mode", choices=["hybrid", "keyword", "vector"], default="hybrid")
    parser.add_argument("--model", help="answer model preset (default RAG_MODEL)")
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    parser.add_argument("--answers", type=Path, default=ANSWERS)
    args = parser.parse_args()
    load_dotenv()

    try:
        rows = read_answers(args.answers)
    except ValueError as e:
        print(e)
        return 1
    if args.score:
        if problems := check_labels(rows):
            print("labels must be yes, partly or no:\n" + "\n".join(problems))
            return 1
        print(report(rows))
        return 0

    try:
        questions = load_questions(args.questions)
        index = Index()
    except (ValueError, NotReady) as e:
        print(e)
        return 1
    settings: Settings = rag_settings(args.model)
    if missing := settings.missing_key():
        print(f"{settings.name} needs {missing} in .env")
        return 1

    def ask(q: Question) -> Reply:
        return answer(index, q.text, q.filters, args.mode, settings=settings)

    rows, stopped = answer_all(questions, rows, ask, args.mode, settings.name)
    write_answers(rows, args.answers)
    if stopped:
        print(f"stopped: {stopped}\nthe answers so far are saved; run again to carry on")
        return 1
    print(f"written to {args.answers}: label the 'supported' column, then run with --score")
    return 0


if __name__ == "__main__":
    sys.exit(main())
