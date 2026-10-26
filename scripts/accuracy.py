"""measure accuracy against emails labelled by hand

run from the repo root:
  uv run python -m scripts.accuracy --sample 20   picks 20 emails, writes evaluation/labels.csv
  uv run python -m scripts.accuracy --score       compares your labels with the results

label blind: open each email in the dashboard (the link column) or in Data/, and fill the
four answer columns with what the email says, without looking at the classification.
leave a cell empty to skip it. the score reads classified_emails.json and its details file,
so it never calls a model. for bank and date it also scores the model's and the rules' own
answers, which are both kept in the details file; market wrap and the main asset class come
from the model only
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from pipeline.allowed_tags import BANK_NAMES, PRIMARY_TAGS
from pipeline.paths import DELIVERABLE, DETAILS

LABELS = Path("evaluation/labels.csv")
REPORT = Path("evaluation/accuracy.md")
DASHBOARD = "http://localhost:5173/#"
FIELDS = ["bank", "date", "market_wrap", "primary_asset_tag"]
COLUMNS = ["email", "link", *FIELDS, "notes"]
NO_DATE = "none"
# the fields where the details file keeps both the model's and the rules' answers
BOTH_ANSWERS = ("bank", "date")


def pick_sample(records: list[dict], n: int) -> list[str]:
    """n emails, taken in turn from each main asset class so the small classes are tested
    too, spread out inside each class; the same data always gives the same emails"""
    groups: dict[str, list[str]] = {}
    for r in sorted(records, key=lambda r: r["source_file"]):
        groups.setdefault(r["primary_asset_tag"] or "", []).append(r["source_file"])
    # golden ratio steps visit a list evenly at any length: ids run in date and bank clusters,
    # so taking neighbours would test one day of one bank
    order = {
        g: [ids[i] for i in sorted(range(len(ids)), key=lambda i: (i * 0.618034) % 1)]
        for g, ids in groups.items()
    }
    picked = []
    while len(picked) < min(n, len(records)):
        for ids in order.values():
            if ids and len(picked) < n:
                picked.append(ids.pop(0))
    return sorted(picked)


def _normal(field: str, value: str | None) -> str:
    value = (value or "").strip()
    if field == "date" and value.lower() in (NO_DATE, ""):
        return NO_DATE
    return value.casefold()


def score(labels: list[dict], records: dict[str, dict], details: dict[str, dict]) -> dict:
    """per field, how many labelled emails each answer got right, and the ones it got wrong"""
    answers = {
        "submitted": lambda r, d, f: r[f],
        "model alone": lambda r, d, f: d.get(f"{f}_llm"),
        "rules alone": lambda r, d, f: d.get(f"{f}_python"),
    }
    result = {}
    for field in FIELDS:
        rows = [row for row in labels if (row.get(field) or "").strip()]
        result[field] = {}
        for name, answer in answers.items():
            if name != "submitted" and field not in BOTH_ANSWERS:
                continue
            wrong = []
            for row in rows:
                record, extra = records[row["email"]], details.get(row["email"], {})
                given = answer(record, extra, field)
                if _normal(field, given) != _normal(field, row[field]):
                    wrong.append((row["email"], row[field].strip(), given))
            result[field][name] = (len(rows) - len(wrong), len(rows), wrong)
    return result


def report(result: dict) -> list[str]:
    lines = ["| Field | Submitted | Model alone | Rules alone |", "| --- | --- | --- | --- |"]
    for field, by_answer in result.items():
        cells = []
        for name in ("submitted", "model alone", "rules alone"):
            if name not in by_answer:
                cells.append("model only")
                continue
            right, total, _ = by_answer[name]
            cells.append(f"{right}/{total}" if total else "no labels")
        lines.append(f"| {field} | " + " | ".join(cells) + " |")
    lines.append("")
    for field, by_answer in result.items():
        for email, label, given in by_answer["submitted"][2]:
            lines.append(f"* {email} {field}: labelled {label!r}, submitted {given!r}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--sample", type=int, metavar="N", help="pick N emails to label")
    action.add_argument("--score", action="store_true", help="score the labels")
    args = parser.parse_args()

    if not DELIVERABLE.exists():
        print(f"{DELIVERABLE} not found: run classify.py first", file=sys.stderr)
        return 2
    records = {r["source_file"]: r for r in json.loads(DELIVERABLE.read_text(encoding="utf-8"))}

    if args.sample:
        if LABELS.exists():
            print(f"{LABELS} exists; delete it to pick a new sample", file=sys.stderr)
            return 2
        LABELS.parent.mkdir(parents=True, exist_ok=True)
        with LABELS.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            for email in pick_sample(list(records.values()), args.sample):
                writer.writerow({"email": email, "link": DASHBOARD + email})
        print(f"wrote {LABELS}. allowed answers:")
        print(f"  bank: {', '.join(BANK_NAMES)}")
        print(f"  date: YYYY-MM-DD, or {NO_DATE} if the email states no date")
        print("  market_wrap: YES or NO")
        print(f"  primary_asset_tag: {', '.join(PRIMARY_TAGS)}")
        return 0

    if not LABELS.exists():
        print(f"{LABELS} not found: run with --sample first", file=sys.stderr)
        return 2
    with LABELS.open(encoding="utf-8") as f:
        labels = [row for row in csv.DictReader(f) if row["email"] in records]
    details = json.loads(DETAILS.read_text(encoding="utf-8")) if DETAILS.exists() else {}
    lines = report(score(labels, records, details))
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten to {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
