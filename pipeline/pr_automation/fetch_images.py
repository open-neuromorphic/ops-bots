import re
import ipaddress
import asyncio
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from pydantic import BaseModel
from io import BytesIO
from PIL import Image, UnidentifiedImageError
import aiohttp

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


class SafeSSRFResolver(aiohttp.DefaultResolver):
    """Custom DNS Resolver to prevent SSRF and DNS Rebinding TOCTOU attacks."""

    async def resolve(self, host: str, port: int, family: int) -> list[dict]:
        hosts = await super().resolve(host, port, family)
        safe_hosts = []
        for h in hosts:
            try:
                ip = ipaddress.ip_address(h['host'])
                if not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved):
                    safe_hosts.append(h)
            except ValueError:
                continue

        if not safe_hosts:
            raise OSError(f"SSRF Attempt detected. No public routable IPs resolved for {host}")
        return safe_hosts


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
    all_candidates, next_id = [], 1
    found, next_id = _extract_from_text(issue.body, "issue_body", next_id)
    all_candidates += found
    for i, c in enumerate(issue.comments, start=1):
        found, next_id = _extract_from_text(c.body, f"comment_{i}", next_id)
        all_candidates += found
    return all_candidates


async def download_image(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ImageDownloadError(f"Unsupported scheme: {parsed.scheme}")

    # Enforce safe DNS resolution inside the client session
    connector = aiohttp.TCPConnector(resolver=SafeSSRFResolver())
    timeout = aiohttp.ClientTimeout(total=config.IMAGE_FETCH_TIMEOUT_SECONDS)

    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True, max_redirects=3) as resp:
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
    except OSError as e:
        raise ImageDownloadError(f"Security block during fetch: {e}")


def verify_image_bytes(data: bytes) -> None:
    try:
        Image.open(BytesIO(data)).verify()
    except (UnidentifiedImageError, ValueError, OSError) as e:
        raise ImageDownloadError(f"Downloaded content is not a valid image: {e}")