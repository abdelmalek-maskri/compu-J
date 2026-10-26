"""make an email's HTML safe to show in the dashboard

every exported email carries an injected <script>, and many load tracking images from the
banks' servers, which tell the bank who opened the email and when. this removes anything that
can run, blocks remote images unless asked for, and opens links in a new tab
"""

from bs4 import BeautifulSoup

# tags that can run code, load other pages or send data somewhere
REMOVED_TAGS = ["script", "noscript", "iframe", "frame", "object", "embed", "form", "base", "link"]


REMOTE = ("http://", "https://", "//")


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
        elif tag.name == "img" and not allow_images:
            if src.lower().startswith(REMOTE):
                # kept aside, so the dashboard can say an image was blocked
                tag["data-blocked-src"] = src
                del tag["src"]
            tag.attrs.pop("srcset", None)

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
