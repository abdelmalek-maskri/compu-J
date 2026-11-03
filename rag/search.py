"""find the passages that answer a question: filters, keyword search, meaning search, merged

keyword search (BM25, a refined tf-idf) finds exact names, tickers and figures such as "OPEC" or
"EUR/USD", which embeddings blur. meaning search (cosine similarity between embeddings) finds
"crude" when the passage says "oil". each misses what the other finds, so both rankings are
merged by rank (reciprocal rank fusion), which needs no tuning between two kinds of score
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from rag.chunks import Chunk

# the usual BM25 settings: how fast repeated words stop adding, and how much length counts
K1 = 1.5
B = 0.75
# reciprocal rank fusion's usual constant: a higher rank always counts, but less and less
RRF_K = 60
# a 42 page PDF matches many questions; a cap per email leaves room for other sources
MAX_PER_EMAIL = 3


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


@dataclass
class Filters:
    """what the classification already knows, used before any search: a question about
    Barclays should never be answered from Goldman Sachs, however similar the words"""

    bank: str | None = None
    since: str | None = None
    until: str | None = None
    tag: str | None = None
    company: str | None = None
    market_wrap: str | None = None

    def allows(self, chunk: Chunk) -> bool:
        folded = str.casefold
        if self.bank and folded(chunk.bank or "") != folded(self.bank):
            return False
        # ISO dates compare correctly as text; an undated email is left out of a date filter
        if self.since and not (chunk.date and chunk.date >= self.since):
            return False
        if self.until and not (chunk.date and chunk.date <= self.until):
            return False
        if self.tag and folded(self.tag) not in {folded(t) for t in chunk.asset_tags}:
            return False
        if self.company and not any(folded(self.company) in folded(c) for c in chunk.companies):
            return False
        return not (self.market_wrap and chunk.market_wrap != self.market_wrap.upper())


class Keyword:
    """BM25 over every passage; the corpus statistics are counted once, at load"""

    def __init__(self, chunks: list[Chunk]):
        self.docs = [Counter(tokens(c.embedded_text)) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.average = sum(self.lengths) / max(len(self.docs), 1)
        df = Counter(word for doc in self.docs for word in doc)
        n = len(self.docs)
        # rare words weigh more: "Brent" says far more about a passage than "market"
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def scores(self, question: str) -> list[float]:
        words = set(tokens(question))
        out = []
        for doc, length in zip(self.docs, self.lengths, strict=True):
            norm = K1 * (1 - B + B * length / self.average)
            out.append(
                sum(self.idf[w] * doc[w] * (K1 + 1) / (doc[w] + norm) for w in words if w in doc)
            )
        return out


def cosine(a: list[float], b: list[float]) -> float:
    """divided by both lengths, so a long vector does not win by being long"""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norms if norms else 0.0


def ranking(scores: list[float], allowed: list[int]) -> list[int]:
    """positions of the allowed passages with a score above zero, best first"""
    return sorted((i for i in allowed if scores[i] > 0), key=lambda i: -scores[i])


def fuse(*rankings: list[int]) -> list[int]:
    """reciprocal rank fusion: each ranking adds 1 / (RRF_K + rank) to every passage in it"""
    total: Counter = Counter()
    for order in rankings:
        for rank, i in enumerate(order, 1):
            total[i] += 1 / (RRF_K + rank)
    return [i for i, _ in total.most_common()]


def diverse(order: list[int], chunks: list[Chunk], k: int) -> list[int]:
    """the first k passages, at most MAX_PER_EMAIL from any one email"""
    kept, per_email = [], Counter()
    for i in order:
        if per_email[chunks[i].email_id] < MAX_PER_EMAIL:
            kept.append(i)
            per_email[chunks[i].email_id] += 1
        if len(kept) == k:
            break
    return kept


@dataclass
class Hit:
    chunk: Chunk
    keyword_rank: int | None
    vector_rank: int | None


def search(
    question: str,
    chunks: list[Chunk],
    keyword: Keyword,
    filters: Filters,
    k: int = 8,
    mode: str = "hybrid",
    query_vector: list[float] | None = None,
    vectors: list[list[float]] | None = None,
) -> list[Hit]:
    """mode is hybrid, keyword or vector; the last two exist to show what each one misses"""
    allowed = [i for i, c in enumerate(chunks) if filters.allows(c)]
    by_keyword = ranking(keyword.scores(question), allowed) if mode != "vector" else []
    by_vector = []
    if mode != "keyword":
        if query_vector is None or vectors is None:
            raise ValueError(f"{mode} search needs the question's vector and the passages'")
        similarity = [cosine(query_vector, v) for v in vectors]
        # every passage has some similarity, so this ranks all allowed passages
        by_vector = sorted(allowed, key=lambda i: -similarity[i])
    order = fuse(by_keyword, by_vector)
    k_rank = {i: r for r, i in enumerate(by_keyword, 1)}
    v_rank = {i: r for r, i in enumerate(by_vector, 1)}
    return [Hit(chunks[i], k_rank.get(i), v_rank.get(i)) for i in diverse(order, chunks, k)]
