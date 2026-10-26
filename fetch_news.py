"""fetch financial headlines for the dashboard's ticker and save them to output/headlines.json

uv run python fetch_news.py              once
uv run python fetch_news.py --every 10   again every 10 minutes, until stopped with Ctrl+C

uses Finnhub when FINNHUB_API_KEY is set in .env, otherwise (or when Finnhub fails) a public
RSS feed. if every source fails, the last good headlines are kept and marked stale.
"""

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from news.headlines import default_sources, fetch_once, load, save
from pipeline.paths import HEADLINES


def run_once(out: Path) -> bool:
    previous = load(out)
    if previous is None and out.exists():
        print(f"could not read the previous {out}; it will be replaced")
    payload = fetch_once(default_sources(), previous, datetime.now(UTC))
    save(payload, out)
    if payload["stale"]:
        kept = f"kept {len(payload['headlines'])} older headlines" if payload["headlines"] else ""
        print(f"STALE: {payload['error']}. {kept}".strip())
    else:
        print(f"{len(payload['headlines'])} headlines from {payload['source']} saved to {out}")
    return not payload["stale"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--every", type=float, metavar="MINUTES", help="keep refreshing")
    parser.add_argument("--out", type=Path, default=HEADLINES)
    args = parser.parse_args()
    if args.every is not None and args.every <= 0:
        print("--every must be more than 0 minutes")
        return 1

    load_dotenv()
    if args.every is None:
        return 0 if run_once(args.out) else 1
    try:
        while True:
            run_once(args.out)
            time.sleep(args.every * 60)
    except KeyboardInterrupt:
        print("stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
