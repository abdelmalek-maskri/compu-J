"""run the same emails through several models and compare them: speed, agreement, flags

run from the repo root:
  uv run python -m scripts.compare_models --models gemma gemini-flash-lite --emails 10
  uv run python -m scripts.compare_models --models gemma gpt-oss-20b --only 035299 035243
  uv run python -m scripts.compare_models --models gemma gemini-flash-lite --emails 10 --no-run

answers already cached are reused, so adding a model to a comparison only runs that model.
--no-run compares cached answers only and never calls a model.
writes output/comparisons/<models>_<emails>/: one json per model, review.csv and agreement.txt
"""

import argparse
import sys
from itertools import combinations
from pathlib import Path

from dotenv import load_dotenv

from classify import Outcome, RunStopped, classify_all, write_json
from pipeline.clean_emails import PreparedEmail, prepare_all
from pipeline.flags import (
    COMPARED_FIELDS,
    model_vs_model_flags,
    review_rows,
    same_answer,
    write_review,
)
from pipeline.llm_cache import Cache
from pipeline.llm_client import LLMError, Settings
from pipeline.paths import COMPARISONS, LLM_ANSWERS

NOT_CACHED = "no cached answer for this model (run without --no-run)"


def spread_sample(emails: list[PreparedEmail], n: int) -> list[PreparedEmail]:
    """n emails evenly spaced across the dataset: ids run in date and bank clusters, so the
    first n would all look alike. the same n always gives the same emails"""
    if n >= len(emails):
        return list(emails)
    if n == 1:
        return [emails[0]]
    return [emails[round(i * (len(emails) - 1) / (n - 1))] for i in range(n)]


def _cached_only(llm_input: str, settings: Settings):
    raise LLMError(NOT_CACHED)


def speed_table(results: dict[str, list[Outcome]]) -> list[str]:
    columns = ["emails", "new", "cached", "failed", "avg"]
    lines = [f"{'model':20}" + "".join(f"{c:>8}" for c in columns) + "  slowest"]
    for name, outcomes in results.items():
        failed = [o for o in outcomes if o.record.meta.error]
        fresh = [o for o in outcomes if not o.cached and not o.record.meta.error]
        avg = f"{sum(o.seconds for o in fresh) / len(fresh):.0f}s" if fresh else "-"
        slowest = max(fresh, key=lambda o: o.seconds, default=None)
        slow = f"{slowest.seconds:.0f}s ({slowest.record.source_file})" if slowest else "-"
        cells = [
            len(outcomes),
            len(fresh),
            len(outcomes) - len(fresh) - len(failed),
            len(failed),
            avg,
        ]
        lines.append(f"{name:20}" + "".join(f"{c:>8}" for c in cells) + f"  {slow}")
    return lines


def agreement_table(results: dict[str, list[Outcome]]) -> list[str]:
    """for each pair of models: on how many emails both answered and gave the same value"""
    short = {
        "primary_asset_tag": "primary",
        "folder_name": "title",
        "companies_mentioned": "companies",
        "industry_subindustry": "industries",
    }
    header = "".join(f"{short.get(f, f):>13}" for f in COMPARED_FIELDS)
    lines = [f"{'pair':40}{header}"]
    for (name_a, a), (name_b, b) in combinations(results.items(), 2):
        pairs = [
            (x.record, y.record)
            for x, y in zip(a, b, strict=True)
            if not x.record.meta.error and not y.record.meta.error
        ]
        cells = ""
        for field in COMPARED_FIELDS:
            same = sum(same_answer(x, y, field) for x, y in pairs)
            cells += f"{f'{same}/{len(pairs)}':>13}"
        lines.append(f"{f'{name_a} vs {name_b}':40}{cells}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--models", nargs="+", required=True, help="preset names or model strings")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--emails", type=int, help="this many emails, spread across the dataset")
    which.add_argument("--only", nargs="+", metavar="ID", help="exactly these folder ids")
    parser.add_argument("--no-run", action="store_true", help="compare cached answers only")
    parser.add_argument("--force", action="store_true", help="ignore cached answers")
    parser.add_argument("--data", type=Path, default=Path("Data"))
    args = parser.parse_args()

    load_dotenv()
    if not args.data.is_dir():
        print(f"no data folder at {args.data}")
        return 1
    all_settings = [Settings.from_name(m) for m in args.models]
    if not args.no_run:
        missing = {s.name: s.missing_key() for s in all_settings if s.missing_key()}
        if missing:
            for name, key in missing.items():
                print(f"{name} needs {key} in .env")
            return 2

    emails, _ = prepare_all(args.data)
    if args.only:
        unknown = set(args.only) - {e.id for e in emails}
        if unknown:
            print(f"unknown folder ids: {sorted(unknown)}")
            return 1
        emails, label = [e for e in emails if e.id in args.only], "selected"
    else:
        emails, label = spread_sample(emails, args.emails), f"{args.emails}-emails"
    out = COMPARISONS / f"{'_vs_'.join(s.name for s in all_settings)}_{label}"
    print(f"comparing {len(emails)} emails: {', '.join(e.id for e in emails)}\n")

    results, rows, notes = {}, [], []
    for settings in all_settings:
        print(f"--- {settings.name} ({settings.model})")
        try:
            outcomes = classify_all(
                emails,
                settings,
                Cache(LLM_ANSWERS / settings.name),
                args.force,
                classify_fn=_cached_only if args.no_run else None,
            )
        except RunStopped as e:
            # keep the emails it finished; the others count as failed for this comparison
            done = {o.record.source_file for o in e.outcomes}
            outcomes = e.outcomes + classify_all(
                [m for m in emails if m.id not in done],
                settings,
                Cache(LLM_ANSWERS / settings.name),
                classify_fn=_cached_only,
                log=lambda line: None,
            )
            outcomes.sort(key=lambda o: o.record.source_file)
            notes.append(f"{settings.name} stopped early: {e}")
        results[settings.name] = outcomes
        records = [o.record for o in outcomes]
        write_json(records, out / f"{settings.name}.json")
        rows += review_rows(records, settings.name)

    for (name_a, a), (name_b, b) in combinations(results.items(), 2):
        for x, y in zip(a, b, strict=True):
            if x.record.meta.error or y.record.meta.error:
                continue
            flags = model_vs_model_flags(x.record, y.record, name_a, name_b)
            rows += [
                {
                    "email": x.record.source_file,
                    "title": x.record.folder_name,
                    "model": f"{name_a} vs {name_b}",
                    **f.model_dump(),
                    "your_verdict": "",
                }
                for f in flags
            ]
    rows.sort(key=lambda r: (r["email"], r["model"], r["field"]))
    write_review(rows, out / "review.csv")

    report = [
        f"models: {', '.join(results)} | emails: {len(emails)} ({label})",
        *notes,
        "",
        *speed_table(results),
        "",
        *agreement_table(results),
        "",
        f"flags to review: {len(rows)} (in review.csv)",
    ]
    (out / "agreement.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n" + "\n".join(report) + f"\n\nwritten to {out}/")
    return 2 if notes else 0


if __name__ == "__main__":
    sys.exit(main())
