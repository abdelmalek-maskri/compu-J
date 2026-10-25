"""prepare every email, print coverage, and save what the LLM will read to output/cleaned_emails/

run from the repo root: uv run python -m scripts.preview_cleaned_emails
"""

import argparse
import statistics
import sys
from collections import Counter
from pathlib import Path

from pipeline.clean_emails import prepare_all
from pipeline.paths import CLEANED_EMAILS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("Data"))
    parser.add_argument("--out", type=Path, default=CLEANED_EMAILS)
    args = parser.parse_args()

    if not args.data.is_dir():
        print(f"no data folder at {args.data}")
        return 1

    emails, failures = prepare_all(args.data)
    args.out.mkdir(parents=True, exist_ok=True)
    for email in emails:
        (args.out / f"{email.id}.txt").write_text(email.llm_input, encoding="utf-8")

    sizes = sorted((len(e.llm_input), e.id) for e in emails)
    print(f"prepared {len(emails)}, failures {len(failures)}")
    for folder, reason in failures.items():
        print(f"  {folder}: {reason}")
    print(f"bank source:  {dict(Counter(e.bank_source for e in emails))}")
    print(f"banks:        {dict(Counter(e.bank for e in emails).most_common())}")
    print(f"date source:  {dict(Counter(e.date_source for e in emails))}")
    print(f"no date:      {[e.id for e in emails if e.date is None]}")
    print(f"date hints:   { {e.id: e.date_hint.isoformat() for e in emails if e.date_hint} }")
    print(f"with PDFs:    {sum(bool(e.attachments.pdfs) for e in emails)}")
    print(f"not utf-8:    {[e.id for e in emails if e.encoding != 'utf-8']}")
    duplicates = {e.id: e.duplicate_of for e in emails if e.duplicate_of}
    warnings = {e.id: e.warnings for e in emails if e.warnings}
    print(f"duplicates:   {duplicates}")
    print(f"warnings:     {warnings}")
    print(
        f"input chars:  median {statistics.median(s for s, _ in sizes):.0f}, "
        f"largest {sizes[-1][1]} at {sizes[-1][0]}"
    )
    print(f"texts written to {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
