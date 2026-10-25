"""turn raw email folders into clean text for the LLM"""

import hashlib
import html as html_lib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup, Comment
from pypdf import PdfReader
from pypdf.errors import PdfReadError

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
        # the sign-off and legal text name the sender; the top is content and can name other
        # banks ("issued by Goldman Sachs"). it starts after the top 30 lines so they never overlap
        ("signature", "\n".join(lines[max(30, len(lines) - 30) :])),
        ("top_text", "\n".join(lines[:30])),
    ]
    for source, region in regions:
        if bank := _earliest_bank(region):
            return bank, source
    return None, None


MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MONTH = rf"(?:{'|'.join(MONTHS)})[a-z]*\.?"

# ordinal days like "10th April 2026" and "April 7th, 2026" appear in the emails
ORDINAL = r"(?:st|nd|rd|th)?"
# (pattern, group numbers for day, month, year)
TEXT_DATES = [
    # 9 April 2026, 07-Apr-26, 10th April 2026, and "13 Apr, 2026" from Goldman's footers
    (re.compile(rf"\b(\d{{1,2}}){ORDINAL}[ -]({MONTH}),?[ -](\d{{4}}|\d{{2}})\b", re.I), (1, 2, 3)),
    # April 10, 2026 and April 7th, 2026
    (re.compile(rf"\b({MONTH}) (\d{{1,2}}){ORDINAL},? (\d{{4}})\b", re.I), (2, 1, 3)),
    (re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b"), (1, 2, 3)),
]
# slash dates are left out on purpose: 04/10/2026 is ambiguous between US and European order
COMPACT_DATE = (re.compile(r"(?<!\d)(20\d\d)(\d\d)(\d\d)(?!\d)"), (3, 2, 1))
PDF_NAME_DATES = [*TEXT_DATES, COMPACT_DATE]


def _to_date(day: str, month: str, year: str) -> date | None:
    y = int(year) + (2000 if len(year) == 2 else 0)
    m = int(month) if month.isdigit() else MONTHS.index(month[:3].lower()) + 1
    try:
        return date(y, m, int(day))
    except ValueError:
        return None


# file times carry no time zone, so a report dated the day after it arrived is still possible
RECEIVED_MARGIN = timedelta(days=1)
# the largest real gap is 10 days (a price sheet "as of 30 March" arriving on 9 April); older
# dates are charts or history, like 08.04.2024 in a 2026 flyer
RECEIVED_LOOKBACK = timedelta(days=31)


def received_date(folder: Path) -> date | None:
    """when the email arrived, from its attachment and image file times.

    emailbody.html is not used: the export rewrote it, so it carries the export date.
    copying files can reset these times to today, which only makes the check below looser
    """
    stamps = [
        p.stat().st_mtime for p in folder.rglob("*") if p.is_file() and p.name != "emailbody.html"
    ]
    return date.fromtimestamp(min(stamps)) if stamps else None


def could_be_published(found: date, received: date | None) -> bool:
    """a publication date sits just before arrival: deadlines, events and old chart dates fail"""
    if received is None:
        return True
    return received - RECEIVED_LOOKBACK <= found <= received + RECEIVED_MARGIN


def _earliest_date(text: str, patterns: list, received: date | None) -> date | None:
    found = []
    for rx, (d, m, y) in patterns:
        for match in rx.finditer(text):
            parsed = _to_date(match[d], match[m], match[y])
            if parsed and could_be_published(parsed, received):
                found.append((match.start(), parsed))
    return min(found)[1] if found else None


def find_date_hint(html: str, received: date | None) -> date | None:
    """a date inferred from link addresses, such as a campaign code ending _20260413. it is a
    send date at best, not one the email states, so it is kept apart from the date field"""
    hrefs = " ".join(html_lib.unescape(h) for h in re.findall(r'href="([^"]+)"', html, re.I))
    return _earliest_date(hrefs, [COMPACT_DATE], received)


def find_date(
    text: str, pdf_names: list[str], received: date | None = None
) -> tuple[date | None, str | None]:
    """returns (date, source); the publication date sits near the top when it is present"""
    if found := _earliest_date("\n".join(text.splitlines()[:25]), TEXT_DATES, received):
        return found, "text"
    for name in pdf_names:
        if found := _earliest_date(name, PDF_NAME_DATES, received):
            return found, "pdf_name"
    return None, None


PDF_BUDGET_CHARS = 6000
# after page 1, pages this short are contents pages, dividers or image only slides
MIN_PAGE_CHARS = 200


def read_pdf_pages(path: Path) -> list[str]:
    """raises pypdf.errors.PdfReadError on a broken file; the caller records it"""
    return [page.extract_text() or "" for page in PdfReader(path).pages]


def select_pages(pages: list[str], budget: int) -> str:
    kept, used = [], 0
    for i, page in enumerate(pages):
        page = "\n".join(" ".join(line.split()) for line in page.splitlines() if line.strip())
        # a short first page is the title page: it often names the report and its date
        if not page or (i > 0 and len(page) < MIN_PAGE_CHARS):
            continue
        if used + len(page) > budget:
            kept.append(page[: budget - used] + " [truncated]")
            break
        kept.append(page)
        used += len(page)
    return "\n\n".join(kept)


def build_llm_input(body: str, pdfs: list[str], pdf_texts: dict[str, str]) -> str:
    """fixed section headings so the prompt can refer to each part by name"""
    parts = [f"EMAIL BODY:\n{body}", f"ATTACHMENTS: {', '.join(pdfs) or 'none'}"]
    # a PDF that could not be read is still listed above, it just has no text section
    parts += [f"PDF TEXT ({name}):\n{text}" for name, text in pdf_texts.items() if text]
    return "\n\n".join(parts)


def find_duplicates(texts: dict[str, str]) -> dict[str, str]:
    """maps each repeated email to the first one with the same text, in id order"""
    first_seen: dict[str, str] = {}
    duplicates = {}
    for email_id in sorted(texts):
        digest = hashlib.sha256(" ".join(texts[email_id].split()).encode()).hexdigest()
        if digest in first_seen:
            duplicates[email_id] = first_seen[digest]
        else:
            first_seen[digest] = email_id
    return duplicates


@dataclass
class PreparedEmail:
    id: str
    body: str
    llm_input: str
    attachments: Attachments
    bank: str | None
    bank_source: str | None
    date: date | None
    date_source: str | None
    received: date | None
    encoding: str
    # only set when the email states no date (see find_date_hint)
    date_hint: date | None = None
    duplicate_of: str | None = None
    warnings: list[str] = field(default_factory=list)


def read_html(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        # one export (035432) declares no charset and is Windows-1252
        return raw.decode("cp1252"), "cp1252"


def prepare_email(folder: Path) -> PreparedEmail:
    html, encoding = read_html(folder / "emailbody.html")
    body = strip_banner(clean_html(html))
    files = list_files(folder)

    warnings, pdf_texts = [], {}
    share = PDF_BUDGET_CHARS // max(len(files.pdfs), 1)
    for name in files.pdfs:
        try:
            pdf_texts[name] = select_pages(read_pdf_pages(folder / name), share)
        except PdfReadError as e:
            warnings.append(f"could not read {name}: {e}")

    bank, bank_source = find_bank(body)
    received = received_date(folder)
    found_date, date_source = find_date(body, files.pdfs, received)
    return PreparedEmail(
        id=folder.name,
        body=body,
        llm_input=build_llm_input(body, files.pdfs, pdf_texts),
        attachments=files,
        bank=bank,
        bank_source=bank_source,
        date=found_date,
        date_source=date_source,
        received=received,
        encoding=encoding,
        date_hint=None if found_date else find_date_hint(html, received),
        warnings=warnings,
    )


def prepare_all(data_dir: Path) -> tuple[list[PreparedEmail], dict[str, str]]:
    """one folder failing never stops the rest; failures are returned by folder id"""
    emails, failures = [], {}
    for folder in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        try:
            emails.append(prepare_email(folder))
        except (OSError, UnicodeDecodeError) as e:
            failures[folder.name] = f"{type(e).__name__}: {e}"

    duplicates = find_duplicates({e.id: e.body for e in emails})
    for email in emails:
        email.duplicate_of = duplicates.get(email.id)
    return emails, failures
