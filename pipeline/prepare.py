"""turn raw email folders into clean text for the LLM"""

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Comment

DROP_TAGS = ["script", "style", "head", "title", "meta", "noscript"]
BLOCK_TAGS = [
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer",
]  # fmt: skip
CELL_TAGS = ["td", "th"]

# preheaders pad with these so mail clients show a clean preview line
INVISIBLE_CHARS = re.compile(r"[\u200b-\u200d\u034f\u00ad\ufeff]")
HIDDEN_STYLE = re.compile(r"display\s*:\s*none", re.I)


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(DROP_TAGS):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    # the LLM should read what a person sees, not hidden preheaders or alternate layouts
    for tag in soup.find_all(style=HIDDEN_STYLE):
        tag.decompose()

    # alt text carries the bank's logo name; images without it are tracking pixels and spacers
    for img in soup.find_all("img"):
        alt = img.get("alt", "").strip()
        img.replace_with(f" [image: {alt}] " if alt else "")

    # the HTML source is hard wrapped, so its own newlines are not paragraph breaks
    for s in soup.find_all(string=True):
        s.replace_with(re.sub(r"\s+", " ", s))

    # Outlook wraps every cell in <p>; flatten cells of data rows so each row stays one line.
    # rows holding a nested table are layout, not data, and keep their structure
    for row in soup.find_all("tr"):
        cells = row.find_all(CELL_TAGS, recursive=False)
        if len(cells) > 1 and not row.find("table"):
            for cell in cells:
                cell.string = " ".join(cell.get_text(" ").split())

    # separators go in place so nested layout tables are not printed twice
    for cell in soup.find_all(CELL_TAGS):
        cell.insert_after(" | ")
    for block in soup.find_all(BLOCK_TAGS):
        block.insert_before("\n")
        block.insert_after("\n")

    lines = []
    for line in INVISIBLE_CHARS.sub("", soup.get_text()).splitlines():
        line = re.sub(r"\s+", " ", line)
        line = re.sub(r"(\s*\|\s*)+", " | ", line).strip(" |")
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return "\n".join(lines)


MIMECAST_BANNER = (
    "This Message contains suspicious characteristics and has originated outside your "
    "organization. Please check your email in Mimecast Hold queue before releasing."
)


def strip_banner(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if line != MIMECAST_BANNER)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif"}


@dataclass
class Attachments:
    pdfs: list[str]
    images: list[str]
    thumbnails: dict[str, str]


def list_files(folder: Path) -> Attachments:
    pdfs = sorted(p.name for p in folder.iterdir() if p.suffix.lower() == ".pdf")
    images = sorted(
        str(p.relative_to(folder))
        for p in [*folder.iterdir(), *folder.glob("inline/*")]
        if p.suffix.lower() in IMAGE_SUFFIXES
    )
    thumbnails = {
        pdf: f"thumbs/{pdf}.png" for pdf in pdfs if (folder / "thumbs" / f"{pdf}.png").exists()
    }
    return Attachments(pdfs, images, thumbnails)


# canonical name -> how it appears in logos, headers and signatures
BANKS = {
    "Deutsche Bank": r"Deutsche Bank",
    "Barclays": r"Barclays",
    "Goldman Sachs": r"Goldman Sachs",
    "Morgan Stanley": r"Morgan Stanley",
    "J.P. Morgan": r"J\.\s?P\.\s?Morgan|JP\s?Morgan",
    "UBS": r"UBS",
    "Julius Baer": r"Julius B\S{1,2}r",
    # some exports damaged the accent, so match the start of "Privée"
    "UBP": r"Union Bancaire Priv|UBP",
    "Pictet": r"Pictet",
    "J. Safra Sarasin": r"Safra Sarasin",
    "Macquarie": r"Macquarie",
    "BNP Paribas": r"BNP Paribas",
    "EFG": r"EFG",
    # an asset manager, not a bank, but the publisher is what this field records
    "T. Rowe Price": r"T\. Rowe Price",
}
BANK_PATTERNS = {name: re.compile(rf"\b(?:{p})\b") for name, p in BANKS.items()}


def _earliest_bank(text: str) -> str | None:
    hits = [(m.start(), name) for name, rx in BANK_PATTERNS.items() if (m := rx.search(text))]
    return min(hits)[1] if hits else None


def find_bank(text: str) -> tuple[str | None, str | None]:
    """returns (bank, source), checking the strongest evidence first"""
    lines = text.splitlines()
    regions = [
        ("logo", " ".join(re.findall(r"\[image: ([^\]]+)\]", text))),
        ("top_text", "\n".join(lines[:30])),
        # private banks often only name themselves in the signature
        ("signature", "\n".join(lines[-30:])),
    ]
    for source, region in regions:
        if bank := _earliest_bank(region):
            return bank, source
    return None, None
