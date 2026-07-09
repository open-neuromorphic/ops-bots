import re
import socket
import ipaddress
import asyncio
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from pydantic import BaseModel
from io import BytesIO
from PIL import Image, UnidentifiedImageError
import aiohttp

from services.http import get_session
import config

MD_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\((https?://[^\s)]+)\)')
RAW_URL_RE = re.compile(r'(https?://\S+\.(?:png|jpe?g|gif|webp)(?:\?\S*)?)', re.IGNORECASE)


class ImageCandidate(BaseModel):
    candidate_id: str
    url: str
    alt_text: str | None = None
    source_location: str
    surrounding_text: str = ""


class ImageDownloadError(Exception):
    pass


def _extract_from_text(text: str, source_location: str, next_id: int) -> tuple[list[ImageCandidate], int]:
    candidates, seen = [], set()

    for m in MD_IMAGE_RE.finditer(text):
        alt, url = m.group(1), m.group(2)
        if url in seen:
            continue
        seen.add(url)
        candidates.append(ImageCandidate(
            candidate_id=f"img_{next_id}", url=url, alt_text=alt or None,
            source_location=source_location,
            surrounding_text=text[max(0, m.start() - 80):m.start()].strip()
        ))
        next_id += 1

    for img in BeautifulSoup(text, "html.parser").find_all("img"):
        url = img.get("src")
        if not url or url in seen:
            continue
        seen.add(url)
        candidates.append(ImageCandidate(
            candidate_id=f"img_{next_id}", url=url, alt_text=img.get("alt"),
            source_location=source_location, surrounding_text=""
        ))
        next_id += 1

    for m in RAW_URL_RE.finditer(text):
        url = m.group(1)
        if url in seen:
            continue
        seen.add(url)
        candidates.append(ImageCandidate(
            candidate_id=f"img_{next_id}", url=url, alt_text=None,
            source_location=source_location,
            surrounding_text=text[max(0, m.start() - 80):m.start()].strip()
        ))
        next_id += 1

    return candidates, next_id


def extract_image_candidates(issue) -> list[ImageCandidate]:
    """Extracts candidate image URLs from an IssueContext body and its comments."""
    all_candidates, next_id = [], 1
    found, next_id = _extract_from_text(issue.body, "issue_body", next_id)
    all_candidates += found
    for i, c in enumerate(issue.comments, start=1):
        found, next_id = _extract_from_text(c.body, f"comment_{i}", next_id)
        all_candidates += found
    return all_candidates


async def _is_safe_host(hostname: str) -> bool:
    """SSRF guard: reject hosts resolving to private/loopback/link-local ranges."""

    def _resolve():
        try:
            return socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return None

    infos = await asyncio.to_thread(_resolve)
    if not infos:
        return False

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
    return True


async def download_image(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ImageDownloadError(f"Unsupported scheme: {parsed.scheme}")

    is_safe = await _is_safe_host(parsed.hostname)
    if not parsed.hostname or not is_safe:
        raise ImageDownloadError(f"Refusing to fetch disallowed host: {parsed.hostname}")

    session = await get_session()
    timeout = aiohttp.ClientTimeout(total=config.IMAGE_FETCH_TIMEOUT_SECONDS)
    try:
        async with session.get(url, timeout=timeout, allow_redirects=True, max_redirects=3) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type not in config.ALLOWED_LOGO_CONTENT_TYPES_SET:
                raise ImageDownloadError(f"Unexpected content-type: {content_type}")

            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > config.MAX_LOGO_IMAGE_BYTES:
                raise ImageDownloadError(f"Declared size too large: {content_length} bytes")

            chunks = bytearray()
            async for chunk in resp.content.iter_chunked(65536):
                chunks.extend(chunk)
                if len(chunks) > config.MAX_LOGO_IMAGE_BYTES:
                    raise ImageDownloadError("Exceeded size limit while streaming")
            return bytes(chunks), content_type
    except aiohttp.ClientError as e:
        raise ImageDownloadError(f"Network error during fetch: {e}")


def verify_image_bytes(data: bytes) -> None:
    try:
        Image.open(BytesIO(data)).verify()
    except (UnidentifiedImageError, ValueError, OSError) as e:
        raise ImageDownloadError(f"Downloaded content is not a valid image: {e}")