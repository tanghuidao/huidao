"""Web scraping service using Playwright and BeautifulSoup."""
import hashlib
import datetime
import logging
import asyncio
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models import Source, Article
from app.config import WEB_SCRAPE_TIMEOUT, PLAYWRIGHT_HEADLESS, MAX_ARTICLES_PER_FEED

logger = logging.getLogger(__name__)

# Selectors for known sites (customizable)
SITE_SELECTORS = {
    "coindesk.com": {
        "article_list": "a[class*='card']",
        "title": "h1, h2, h3",
        "content": "article, .article-body, .at-body",
        "date": "time",
    },
    "theblock.co": {
        "article_list": "a[class*='article']",
        "title": "h1, h2",
        "content": ".article-body, .articleBody",
        "date": "time",
    },
    "default": {
        "article_list": "article a, .post a, .entry a, a[href*='/20']",
        "title": "h1, h2, .title, .headline",
        "content": "article, .content, .post-content, .entry-content, main",
        "date": "time, .date, .published, [datetime]",
    },
}


def get_selectors_for_url(url: str) -> dict:
    """Get appropriate selectors for a URL."""
    for domain, selectors in SITE_SELECTORS.items():
        if domain in url:
            return selectors
    return SITE_SELECTORS["default"]


def compute_content_hash(title: str, url: str) -> str:
    """Generate a hash for deduplication."""
    content = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(content.encode()).hexdigest()


async def scrape_with_httpx(url: str) -> Optional[str]:
    """Lightweight scraping with httpx + BeautifulSoup (no JS rendering)."""
    try:
        async with httpx.AsyncClient(
            timeout=WEB_SCRAPE_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
    except Exception as e:
        logger.error(f"httpx scrape failed for {url}: {e}")
        return None


async def scrape_with_playwright(url: str) -> Optional[str]:
    """Full JS-rendered scraping with Playwright."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
            page = await browser.new_page()
            page.set_default_timeout(WEB_SCRAPE_TIMEOUT * 1000)

            await page.goto(url, wait_until="networkidle")
            # Wait a bit more for dynamic content
            await asyncio.sleep(2)
            content = await page.content()
            await browser.close()
            return content

    except ImportError:
        logger.warning("Playwright not installed. Falling back to httpx.")
        return await scrape_with_httpx(url)
    except Exception as e:
        logger.error(f"Playwright scrape failed for {url}: {e}")
        return None


def extract_articles_from_html(html: str, base_url: str, selectors: dict) -> list[dict]:
    """Extract article data from HTML using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")
    articles = []

    # Try to find article links
    links = soup.select(selectors.get("article_list", "a"))

    seen_urls = set()
    for link in links[:MAX_ARTICLES_PER_FEED]:
        href = link.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue

        # Resolve relative URLs
        if href.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        elif not href.startswith("http"):
            href = f"{base_url.rstrip('/')}/{href}"

        if href in seen_urls:
            continue
        seen_urls.add(href)

        # Extract title
        title_el = link.select_one(selectors.get("title", "h2, h3"))
        if not title_el:
            title = link.get_text(strip=True)[:200]
        else:
            title = title_el.get_text(strip=True)

        if not title or len(title) < 10:
            continue

        articles.append({
            "title": title,
            "url": href,
            "content": "",
        })

    return articles


def extract_single_page_content(html: str, selectors: dict) -> dict:
    """Extract content from a single article page."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove scripts, styles, nav, footer
    for tag in soup.select("script, style, nav, footer, header, .sidebar, .ad, .advertisement"):
        tag.decompose()

    # Title
    title_el = soup.select_one(selectors.get("title", "h1"))
    title = title_el.get_text(strip=True) if title_el else ""

    # Content
    content_el = soup.select_one(selectors.get("content", "article"))
    if content_el:
        content = content_el.get_text(separator="\n", strip=True)
    else:
        # Fallback: get body text
        body = soup.find("body")
        content = body.get_text(separator="\n", strip=True) if body else ""

    # Date
    date_el = soup.select_one(selectors.get("date", "time"))
    published_at = None
    if date_el:
        datetime_attr = date_el.get("datetime", "")
        if datetime_attr:
            try:
                published_at = datetime.datetime.fromisoformat(datetime_attr.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

    # Author
    author_el = soup.select_one("[rel='author'], .author, .byline")
    author = author_el.get_text(strip=True) if author_el else None

    return {
        "title": title,
        "content": content[:10000],  # Limit content size
        "published_at": published_at,
        "author": author,
    }


async def scrape_source(source: Source, db: Session) -> dict:
    """Scrape articles from a web source."""
    result = {"source_name": source.name, "new_articles": 0, "errors": []}

    selectors = get_selectors_for_url(source.url)

    # Step 1: Get listing page
    html = await scrape_with_httpx(source.url)
    if not html:
        # Try Playwright for JS-rendered sites
        html = await scrape_with_playwright(source.url)

    if not html:
        source.health_status = "error"
        result["errors"].append(f"Failed to scrape: {source.url}")
        db.commit()
        return result

    # Step 2: Extract article links
    articles_data = extract_articles_from_html(html, source.url, selectors)

    if not articles_data:
        source.health_status = "degraded"
        result["errors"].append("No articles found on page")
        db.commit()
        return result

    # Step 3: Process each article
    for article_data in articles_data[:20]:  # Limit per run
        try:
            title = article_data["title"]
            url = article_data["url"]

            # Deduplication
            content_hash = compute_content_hash(title, url)
            existing = db.query(Article).filter(Article.content_hash == content_hash).first()
            if existing:
                continue

            # Optional: fetch full article content
            content = article_data.get("content", "")
            published_at = None
            author = None

            # For important sources, fetch full page
            if source.credibility_score >= 0.8:
                try:
                    page_html = await scrape_with_httpx(url)
                    if page_html:
                        page_data = extract_single_page_content(page_html, selectors)
                        content = page_data["content"] or content
                        published_at = page_data["published_at"]
                        author = page_data["author"]
                except Exception as e:
                    logger.debug(f"Could not fetch full article {url}: {e}")

            article = Article(
                source_id=source.id,
                title=title,
                url=url,
                author=author,
                published_at=published_at or datetime.datetime.utcnow(),
                raw_content=content,
                language="en",
                content_hash=content_hash,
            )
            db.add(article)
            result["new_articles"] += 1

        except Exception as e:
            result["errors"].append(f"Error processing: {e}")
            logger.error(f"Scrape article error: {e}")

    source.last_checked_at = datetime.datetime.utcnow()
    source.health_status = "healthy" if not result["errors"] else "degraded"
    db.commit()

    return result
