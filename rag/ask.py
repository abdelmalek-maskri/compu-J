"""ask a question of the research emails and get an answer that cites its sources

uv run python -m rag.ask "What is the view on oil?"
uv run python -m rag.ask "What is the view on oil?" --bank Barclays
uv run python -m rag.ask "EUR/USD outlook" --mode keyword --sources-only   no model calls at all
uv run python -m rag.ask "..." --since 2026-04-10 --tag FX --market-wrap NO

--mode keyword | vector | hybrid (default) shows what each kind of search finds;
--sources-only prints the passages found without asking the model for an answer
"""

import argparse
import sys

from dotenv import load_dotenv

from pipeline.llm_client import RETRYABLE, LLMError, Settings, StopRun
from rag.embed import DEFAULT_EMBEDDER, EMBEDDERS
from rag.qa import Index, NotReady, answer
from rag.search import Filters, Hit


def print_sources(hits: list[Hit]) -> None:
    print("\nSources:")
    for n, hit in enumerate(hits, 1):
        c = hit.chunk
        ranks = f"keyword #{hit.keyword_rank or '-'}, meaning #{hit.vector_rank or '-'}"
        print(f"[{n}] {c.email_id} | {c.bank} | {c.date} | {c.title} | {c.where}  ({ranks})")
        preview = " ".join(c.text.split())
        print(f"    {preview[:220]}{'...' if len(preview) > 220 else ''}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("question")
    parser.add_argument("--mode", choices=["hybrid", "keyword", "vector"], default="hybrid")
    parser.add_argument("--k", type=int, default=8, help="passages given to the model")
    parser.add_argument("--bank")
    parser.add_argument("--since", help="YYYY-MM-DD")
    parser.add_argument("--until", help="YYYY-MM-DD")
    parser.add_argument("--tag", help="an asset tag, such as FX or Oil")
    parser.add_argument("--company")
    parser.add_argument("--market-wrap", choices=["YES", "NO"])
    parser.add_argument(
        "--picture", help='only picture descriptions: "any" or a kind, such as cartoon or chart'
    )
    parser.add_argument("--embedder", choices=EMBEDDERS, default=DEFAULT_EMBEDDER)
    parser.add_argument("--model", help="answer model preset (default RAG_MODEL, else gpt-6-luna)")
    parser.add_argument("--sources-only", action="store_true", help="no answer, no model call")
    args = parser.parse_args()
    load_dotenv()

    filters = Filters(
        args.bank, args.since, args.until, args.tag, args.company, args.market_wrap, args.picture
    )
    settings = Settings.from_name(args.model) if args.model else None
    try:
        index = Index(embedder=EMBEDDERS[args.embedder])
        reply = answer(
            index, args.question, filters, args.mode, args.k, settings,
            sources_only=args.sources_only,
        )  # fmt: skip
    except NotReady as e:
        print(e)
        return 1
    except (StopRun, LLMError, *RETRYABLE) as e:
        print(f"no answer: {e}")
        return 1

    if not reply.hits:
        print("No passage matches the question and filters.")
        return 0
    if reply.answered is not None:
        print(f"\nQ: {args.question}\n")
        if not reply.answered or not reply.points:
            print("The sources found do not answer this question.")
        for p in reply.points:
            mark = "" if p.verified else f"  [NOT VERIFIED: {p.problem}]"
            if p.from_picture:
                mark += "  [from a picture description: check the picture]"
            print(f"* {p.claim} [{p.source}]{mark}")
            print(f'    "{p.quote}"')
        if reply.missing:
            print(f"\nNot covered by the sources: {reply.missing}")
        if unverified := sum(not p.verified for p in reply.points):
            print(f"\n{unverified} of {len(reply.points)} points could not be checked.")
    if reply.reading.picture:
        print(f"\n(searched {reply.reading.picture} pictures only, as the question asks for them)")
    if reply.reading.banks:
        print(f"\n(searched each bank on its own: {', '.join(reply.reading.banks)})")
        if reply.reading.banks_without:
            print(f"(no passage found for {', '.join(reply.reading.banks_without)})")
    print_sources(reply.hits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
