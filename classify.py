"""classify every email with the LLM and write classified_emails.json

uv run python classify.py                 all emails
uv run python classify.py --limit 10      the first 10, written to .cache/classified_subset.json
uv run python classify.py --only 035299   one or more emails by folder id
uv run python classify.py --force         ignore cached answers
"""

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from pipeline.build_record import build_record, error_record
from pipeline.clean_emails import PreparedEmail, prepare_all
from pipeline.flags import review_rows, write_review
from pipeline.llm_cache import Cache, cache_key
from pipeline.llm_client import LLMError, Settings, classify_email
from pipeline.prompt import PROMPT_VERSION
from pipeline.schema import ClassifiedEmail

FULL_OUTPUT = Path("classified_emails.json")
# a trial run must never replace the full deliverable by accident
SUBSET_OUTPUT = Path(".cache/classified_subset.json")


@dataclass
class Outcome:
    record: ClassifiedEmail
    cached: bool
    seconds: float
    prompt_tokens: int


def classify_all(
    emails: list[PreparedEmail],
    settings: Settings,
    cache: Cache,
    force: bool = False,
    classify_fn: Callable = classify_email,
    log: Callable[[str], None] = print,
) -> list[Outcome]:
    outcomes = []
    for i, email in enumerate(emails, 1):
        key = cache_key(email.llm_input, settings)
        result = None if force else cache.get(email.id, key)
        cached = result is not None
        if result is None:
            try:
                result = classify_fn(email.llm_input, settings)
            except LLMError as e:
                record = error_record(email, str(e), settings.model, PROMPT_VERSION)
                outcomes.append(Outcome(record, cached=False, seconds=0, prompt_tokens=0))
                log(f"[{i}/{len(emails)}] {email.id} FAILED: {e}")
                continue
            # only successful answers are cached, so failures are retried on the next run
            cache.put(email.id, key, result)

        record = build_record(email, result.output, settings.model, PROMPT_VERSION)
        record.meta.warnings = [*email.warnings, *result.warnings]
        outcomes.append(Outcome(record, cached, result.seconds, result.prompt_tokens))
        how = "cached" if cached else f"{result.seconds:.0f}s"
        log(
            f"[{i}/{len(emails)}] {email.id} {how:>6} | {record.primary_asset_tag} "
            f"| wrap {record.market_wrap} | {record.folder_name}"
        )
    return outcomes


def write_json(records: list[ClassifiedEmail], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [r.model_dump(mode="json") for r in sorted(records, key=lambda r: r.source_file)]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def summary(outcomes: list[Outcome], settings: Settings) -> str:
    records = [o.record for o in outcomes]
    failed = [r.source_file for r in records if r.meta.error]
    fresh = [o for o in outcomes if not o.cached and not o.record.meta.error]
    biggest = max(outcomes, key=lambda o: o.prompt_tokens, default=None)
    unverified = [r.source_file for r in records if r.meta.title_verified is False]
    flags = Counter(f"{f.kind} {f.field}" for r in records for f in r.meta.flags)
    warnings = {r.source_file: r.meta.warnings for r in records if r.meta.warnings}
    lines = [
        f"{len(records) - len(failed)} classified, {len(failed)} failed {failed or ''}",
        f"model {settings.model}, prompt {PROMPT_VERSION}, "
        f"{len(outcomes) - len(fresh) - len(failed)} answers from cache",
        f"market wraps: {sum(r.market_wrap == 'YES' for r in records)}",
        f"titles not found in the email: {unverified}",
        f"flags to review: {sum(flags.values())} {dict(flags.most_common())}",
        f"rule corrections: {sum(len(r.meta.corrections) for r in records)}",
        f"warnings: {warnings}",
    ]
    if fresh:
        total = sum(o.seconds for o in fresh)
        slowest = max(fresh, key=lambda o: o.seconds)
        lines.append(
            f"time: {total / 60:.1f} min for {len(fresh)} new answers, "
            f"average {total / len(fresh):.0f}s, slowest {slowest.record.source_file} "
            f"at {slowest.seconds:.0f}s"
        )
    if biggest and biggest.prompt_tokens:
        lines.append(
            f"largest input: {biggest.record.source_file} at {biggest.prompt_tokens} "
            f"of {settings.num_ctx} tokens"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--data", type=Path, default=Path("Data"))
    parser.add_argument(
        "--out", type=Path, help=f"default {FULL_OUTPUT}, or {SUBSET_OUTPUT} for a subset"
    )
    parser.add_argument("--limit", type=int, help="only the first N emails")
    parser.add_argument("--only", nargs="+", metavar="ID", help="only these folder ids")
    parser.add_argument("--force", action="store_true", help="ignore cached answers")
    args = parser.parse_args()

    load_dotenv()
    if not args.data.is_dir():
        print(f"no data folder at {args.data}")
        return 1

    emails, failures = prepare_all(args.data)
    for folder, reason in failures.items():
        print(f"could not prepare {folder}: {reason}")
    if args.only:
        missing = set(args.only) - {e.id for e in emails}
        if missing:
            print(f"unknown folder ids: {sorted(missing)}")
            return 1
        emails = [e for e in emails if e.id in args.only]
    if args.limit:
        emails = emails[: args.limit]
    subset = bool(args.only or args.limit)
    out = args.out or (SUBSET_OUTPUT if subset else FULL_OUTPUT)

    settings = Settings.from_env()
    print(f"classifying {len(emails)} emails with {settings.model}\n")
    outcomes = classify_all(emails, settings, Cache())
    records = [o.record for o in outcomes]
    write_json(records, out)
    review = out.with_suffix(".review.csv")
    write_review(review_rows(records), review)
    print(f"\n{summary(outcomes, settings)}\nwritten to {out}, flags to {review}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
