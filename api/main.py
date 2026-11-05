"""the dashboard's API: the classified emails, each email itself, its files, and the headlines

run from the repo root:  uv run uvicorn api.main:app --reload
then the interactive documentation is at http://localhost:8000/docs

when the dashboard has been built (web/dist, as in the Docker image), it is served here too,
so one address gives both
"""

import json
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal, get_args

import litellm
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.safe_html import content_security_policy, make_safe, remote_images
from pipeline.allowed_tags import ASSET_TAXONOMY, BANK_NAMES, INDUSTRY_TAXONOMY
from pipeline.clean_emails import read_html
from pipeline.llm_client import RETRYABLE, LLMError, Settings, StopRun, complete
from pipeline.paths import DELIVERABLE, DETAILS, HEADLINES, RAG
from rag.embed import DEFAULT_EMBEDDER, EMBEDDERS, Embedder, call_embedding
from rag.images import NOT_INDEXED, Kind
from rag.ingest import CHUNKS
from rag.qa import Index, NotReady, answer
from rag.search import Filters

# the questions page calls the embedding and answer models, whose keys live in .env
load_dotenv()
# the kinds of picture a question can be limited to: those that are indexed
PICTURE_KINDS = tuple(k for k in get_args(Kind) if k not in NOT_INDEXED)

EMAIL_ID = re.compile(r"\d{6}")
# only these can be downloaded; emailbody.html is only served cleaned, through /html
SERVED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".gif"}
NO_HEADLINES = {
    "last_updated": None,
    "stale": True,
    "error": "no headlines yet: run fetch_news.py",
    "headlines": [],
}


@dataclass(frozen=True)
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "Data")))
    deliverable: Path = DELIVERABLE
    details: Path = DETAILS
    headlines: Path = HEADLINES
    web_dir: Path = Path("web/dist")
    # the React dev server; the browser refuses other sites reading this API
    dashboard_origin: str = field(
        default_factory=lambda: os.getenv("DASHBOARD_ORIGIN", "http://localhost:5173")
    )
    # the question answering index (built by rag/ingest.py) and its models; tests pass fakes
    rag_chunks: Path = CHUNKS
    rag_root: Path = RAG
    embedder: Embedder = EMBEDDERS[DEFAULT_EMBEDDER]
    embed_call: Callable = call_embedding
    # None: RAG_MODEL from .env, else gpt-6-luna, read when a question comes in
    answer_settings: Settings | None = None
    answer_complete: Callable = complete


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    mode: Literal["hybrid", "keyword", "vector"] = "hybrid"
    bank: str | None = None
    since: date | None = None
    until: date | None = None
    tag: str | None = None
    picture: Literal["any", *PICTURE_KINDS] | None = Field(
        None, description='only picture descriptions: "any", or one kind of picture'
    )
    k: int = Field(8, ge=1, le=12, description="passages given to the model")
    sources_only: bool = Field(False, description="the passages found, without an answer")
    read_question: bool = Field(
        True, description='a question naming a kind of picture ("cartoons") searches those first'
    )


def _read_json(path: Path, default):
    """files are re-read on each request, so a new classify or news run shows up at once"""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise HTTPException(503, f"{path} is not readable JSON: {e}") from e


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config()
    app = FastAPI(title="Research email dashboard API")
    app.add_middleware(
        CORSMiddleware, allow_origins=[config.dashboard_origin], allow_methods=["GET", "POST"]
    )

    def records() -> dict[str, dict]:
        return {r["source_file"]: r for r in _read_json(config.deliverable, [])}

    def details() -> dict[str, dict]:
        return _read_json(config.details, {})

    def known(email_id: str) -> dict:
        record = records().get(email_id) if EMAIL_ID.fullmatch(email_id) else None
        if record is None:
            raise HTTPException(404, f"no classified email {email_id}")
        return record

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "emails": len(records()),
            "details": config.details.exists(),
            "headlines": config.headlines.exists(),
        }

    @app.get("/api/emails")
    def list_emails():
        """the brief's fields for every email, plus what the list needs from the details"""
        extra = details()
        result = []
        for email_id, record in sorted(records().items()):
            meta = extra.get(email_id, {})
            result.append(
                {
                    **record,
                    "content_type": meta.get("content_type"),
                    # a date from a link address, or one whose source is unknown, is shown as
                    # not confirmed
                    "date_confirmed": meta.get("date_source") not in (None, "link"),
                    "received": meta.get("received"),
                    "flag_count": len(meta.get("flags", [])),
                }
            )
        return result

    def inside(email_id: str, name: str) -> Path | None:
        """a file in the email's own folder; anything a link or "../" points elsewhere is not"""
        root = config.data_dir.resolve()
        folder = (root / email_id).resolve()
        path = (folder / name).resolve()
        if folder.parent != root or not path.is_relative_to(folder) or not path.is_file():
            return None
        return path

    def email_body(email_id: str) -> str | None:
        path = inside(email_id, "emailbody.html")
        return read_html(path)[0] if path else None

    @app.get("/api/emails/{email_id}")
    def get_email(email_id: str):
        record = known(email_id)
        html = email_body(email_id)
        return {
            "record": record,
            "details": details().get(email_id, {}),
            "remote_images": remote_images(html) if html else 0,
        }

    @app.get("/api/emails/{email_id}/html", response_class=HTMLResponse)
    def email_html(email_id: str, images: bool = False):
        known(email_id)
        html = email_body(email_id)
        if html is None:
            raise HTTPException(404, f"no email body for {email_id}")
        return HTMLResponse(
            make_safe(html, allow_images=images, files_url=f"/api/emails/{email_id}/files/"),
            # stated here, so browsers ignore the outdated labels inside the files
            media_type="text/html; charset=utf-8",
            headers={"Content-Security-Policy": content_security_policy(images)},
        )

    @app.get("/api/emails/{email_id}/files/{name:path}")
    def email_file(email_id: str, name: str):
        known(email_id)
        path = inside(email_id, name)
        if path is None or path.suffix.lower() not in SERVED_SUFFIXES:
            raise HTTPException(404, "no such file")
        return FileResponse(path)

    @app.get("/api/tags")
    def tags():
        """the brief's tag lists, so the dashboard's filters are never typed in by hand"""
        return {
            "asset_classes": ASSET_TAXONOMY,
            "industries": INDUSTRY_TAXONOMY,
            "banks": BANK_NAMES,
        }

    @app.get("/api/headlines")
    def headlines():
        return _read_json(config.headlines, NO_HEADLINES)

    loaded: dict = {}
    loading = threading.Lock()

    def rag_index() -> Index:
        """loaded on the first question and kept; loaded again when an ingest rewrites it"""
        with loading:
            if not config.rag_chunks.exists():
                raise NotReady("no search index yet: run `uv run python -m rag.ingest`")
            stamp = config.rag_chunks.stat().st_mtime
            if loaded.get("stamp") != stamp:
                loaded["index"] = Index(
                    config.rag_chunks, config.rag_root, config.embedder, config.embed_call
                )
                loaded["stamp"] = stamp
            return loaded["index"]

    @app.post("/api/ask")
    def ask(q: Question):
        """a plain def: the model calls block, so FastAPI runs this in a worker thread"""
        question = q.question.strip()
        if not question:
            raise HTTPException(422, "the question is empty")
        filters = Filters(
            bank=q.bank or None,
            since=q.since.isoformat() if q.since else None,
            until=q.until.isoformat() if q.until else None,
            tag=q.tag or None,
            picture=q.picture,
        )
        try:
            reply = answer(
                rag_index(), question, filters, q.mode, q.k, config.answer_settings,
                config.answer_complete, q.sources_only, q.read_question,
            )  # fmt: skip
        except NotReady as e:
            raise HTTPException(503, str(e)) from e
        except StopRun as e:
            raise HTTPException(429, f"the model is refusing for now, try again later: {e}") from e
        except (LLMError, *RETRYABLE, litellm.exceptions.BadRequestError) as e:
            raise HTTPException(502, f"the model call failed: {e}") from e
        return {"question": question, "mode": q.mode, **reply.to_json()}

    # last, so the /api routes above are matched first
    if (config.web_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=config.web_dir, html=True), name="dashboard")
    return app


app = create_app()
