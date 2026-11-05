"""describe every picture worth describing with a vision model (see rag/images.py)

uv run python -m rag.captions                 every picture not described yet
uv run python -m rag.captions --limit 5       5 more pictures, to check the descriptions first
uv run python -m rag.captions --model gemini-flash-lite   another model than RAG_MODEL

a chart, table or infographic with printed figures is read a second time, so Python can keep
only the figures both reads agree on. descriptions are saved under output/rag/captions/<model>/
and a picture already described is never sent again; run rag.ingest afterwards to index them
"""

import argparse
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

from pipeline.llm_client import LLMError, Settings, StopRun
from rag.answer import rag_settings
from rag.images import (
    NOT_INDEXED,
    WITH_FIGURES,
    CaptionStore,
    Picture,
    describe,
    find_pictures,
)


def describe_all(
    pictures: list[Picture],
    data_dir: Path,
    settings: Settings,
    store: CaptionStore,
    describe_fn: Callable = describe,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> Counter:
    """the first read of every picture, and a second of those with figures, unless saved;
    returns how many pictures of each kind were read for the first time"""
    kinds: Counter = Counter()
    distinct = list({p.key: p for p in pictures}.values())
    calls = 0

    def read(picture: Picture, n: int):
        nonlocal calls
        # free cloud tiers allow a few requests a minute; saved reads cost nothing
        if calls and settings.seconds_between_calls:
            sleep(settings.seconds_between_calls)
        calls += 1
        caption = describe_fn(picture, data_dir, settings)
        store.put(picture, caption, n)
        return caption

    for i, picture in enumerate(distinct, 1):
        first, second = store.get(picture, 1), store.get(picture, 2)
        if first is not None and (second is not None or not needs_second(first)):
            continue
        try:
            if first is None:
                first = read(picture, 1)
                kinds[first.kind] += 1
            note = " (not indexed)" if first.kind in NOT_INDEXED else ""
            if needs_second(first) and second is None:
                read(picture, 2)
                note += ", read twice"
        except LLMError as e:
            log(f"[{i}/{len(distinct)}] {picture.label}: FAILED {e}")
            continue
        log(f"[{i}/{len(distinct)}] {picture.label}: {first.kind}{note}")
    return kinds


def needs_second(caption) -> bool:
    return caption.kind in WITH_FIGURES and bool(caption.printed_values)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--data", type=Path, default=Path("Data"))
    parser.add_argument("--model", help="a preset or LiteLLM model (default RAG_MODEL)")
    parser.add_argument("--limit", type=int, help="read at most N pictures not read yet")
    args = parser.parse_args()
    load_dotenv()

    if not args.data.is_dir():
        print(f"no data folder at {args.data}")
        return 1
    settings = rag_settings(args.model)
    if missing := settings.missing_key():
        print(f"{settings.name} needs {missing} in .env")
        return 1

    pictures, problems = find_pictures(args.data)
    for problem in problems:
        print(problem)
    store = CaptionStore(settings)
    distinct = {p.key: p for p in pictures}
    done = sum(store.get(p) is not None for p in distinct.values())
    print(
        f"{len(pictures)} pictures ({len(distinct)} distinct), {done} already described "
        f"by {settings.name}"
    )
    if args.limit:
        pictures = [p for p in distinct.values() if store.get(p) is None][: args.limit]

    try:
        kinds = describe_all(pictures, args.data, settings, store)
    except StopRun as e:
        print(f"stopped: {e}\ndescriptions so far are saved; run again later to carry on")
        return 1
    if kinds:
        print("described: " + ", ".join(f"{n} {kind}" for kind, n in kinds.most_common()))
    print("now run `uv run python -m rag.ingest` to index them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
