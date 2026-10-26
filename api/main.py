"""the dashboard's API: the classified emails, each email itself, its files, and the headlines

run from the repo root:  uv run uvicorn api.main:app --reload
then the interactive documentation is at http://localhost:8000/docs
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from api.safe_html import content_security_policy, make_safe, remote_images
from pipeline.allowed_tags import ASSET_TAXONOMY, BANK_NAMES, INDUSTRY_TAXONOMY
from pipeline.clean_emails import read_html
from pipeline.paths import DELIVERABLE, DETAILS, HEADLINES

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
    # the React dev server; the browser refuses other sites reading this API
    dashboard_origin: str = field(
        default_factory=lambda: os.getenv("DASHBOARD_ORIGIN", "http://localhost:5173")
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
        CORSMiddleware, allow_origins=[config.dashboard_origin], allow_methods=["GET"]
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
                    "date_hint": meta.get("date_hint"),
                    "flag_count": len(meta.get("flags", [])),
                }
            )
        return result

    def email_body(email_id: str) -> str | None:
        path = config.data_dir / email_id / "emailbody.html"
        return read_html(path)[0] if path.exists() else None

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
        folder = (config.data_dir / email_id).resolve()
        path = (folder / name).resolve()
        # "../../.env" and similar resolve outside the email's folder and are refused
        if not path.is_relative_to(folder) or path.suffix.lower() not in SERVED_SUFFIXES:
            raise HTTPException(404, "no such file")
        if not path.is_file():
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

    return app


app = create_app()
