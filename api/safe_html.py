"""make an email's HTML safe to show in the dashboard

every exported email carries an injected <script>, and many load tracking images from the
banks' servers, which tell the bank who opened the email and when. this removes anything that
can run, blocks remote images unless asked for, opens links in a new tab, and puts back the
characters the export lost (see pipeline/repair_text.py)
"""

from bs4 import BeautifulSoup, NavigableString

from pipeline.repair_text import R, repair

# tags that can run code, load other pages or send data somewhere
# <noscript> stays: scripts never run in the sandbox, so browsers show its content
REMOVED_TAGS = ["script", "iframe", "frame", "object", "embed", "form", "base", "link"]


REMOTE = ("http://", "https://", "//")


def _is_remote(img) -> bool:
    """from an outside server, through src or any srcset candidate"""
    candidates = [img.get("src", ""), *img.get("srcset", "").split(",")]
    return any(c.strip().lower().startswith(REMOTE) for c in candidates)


def remote_images(html: str) -> int:
    """how many images would be fetched from outside servers, so the dashboard can say so"""
    soup = BeautifulSoup(html, "lxml")
    return sum(1 for img in soup.find_all("img") if _is_remote(img))


def make_safe(html: str, allow_images: bool = False, files_url: str | None = None) -> str:
    """`files_url` is where the email's own files are served; the export points the images it
    saved in `inline/` at "/filestore/market_research/<id>/inline/<name>", a path that only
    existed on the bank's mail archive"""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(REMOVED_TAGS):
        tag.decompose()
    # the outdated encoding labels (138 emails say windows-1252 although the text is UTF-8) and
    # refresh redirects; the response states its real encoding instead
    for meta in soup.find_all("meta"):
        if meta.get("charset") or meta.get("http-equiv"):
            meta.decompose()

    for tag in soup.find_all(True):
        for attr in [a for a in tag.attrs if a.lower().startswith("on")]:
            del tag[attr]  # onclick, onload, onerror...
        if tag.name == "a" and tag.get("href"):
            if tag["href"].strip().lower().startswith(("javascript:", "data:")):
                del tag["href"]
            else:
                tag["target"] = "_blank"
                tag["rel"] = "noopener noreferrer"
        src = tag.get("src", "") if tag.name == "img" else ""
        if "/inline/" in src and not src.lower().startswith(REMOTE):
            # saved with the email, so it reveals nothing to the bank and always loads
            name = src.rsplit("/inline/", 1)[1]
            if files_url:
                tag["src"] = f"{files_url}inline/{name}"
            else:
                del tag["src"]
            if not allow_images:
                tag.attrs.pop("srcset", None)  # a remote candidate would win and be blocked
        elif tag.name == "img" and not allow_images:
            if src.lower().startswith(REMOTE):
                del tag["src"]
            tag.attrs.pop("srcset", None)

    for text in soup.find_all(string=lambda s: R in s):
        if type(text) is NavigableString:  # not comments or doctypes
            text.replace_with(repair(str(text)))
    for tag in soup.find_all(attrs={"alt": True}) + soup.find_all(attrs={"title": True}):
        for attr in ("alt", "title"):
            if isinstance(tag.get(attr), str):
                tag[attr] = repair(tag[attr])

    head = soup.head or soup.new_tag("head")
    if soup.head is None and soup.html:
        soup.html.insert(0, head)
    head.insert(0, soup.new_tag("meta", charset="utf-8"))
    return str(soup)


def content_security_policy(allow_images: bool) -> str:
    """a second line of defence: the browser itself refuses scripts and, unless allowed, remote
    images (including CSS backgrounds), whatever survived the cleaning above"""
    # 'self' is this API, which serves only the email's own saved images
    images = "'self' data: https:" if allow_images else "'self' data:"
    return (
        "default-src 'none'; "
        "style-src 'unsafe-inline'; "
        f"img-src {images}; "
        "font-src data:; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "sandbox allow-popups allow-popups-to-escape-sandbox"
    )
