"""turn text into vectors, through LiteLLM like the classifier, with every vector saved

vectors are saved by a hash of the model, the task and the text, one line per vector, written as
each batch comes back: an interrupted ingest carries on where it stopped, and an unchanged
passage is never sent twice
"""

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import litellm

from pipeline.llm_client import RATE_LIMIT_WAITS, RETRY_WAITS, RETRYABLE, STOPS_THE_RUN, StopRun
from pipeline.paths import RAG, model_slug

# LiteLLM prints a "Give Feedback" banner on every refused call, including the rate limits
# this module waits out on purpose
litellm.suppress_debug_info = True
# a rough count, used only for pacing; Gemini's real count for this English text is close to it
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class Embedder:
    model: str
    api_key_env: str | None = None
    # Gemini embeds a question and a passage differently when told which is which
    task_types: bool = False
    # 768 of Gemini's 3072 dimensions: Google's suggested smaller size, a quarter of the storage
    dimensions: int | None = None
    batch_size: int = 50
    # the free tier's limit is per minute, in tokens; batches are paced to stay under it
    tokens_per_minute: int | None = None
    timeout: int = 120

    @property
    def is_ollama(self) -> bool:
        return self.model.startswith("ollama")


EMBEDDERS = {
    # the free tier allows 30,000 tokens a minute (from Google's 429 message, not documented);
    # 25,000 leaves room for the rough token count
    "gemini": Embedder(
        "gemini/gemini-embedding-001",
        api_key_env="GEMINI_API_KEY",
        task_types=True,
        dimensions=768,
        tokens_per_minute=25_000,
    ),
    # about a cent for every passage; paid tiers allow far more per minute than one ingest sends
    "openai": Embedder(
        "openai/text-embedding-3-small", api_key_env="OPENAI_API_KEY", batch_size=100
    ),
    # local, free and private: `ollama pull embeddinggemma` first
    "ollama": Embedder("ollama/embeddinggemma", batch_size=16),
}
# Gemini's free tier counts each passage as a request and allows about 1,000 a day, fewer than
# the 1,210 passages, so a full ingest cannot finish in a day there
DEFAULT_EMBEDDER = "openai"


def call_embedding(embedder: Embedder, texts: list[str], task: str) -> list[list[float]]:
    """the only place that talks to the embedding model; tests pass a fake instead"""
    options = {}
    if embedder.task_types:
        options["input_type"] = task
    if embedder.dimensions:
        options["dimensions"] = embedder.dimensions
    if embedder.is_ollama:
        options["api_base"] = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
    response = litellm.embedding(
        model=embedder.model, input=texts, timeout=embedder.timeout, **options
    )
    vectors = [item["embedding"] for item in response.data]
    if len(vectors) != len(texts):
        raise ValueError(f"asked for {len(texts)} vectors, got {len(vectors)}")
    return vectors


def _with_retries(call: Callable, sleep: Callable[[float], None]):
    waits, rate_waits = list(RETRY_WAITS), list(RATE_LIMIT_WAITS)
    while True:
        try:
            return call()
        except RETRYABLE:
            if not waits:
                raise
            sleep(waits.pop(0))
        except litellm.exceptions.RateLimitError as e:
            if not rate_waits:
                # the provider's message says which limit it was: per minute, per day, or credit
                raise StopRun(
                    "the embedding model keeps refusing with a rate limit. Run again later; "
                    f"vectors so far are saved. The provider said: {str(e)[:400]}"
                ) from e
            sleep(rate_waits.pop(0))
        except STOPS_THE_RUN as e:
            raise StopRun(f"{type(e).__name__} from the embedding model: {e}") from e


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


class VectorStore:
    """vectors saved at output/rag/<model>/vectors.jsonl, keyed by model, task and text"""

    def __init__(
        self,
        embedder: Embedder,
        root: Path = RAG,
        call: Callable = call_embedding,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = print,
    ):
        self.embedder, self.call, self.sleep, self.clock, self.log = (
            embedder, call, sleep, clock, log
        )  # fmt: skip
        self.path = root / model_slug(embedder.model) / "vectors.jsonl"
        self.saved: dict[str, list[float]] = {}
        # (when, tokens) for each batch sent in the last minute, for pacing
        self.sent: list[tuple[float, int]] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                # only a run killed mid-write leaves a broken last line; that vector is redone
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.saved[row["key"]] = row["vector"]

    def key(self, text: str, task: str) -> str:
        e = self.embedder
        payload = json.dumps([e.model, e.dimensions, task if e.task_types else None, text])
        return hashlib.sha256(payload.encode()).hexdigest()[:20]

    def missing(self, texts: list[str], task: str) -> list[str]:
        return list(dict.fromkeys(t for t in texts if self.key(t, task) not in self.saved))

    def minutes_needed(self, texts: list[str]) -> float:
        """the least time the per minute limit allows for these texts"""
        limit = self.embedder.tokens_per_minute
        return sum(map(estimate_tokens, texts)) / limit if limit else 0

    def _batches(self, texts: list[str]) -> list[list[str]]:
        """at most batch_size texts, and at most a minute's tokens, per batch"""
        limit = self.embedder.tokens_per_minute
        batches, current, tokens = [], [], 0
        for text in texts:
            n = estimate_tokens(text)
            full = len(current) == self.embedder.batch_size or (limit and tokens + n > limit)
            if current and full:
                batches.append(current)
                current, tokens = [], 0
            current.append(text)
            tokens += n
        return [*batches, current] if current else batches

    def _pace(self, tokens: int) -> None:
        """wait until sending this many tokens keeps the last minute under the limit"""
        limit = self.embedder.tokens_per_minute
        if not limit:
            return
        while True:
            now = self.clock()
            self.sent = [(at, n) for at, n in self.sent if now - at < 60]
            if not self.sent or sum(n for _, n in self.sent) + tokens <= limit:
                break
            wait = self.sent[0][0] + 60 - now
            self.log(f"waiting {wait:.0f}s for the per minute limit")
            self.sleep(wait)
        self.sent.append((self.clock(), tokens))

    def embed(self, texts: list[str], task: str) -> list[list[float]]:
        """vectors for every text, in order; only unsaved texts are sent"""
        todo = self.missing(texts, task)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        done = 0
        for batch in self._batches(todo):
            self._pace(sum(map(estimate_tokens, batch)))
            vectors = _with_retries(lambda b=batch: self.call(self.embedder, b, task), self.sleep)
            with self.path.open("a", encoding="utf-8") as f:
                for text, vector in zip(batch, vectors, strict=True):
                    key = self.key(text, task)
                    self.saved[key] = vector
                    f.write(json.dumps({"key": key, "vector": vector}) + "\n")
            done += len(batch)
            self.log(f"embedded {done}/{len(todo)}")
        return [self.saved[self.key(t, task)] for t in texts]
