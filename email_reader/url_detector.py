# email_reader/url_detector.py
import base64
from collections.abc import Sequence
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass
class ContentResult:
    source: str          # "url" or "body"
    url: str | None
    html: str            # prepared HTML ready for Playwright


def visible_text_length(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    return len(soup.get_text(separator=" ", strip=True))


def is_blocked(url: str, blocklist: Sequence[str]) -> bool:
    return any(blocked in url for blocked in blocklist)


def score_links(html: str, blocklist: Sequence[str]) -> list[tuple[str, str, int]]:
    """Return [(href, anchor_text, score), ...] sorted by score descending."""
    soup = BeautifulSoup(html, "lxml")
    results: list[tuple[str, str, int]] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href.startswith("http"):
            continue
        if is_blocked(href, blocklist):
            continue
        anchor = tag.get_text(strip=True)
        results.append((href, anchor, len(anchor)))
    # Heuristic: longer anchor text is used as a proxy for content relevance.
    # Use the url_blocklist to exclude known non-content links (e.g. unsubscribe).
    return sorted(results, key=lambda x: x[2], reverse=True)


def _detect_image_mime(data: bytes) -> str:
    """Detect image MIME type from magic bytes."""
    if data[:4] == b'\x89PNG':
        return "image/png"
    if data[:2] == b'\xff\xd8':
        return "image/jpeg"
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    return "image/png"


def inline_cid_images(html: str, cid_map: dict[str, bytes]) -> str:
    result = html
    for cid, data in cid_map.items():
        b64 = base64.b64encode(data).decode()
        mime = _detect_image_mime(data)
        data_uri = f"data:{mime};base64,{b64}"
        result = result.replace(f"cid:{cid}", data_uri)
    return result


def wrap_html(body_html: str) -> str:
    return (
        '<!DOCTYPE html>\n'
        '<html><head><meta charset="utf-8">\n'
        '<style>body{font-family:sans-serif;max-width:900px;margin:auto;padding:2rem}</style>\n'
        f'</head><body>{body_html}</body></html>'
    )


def detect_content(
    html: str,
    cid_map: dict[str, bytes],
    url_detection_threshold: int,
    blocklist: Sequence[str],
) -> ContentResult:
    text_len = visible_text_length(html)

    if text_len < url_detection_threshold:
        links = score_links(html, blocklist)
        if links:
            best_url = links[0][0]
            return ContentResult(source="url", url=best_url, html=html)

    inlined = inline_cid_images(html, cid_map)
    wrapped = wrap_html(inlined)
    return ContentResult(source="body", url=None, html=wrapped)
