import json
import shutil

import pytest
from fastapi.testclient import TestClient

from api.main import Config, create_app
from api.safe_html import make_safe, remote_images
from pipeline.repair_text import APOSTROPHE, CLOSE_QUOTE, EN_DASH, OPEN_QUOTE, R

EMAIL = """<html><head><meta http-equiv="Content-Type" content="text/html; charset=windows-1252">
<script>let baseHref=document.querySelector("base")</script></head>
<body onload="track()"><img src="https://live.barcap.com/pixel.gif" width="1">
<img src="/filestore/market_research/035300/inline/image001.png">
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
    (folder / "inline").mkdir()
    (folder / "inline" / "image001.png").write_bytes(b"\x89PNG fake")
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
    assert body["remote_images"] == 1  # the tracking pixel, not the image saved with the email


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
    assert "img-src 'self' data:;" in policy and "sandbox" in policy


def test_images_load_only_when_asked(client):
    response = client.get("/api/emails/035300/html?images=true")
    assert 'src="https://live.barcap.com/pixel.gif"' in response.text
    assert "img-src 'self' data: https:;" in response.headers["content-security-policy"]


def test_images_saved_with_the_email_point_at_its_files(client):
    html = client.get("/api/emails/035300/html").text
    assert 'src="/api/emails/035300/files/inline/image001.png"' in html
    assert client.get("/api/emails/035300/files/inline/image001.png").status_code == 200


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


def test_characters_lost_in_the_export_are_put_back():
    html = make_safe(f'<p>it{R}s the {R}Bank{R}</p><img alt="13th {R} 17th"><!-- a{R}b -->')
    assert f"it{APOSTROPHE}s the {OPEN_QUOTE}Bank{CLOSE_QUOTE}" in html
    assert f'alt="13th {EN_DASH} 17th"' in html
    assert f"a{R}b" in html  # comments are left alone


def test_an_email_folder_linked_from_elsewhere_is_not_served(client, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "emailbody.html").write_text("<p>secret</p>")
    (outside / "secret.pdf").write_bytes(b"%PDF secret")
    folder = tmp_path / "Data" / "035300"
    shutil.rmtree(folder)
    folder.symlink_to(outside, target_is_directory=True)

    assert client.get("/api/emails/035300/html").status_code == 404
    assert client.get("/api/emails/035300/files/secret.pdf").status_code == 404


def test_noscript_content_is_kept_and_cleaned():
    html = make_safe('<noscript><p>Read</p><img src="https://x.com/p.gif"></noscript>')
    assert "<p>Read</p>" in html and 'data-blocked-src="https://x.com/p.gif"' in html


def test_remote_srcset_candidates_count_and_never_replace_a_saved_image():
    img = '<img src="/filestore/x/inline/a.png" srcset="https://bank.com/a.png 2x">'
    assert remote_images(img) == 1
    html = make_safe(img, files_url="/api/emails/035300/files/")
    assert "srcset" not in html and 'src="/api/emails/035300/files/inline/a.png"' in html
