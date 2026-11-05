"""build the search index: emails and PDF pages, split into passages, each turned into a vector

uv run python -m rag.ingest                  passages and vectors (calls the embedding model)
uv run python -m rag.ingest --no-embed       passages only: keyword search works without a model
uv run python -m rag.ingest --embedder ollama

reads Data/ and classified_emails.json (bank, date, title and tags for each passage's header and
the filters), and the picture descriptions saved by rag.captions, which it never calls itself.
writes output/rag/chunks.jsonl and output/rag/<model>/vectors.jsonl
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from pypdf.errors import PdfReadError

from pipeline.clean_emails import PreparedEmail, prepare_all, read_pdf_pages
from pipeline.llm_client import StopRun
from pipeline.paths import DELIVERABLE, RAG
from rag.answer import rag_settings
from rag.chunks import Chunk, Source, boilerplate, make_chunks, strip_lines
from rag.embed import DEFAULT_EMBEDDER, EMBEDDERS, Embedder, VectorStore
from rag.images import (
    NOT_INDEXED,
    CaptionStore,
    Picture,
    check_values,
    find_pictures,
    passage_text,
)

CHUNKS = RAG / "chunks.jsonl"
DOCUMENT, QUERY = "RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"
# a page with less text than this is a cover, a divider or a chart with no words
MIN_PAGE_CHARS = 100


def _source(email: PreparedEmail, record: dict | None, text: str, **where) -> Source:
    # an email the classifier has not seen still gets the rules' bank, so it can be found
    record = record or {}
    return Source(
        email_id=email.id,
        text=text,
        title=record.get("folder_name") or f"email {email.id}",
        bank=record.get("bank") or email.bank,
        date=record.get("date"),
        market_wrap=record.get("market_wrap", "NO"),
        asset_tags=record.get("asset_tags", []),
        companies=record.get("companies_mentioned", []),
        **where,
    )


def build_sources(
    emails: list[PreparedEmail], records: dict[str, dict], data_dir: Path
) -> tuple[list[Source], list[str]]:
    """every email body and every PDF page with text, boilerplate removed; returns the problems
    met on the way, such as an unreadable PDF"""
    problems, pdf_pages = [], {}
    emails = [e for e in emails if not e.duplicate_of]
    for email in emails:
        for name in email.attachments.pdfs:
            try:
                pdf_pages[email.id, name] = read_pdf_pages(data_dir / email.id / name)
            except PdfReadError as e:
                problems.append(f"{email.id}/{name}: could not read ({e})")

    documents = [e.body for e in emails] + ["\n".join(p) for p in pdf_pages.values()]
    remove = boilerplate(documents)

    sources = []
    for email in emails:
        record = records.get(email.id)
        if record is None:
            problems.append(f"{email.id}: not in {DELIVERABLE}, so no date, title or tags")
        body = strip_lines(email.body, remove)
        if body:
            sources.append(_source(email, record, body))
        for name in email.attachments.pdfs:
            for n, page in enumerate(pdf_pages.get((email.id, name), []), 1):
                text = strip_lines(page, remove)
                if len(text) >= MIN_PAGE_CHARS:
                    sources.append(_source(email, record, text, pdf=name, page=n))
    return sources, problems


def picture_sources(
    pictures: list[Picture],
    store: CaptionStore,
    emails: list[PreparedEmail],
    records: dict[str, dict],
    data_dir: Path,
) -> tuple[list[Source], Counter]:
    """a passage for each described picture worth finding, with only the figures Python could
    confirm; returns the passages and how many pictures were left out, by reason"""
    by_id = {e.id: e for e in emails if not e.duplicate_of}
    pages: dict[tuple[str, str], list[str]] = {}
    sources, left_out = [], Counter()
    for picture in pictures:
        email = by_id.get(picture.email_id)
        first = store.get(picture, 1)
        if email is None:
            left_out["in a duplicate email"] += 1
            continue
        if first is None:
            left_out["not described yet"] += 1
            continue
        if first.kind in NOT_INDEXED:
            left_out[first.kind] += 1
            continue
        # the words around the picture: its PDF page, or the email it is in
        context = email.body
        where = {"image": picture.file}
        if picture.page:
            name = (email.id, picture.file)
            if name not in pages:
                try:
                    pages[name] = read_pdf_pages(data_dir / email.id / picture.file)
                except PdfReadError:
                    pages[name] = []
            page_texts = pages[name]
            context = page_texts[picture.page - 1] if picture.page <= len(page_texts) else ""
            where = {"pdf": picture.file, "page": picture.page}
        confirmed, unconfirmed = check_values(first, store.get(picture, 2), context)
        text = passage_text(first, confirmed, unconfirmed)
        sources.append(_source(email, records.get(email.id), text, picture=first.kind, **where))
    return sources, left_out


def load_chunks(path: Path = CHUNKS) -> list[Chunk]:
    if not path.exists():
        raise FileNotFoundError(f"no index at {path}: run `uv run python -m rag.ingest` first")
    return [Chunk(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


def ready(embedder: Embedder) -> str | None:
    """why this embedder cannot run now, or None"""
    if embedder.api_key_env and not os.getenv(embedder.api_key_env):
        return f"{embedder.model} needs {embedder.api_key_env} in .env"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--data", type=Path, default=Path("Data"))
    parser.add_argument("--embedder", choices=EMBEDDERS, default=DEFAULT_EMBEDDER)
    parser.add_argument("--no-embed", action="store_true", help="write the passages only")
    parser.add_argument(
        "--caption-model", help="whose picture descriptions to index (default RAG_MODEL)"
    )
    args = parser.parse_args()
    load_dotenv()

    if not args.data.is_dir():
        print(f"no data folder at {args.data}")
        return 1
    if not DELIVERABLE.exists():
        print(f"no {DELIVERABLE}: run classify.py first, its answers become the filters")
        return 1
    records = {r["source_file"]: r for r in json.loads(DELIVERABLE.read_text(encoding="utf-8"))}

    emails, failures = prepare_all(args.data)
    for folder, reason in failures.items():
        print(f"could not prepare {folder}: {reason}")
    sources, problems = build_sources(emails, records, args.data)
    pictures, picture_problems = find_pictures(args.data)
    for problem in problems + picture_problems:
        print(problem)
    caption_settings = rag_settings(args.caption_model)
    store = CaptionStore(caption_settings)
    described, left_out = picture_sources(pictures, store, emails, records, args.data)
    print(
        f"{len(described)} of {len(pictures)} pictures indexed, described by "
        f"{caption_settings.name}; left out: "
        + (", ".join(f"{n} {why}" for why, n in left_out.most_common()) or "none")
    )
    if left_out["not described yet"]:
        print("run `uv run python -m rag.captions` to describe the rest")
    chunks = make_chunks(sources + described)

    CHUNKS.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHUNKS.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(c.to_json()) + "\n" for c in chunks), encoding="utf-8")
    tmp.replace(CHUNKS)
    pdf_chunks = sum(1 for c in chunks if c.pdf and not c.picture)
    picture_chunks = sum(1 for c in chunks if c.picture)
    print(
        f"{len(chunks)} passages from {len({c.email_id for c in chunks})} emails "
        f"({pdf_chunks} from PDF pages, {picture_chunks} describing pictures), written to {CHUNKS}"
    )
    if args.no_embed:
        return 0

    embedder = EMBEDDERS[args.embedder]
    if problem := ready(embedder):
        print(problem)
        return 1
    store = VectorStore(embedder)
    todo = store.missing([c.embedded_text for c in chunks], DOCUMENT)
    # passages with the same text (such as two emails sharing a paragraph) share one vector
    unique = len({c.embedded_text for c in chunks})
    print(f"{unique - len(todo)} of {unique} distinct passages already embedded, {len(todo)} to go")
    if minutes := store.minutes_needed(todo):
        print(f"the free tier's per minute limit makes this take at least {minutes:.0f} minutes")
    try:
        store.embed([c.embedded_text for c in chunks], DOCUMENT)
    except StopRun as e:
        print(f"stopped: {e}")
        return 1
    print(f"vectors saved to {store.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
