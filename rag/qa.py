"""one question answered: the steps shared by the command line (rag/ask.py) and the API

the index (passages, keyword statistics, vectors) is loaded once and kept, so each question
costs only its own embedding and answer calls
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.llm_client import Settings, complete
from pipeline.paths import RAG
from rag.answer import CheckedPoint, ask_model, check
from rag.embed import DEFAULT_EMBEDDER, EMBEDDERS, Embedder, VectorStore, call_embedding
from rag.ingest import CHUNKS, DOCUMENT, QUERY, load_chunks, ready
from rag.search import Filters, Hit, Keyword, search


class NotReady(Exception):
    """the index, its vectors or a key is missing; the message says what to do"""


@dataclass
class Reply:
    hits: list[Hit]
    # None when only the sources were asked for
    answered: bool | None = None
    points: list[CheckedPoint] = field(default_factory=list)
    missing: str = ""

    def to_json(self) -> dict:
        return {
            "answered": self.answered,
            "missing": self.missing,
            "points": [p.__dict__ for p in self.points],
            "sources": [
                {
                    "n": n,
                    "email_id": h.chunk.email_id,
                    "title": h.chunk.title,
                    "bank": h.chunk.bank,
                    "date": h.chunk.date,
                    "pdf": h.chunk.pdf,
                    "page": h.chunk.page,
                    "where": h.chunk.where,
                    "text": h.chunk.text,
                    "keyword_rank": h.keyword_rank,
                    "vector_rank": h.vector_rank,
                }
                for n, h in enumerate(self.hits, 1)
            ],
        }


class Index:
    def __init__(
        self,
        chunks_path: Path = CHUNKS,
        root: Path = RAG,
        embedder: Embedder = EMBEDDERS[DEFAULT_EMBEDDER],
        embed_call: Callable = call_embedding,
    ):
        try:
            self.chunks = load_chunks(chunks_path)
        except FileNotFoundError as e:
            raise NotReady(str(e)) from e
        self.keyword = Keyword(self.chunks)
        self.root, self.embedder, self.embed_call = root, embedder, embed_call
        self.store = self._store()
        self._vectors: list[list[float]] | None = None
        # questions are embedded through one store that appends to one file
        self.lock = threading.Lock()

    def _store(self) -> VectorStore:
        return VectorStore(self.embedder, root=self.root, call=self.embed_call, log=lambda _: None)

    def vectors(self) -> list[list[float]]:
        if self._vectors is None:
            texts = [c.embedded_text for c in self.chunks]
            # an ingest may have finished since this index was loaded
            if self.store.missing(texts, DOCUMENT):
                self.store = self._store()
            if missing := len(self.store.missing(texts, DOCUMENT)):
                raise NotReady(
                    f"{missing} passages have no vector yet: run `uv run python -m rag.ingest`"
                )
            # every vector is saved, so this reads them without calling the model
            self._vectors = self.store.embed(texts, DOCUMENT)
        return self._vectors

    def search(self, question: str, filters: Filters, mode: str, k: int) -> list[Hit]:
        query_vector = vectors = None
        if mode != "keyword":
            if problem := ready(self.embedder):
                raise NotReady(problem)
            vectors = self.vectors()
            with self.lock:
                query_vector = self.store.embed([question], QUERY)[0]
        return search(question, self.chunks, self.keyword, filters, k, mode, query_vector, vectors)


def answer(
    index: Index,
    question: str,
    filters: Filters,
    mode: str = "hybrid",
    k: int = 8,
    settings: Settings | None = None,
    complete_fn: Callable = complete,
    sources_only: bool = False,
) -> Reply:
    """the passages found, and unless sources_only, the model's answer with each quote checked"""
    hits = index.search(question, filters, mode, k)
    if sources_only or not hits:
        return Reply(hits)
    settings = settings or Settings.from_env()
    if missing := settings.missing_key():
        raise NotReady(f"{settings.name} needs {missing} in .env")
    result = ask_model(question, hits, settings, complete_fn)
    return Reply(hits, result.answered, check(result, hits), result.missing)
