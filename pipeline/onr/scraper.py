import asyncio
import logging
from typing import List

from models.onr import ArxivPaper
from services.state_store import TypedStateStore
from services.arxiv import fetch_arxiv_feed, scrape_paper_license, verify_open_license

logger = logging.getLogger(__name__)

onr_papers_store = TypedStateStore(ArxivPaper, "researchbot/onr_papers")

async def fetch_and_filter_new_papers(
        query: str = None,
        id_list: str = None,
        max_results: int = 50,
        skip_cached: bool = True,
        save_to_cache: bool = True
) -> List[ArxivPaper]:
    raw_papers = await fetch_arxiv_feed(query=query, id_list=id_list, max_results=max_results)
    valid_papers = []

    for raw in raw_papers:
        arxiv_id = raw["arxiv_id"]

        paper = await onr_papers_store.get_async(arxiv_id)
        if paper:
            if skip_cached and not id_list:
                continue

            logger.info(f"Paper {arxiv_id} found in cache. Skipping scrape.")
            if paper.is_open_license:
                valid_papers.append(paper)
            continue

        logger.info(f"Scraping license metadata for arXiv ID: {arxiv_id}...")
        license_uri = await scrape_paper_license(arxiv_id)
        is_open = verify_open_license(license_uri)

        paper = ArxivPaper(
            arxiv_id=arxiv_id, title=raw["title"], summary=raw["summary"], authors=raw["authors"],
            published_date=raw["published_date"], url=raw["url"], pdf_url=raw["pdf_url"],
            license=license_uri or "unknown", is_open_license=is_open, submitted_by="auto"
        )

        if save_to_cache:
            await onr_papers_store.put_async(arxiv_id, paper)

        if is_open:
            logger.info(f"✅ Approved open license ({license_uri}) for {arxiv_id}")
            valid_papers.append(paper)
        else:
            logger.info(f"❌ Dropped paper {arxiv_id} due to closed/missing license: {license_uri}")

        await asyncio.sleep(1)

    return valid_papers