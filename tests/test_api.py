import json

import pytest
from fastapi.testclient import TestClient

from api.main import Config, create_app
from api.safe_html import make_safe

EMAIL = """<html><head><meta http-equiv="Content-Type" content="text/html; charset=windows-1252">
<script>let baseHref=document.querySelector("base")</script></head>
<body onload="track()"><img src="https://live.barcap.com/pixel.gif" width="1">
<p>Rates rallied</p><a href="https://research.db.com/report">Read</a>
<a href="javascript:alert(1)">bad</a></body></html>"""

RECORD = {
    "folder_name": "FX Daily",
    "bank": "Deutsche Bank",
    "date": "2026-04-10",
    "market_wrap": "NO",
    "primary_asset_tag": "FX",
    "asset_tags": ["FX", "JPY"],
    "companies_mentioned": [],
    "industry_subindustry": [],
    "pdf_attachment": ["report.pdf"],
    "source_file": "035300",
}


@pytest.fixture
def client(tmp_path):
    folder = tmp_path / "Data" / "035300"
    folder.mkdir(parents=True)
    (folder / "emailbody.html").write_text(EMAIL)
    (folder / "report.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / ".env").write_text("GEMINI_API_KEY=secret")
    (tmp_path / "classified_emails.json").write_text(json.dumps([RECORD]))
    details = {"035300": {"content_type": "research", "date_hint": None, "flags": [{"kind": "x"}]}}
    (tmp_path / "details.json").write_text(json.dumps(details))
    config = Config(
        data_dir=tmp_path / "Data",
        deliverable=tmp_path / "classified_emails.json",
        details=tmp_path / "details.json",
        headlines=tmp_path / "headlines.json",
    )
    return TestClient(create_app(config))


def test_the_list_joins_the_brief_fields_with_what_the_list_needs(client):
    [email] = client.get("/api/emails").json()
    assert email["folder_name"] == "FX Daily"
    assert (email["content_type"], email["flag_count"]) == ("research", 1)


def test_one_email_returns_its_record_and_details(client):
    body = client.get("/api/emails/035300").json()
    assert body["record"] == RECORD
    assert body["details"]["content_type"] == "research"


@pytest.mark.parametrize("email_id", ["999999", "035300x", "..%2F.env"])
def test_unknown_or_malformed_ids_are_not_found(client, email_id):
    assert client.get(f"/api/emails/{email_id}").status_code == 404


def test_the_email_html_is_cleaned_and_labelled_utf8(client):
    response = client.get("/api/emails/035300/html")
    html = response.text
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "<script" not in html and "onload" not in html and "windows-1252" not in html
    assert 'data-blocked-src="https://live.barcap.com/pixel.gif"' in html
    assert 'target="_blank"' in html and "javascript:" not in html
    policy = response.headers["content-security-policy"]
    assert "img-src data:;" in policy and "sandbox" in policy


def test_images_load_only_when_asked(client):
    response = client.get("/api/emails/035300/html?images=true")
    assert 'src="https://live.barcap.com/pixel.gif"' in response.text
    assert "img-src data: https:;" in response.headers["content-security-policy"]


def test_attachments_are_served(client):
    response = client.get("/api/emails/035300/files/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"


@pytest.mark.parametrize(
    "name", ["../../.env", "..%2F..%2F.env", "emailbody.html", "missing.pdf", "/etc/passwd"]
)
def test_only_files_inside_the_email_folder_can_be_downloaded(client, name):
    assert client.get(f"/api/emails/035300/files/{name}").status_code == 404


def test_tags_come_from_the_brief(client):
    tags = client.get("/api/tags").json()
    assert "Credit Strategy" in tags["asset_classes"]["Fixed Income"]
    assert "Other" in tags["banks"]


def test_headlines_before_the_news_script_ran(client):
    assert client.get("/api/headlines").json()["error"] == "no headlines yet: run fetch_news.py"


def test_cleaning_keeps_the_content():
    html = make_safe("<p>Rates <b>rallied</b></p>")
    assert "Rates <b>rallied</b>" in html and '<meta charset="utf-8"/>' in html
