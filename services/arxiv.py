import asyncio
import logging
import urllib.parse
from typing import List, Optional
from bs4 import BeautifulSoup
import config
from services.http import get_session

logger = logging.getLogger(__name__)


async def fetch_arxiv_feed(query: str = None, id_list: str = None, max_results: int = 25) -> List[dict]:
    """Hits the arXiv API and parses the Atom XML to return raw paper metadata dictionaries."""
    session = await get_session()

    # Hard cap to prevent long-running loops or rate-limit abuse
    safe_max_results = min(max_results, 100)

    if id_list:
        url = f"{config.ARXIV_BASE_URL}?id_list={id_list}"
    else:
        encoded_query = urllib.parse.quote(query)
        url = f"{config.ARXIV_BASE_URL}?search_query={encoded_query}&{config.ARXIV_CURRENT_FLAGS}&max_results={safe_max_results}"

    xml_data = None

    # Retry loop specifically for 429 Too Many Requests (ArXiv API limits)
    for attempt in range(3):
        try:
            async with session.get(url) as resp:
                if resp.status == 429:
                    wait_time = 3 * (attempt + 1)
                    logger.warning(f"ArXiv API 429 Too Many Requests. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                resp.raise_for_status()
                xml_data = await resp.text()
                break
        except Exception as e:
            if attempt == 2:
                logger.error(f"Error fetching arXiv feed: {e}")
                return []
            await asyncio.sleep(2)

    if not xml_data:
        return []

    try:
        soup = BeautifulSoup(xml_data, "xml")
        entries = soup.find_all("entry")

        results = []
        for entry in entries:
            arxiv_url = entry.find("id").text.strip() if entry.find("id") else ""

            # STRIP VERSION SUFFIX (v1, v2) TO NORMALIZE IDs AND FIX SPLIT-BRAIN CACHES
            raw_id = arxiv_url.split("/abs/")[-1] if "/abs/" in arxiv_url else arxiv_url
            arxiv_id = raw_id.split("v")[0]

            pdf_link = entry.find("link", title="pdf")
            pdf_url = pdf_link["href"] if pdf_link else None

            authors = [author.find("name").text.strip() for author in entry.find_all("author")]

            results.append({
                "arxiv_id": arxiv_id,
                "title": entry.find("title").text.strip().replace("\n", " "),
                "summary": entry.find("summary").text.strip().replace("\n", " "),
                "authors": authors,
                "published_date": entry.find("published").text.strip(),
                "url": arxiv_url,
                "pdf_url": pdf_url
            })
        return results
    except Exception as e:
        logger.error(f"Error parsing arXiv feed XML: {e}")
        return []


async def scrape_paper_license(arxiv_id: str) -> Optional[str]:
    """Scrapes the abstract page HTML to find the license URI."""
    session = await get_session()
    url = f"https://arxiv.org/abs/{arxiv_id}"

    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            html_data = await resp.text()

        soup = BeautifulSoup(html_data, "lxml")

        # Look for standard a rel="license"
        license_tag = soup.find("a", rel="license")
        if license_tag and license_tag.get("href"):
            return license_tag["href"]

        # Fallback to general license div OR abs-license div
        license_div = soup.find("div", class_="license") or soup.find("div", class_="abs-license")
        if license_div:
            a_tag = license_div.find("a")
            if a_tag and a_tag.get("href"):
                return a_tag["href"]

        return "unknown"
    except Exception as e:
        logger.warning(f"Failed to scrape license for {arxiv_id}: {e}")
        return None


def verify_open_license(license_uri: str) -> bool:
    """Returns True if the license is CC or Public Domain."""
    if not license_uri:
        return False
    uri_lower = license_uri.lower()
    return "creativecommons.org" in uri_lower or "publicdomain" in uri_lower


def format_license_uri(uri: str) -> str:
    """Converts a long license URL into a clean shortcode for Discord embeds."""
    if not uri or uri.lower() == "unknown":
        return "Unknown"

    uri_lower = uri.lower()

    if "creativecommons.org/licenses/" in uri_lower:
        try:
            # Extracts the 'by-nc-nd' part from http://creativecommons.org/licenses/by-nc-nd/4.0/
            code = uri_lower.split("licenses/")[1].split("/")[0]
            return f"CC {code.upper()}"
        except IndexError:
            return "Creative Commons"

    elif "publicdomain/zero" in uri_lower or "cc0" in uri_lower:
        return "CC0 (Public Domain)"

    elif "nonexclusive-distrib" in uri_lower:
        return "arXiv Non-Exclusive"

    return uri