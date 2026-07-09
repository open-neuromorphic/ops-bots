import pytest
import asyncio
from pipeline.pr_automation.fetch_images import _extract_from_text, _is_safe_host, extract_image_candidates
from pipeline.pr_automation.fetch_issue import IssueContext


def test_extract_markdown_syntax():
    text = "Here is an image: ![Alt text](https://example.com/logo.png)"
    candidates, _ = _extract_from_text(text, "issue_body", 1)

    assert len(candidates) == 1
    assert candidates[0].url == "https://example.com/logo.png"
    assert candidates[0].alt_text == "Alt text"
    assert "Here is an image:" in candidates[0].surrounding_text


def test_extract_html_img_tag():
    text = '<img src="https://example.com/logo.jpg" alt="test" width="200">'
    candidates, _ = _extract_from_text(text, "issue_body", 1)

    assert len(candidates) == 1
    assert candidates[0].url == "https://example.com/logo.jpg"
    assert candidates[0].alt_text == "test"


def test_extract_bare_url():
    text = "Check this out https://example.com/logo.webp?size=large"
    candidates, _ = _extract_from_text(text, "issue_body", 1)

    assert len(candidates) == 1
    assert candidates[0].url == "https://example.com/logo.webp?size=large"
    assert "Check this out" in candidates[0].surrounding_text


def test_deduplication():
    text = """
    ![alt](https://example.com/logo.png)
    <img src="https://example.com/logo.png">
    https://example.com/logo.png
    """
    candidates, _ = _extract_from_text(text, "issue_body", 1)
    assert len(candidates) == 1


def test_is_safe_host():
    # Wrap the async calls in asyncio.run() so standard pytest can execute them natively

    # External valid hosts
    assert asyncio.run(_is_safe_host("github.com")) == True
    assert asyncio.run(_is_safe_host("google.com")) == True

    # Internal / SSRF risk hosts
    assert asyncio.run(_is_safe_host("localhost")) == False
    assert asyncio.run(_is_safe_host("127.0.0.1")) == False
    assert asyncio.run(_is_safe_host("10.0.0.5")) == False
    assert asyncio.run(_is_safe_host("192.168.1.1")) == False