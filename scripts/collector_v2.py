"""RSS content collector service (with quality filtering)."""
import hashlib
import datetime
import logging
import re
from typing import Optional

import feedparser
import httpx
from sqlalchemy.orm import Session

from app.models import Source, Article
from app.config import FETCH_TIMEOUT, MAX_ARTICLES_PER_FEED

logger = logging.getLogger(__name__)

# Quality thresholds
MIN_CONTENT_LENGTH = 50       # Minimum raw_content chars to accept
MIN_TITLE_LENGTH = 10         # Minimum title length
MAX_TITLE_LENGTH = 500        # Maximum title length (prevent junk)


def compute_content_hash(title: str, url: str) -> str:
    """Generate a hash for deduplication."""
    content = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(content.encode()).hexdigest()


def strip_html(text: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'&[#0-9a-zA-Z]+;', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def parse_published_date(entry) -> Optional[datetime.datetime]:
    """Extract published date from feed entry."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime.datetime(*parsed[:6])
            except (TypeError, ValueError):
                continue
    return None


def extract_content(entry) -> str:
    """Extract text content from feed entry."""
    raw = ""
    # Try content field first
    if hasattr(entry, "content") and entry.content:
        raw = entry.content[0].get("value", "")
    # Fall back to summary
    elif hasattr(entry, "summary"):
        raw = entry.summary or ""
    # Fall back to description
    elif hasattr(entry, "description"):
        raw = entry.description or ""
    # Strip HTML and return clean text
    return strip_html(raw)


def _passes_quality_filter(title: str, content: str) -> bool:
    """Check if an article passes minimum quality requirements."""
    if not title or len(title.strip()) < MIN_TITLE_LENGTH:
        return False
    if len(title) > MAX_TITLE_LENGTH:
        return False
    # Allow articles with empty content if title is informative enough
    # (some RSS feeds only have titles, like Bloomberg)
    # But require at least some content for quality
    clean_content = content.strip() if content else ""
    if len(clean_content) < MIN_CONTENT_LENGTH:
        return False
    return True


async def fetch_feed(url: str) -> Optional[feedparser.FeedParserDict]:
    """Fetch and parse an RSS feed with browser-like headers."""
    import warnings
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except ImportError:
        pass
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate",
    }
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            verify=False,
        ) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            text = response.text
            if not text or len(text) < 50:
                logger.warning(f"Empty or too-short response from {url}")
                return None
            return feedparser.parse(text)
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code} fetching {url}")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch feed {url}: {e}")
        return None


async def collect_source(source: Source, db: Session) -> dict:
    """Collect articles from a single source. Returns stats."""
    result = {"source_name": source.name, "new_articles": 0, "skipped_quality": 0, "errors": []}

    feed = await fetch_feed(source.url)
    if feed is None:
        source.health_status = "error"
        result["errors"].append(f"Failed to fetch: {source.url}")
        db.commit()
        return result

    if feed.bozo and not feed.entries:
        source.health_status = "degraded"
        result["errors"].append(f"Feed parse warning: {feed.bozo_exception}")
        db.commit()
        return result

    entries = feed.entries[:MAX_ARTICLES_PER_FEED]

    for entry in entries:
        try:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()

            if not title or not link:
                continue

            # Extract and clean content
            raw_content = extract_content(entry)

            # Quality filter
            if not _passes_quality_filter(title, raw_content):
                result["skipped_quality"] += 1
                continue

            # Deduplication
            content_hash = compute_content_hash(title, link)
            existing = db.query(Article).filter(
                Article.content_hash == content_hash
            ).first()
            if existing:
                continue

            # Create article
            article = Article(
                source_id=source.id,
                title=title,
                url=link,
                author=entry.get("author", None),
                published_at=parse_published_date(entry),
                raw_content=raw_content,
                language="en",  # Default, can be detected later
                content_hash=content_hash,
            )
            db.add(article)
            result["new_articles"] += 1

        except Exception as e:
            result["errors"].append(f"Error processing entry: {e}")
            logger.error(f"Error processing entry from {source.name}: {e}")

    # Update source status
    source.last_checked_at = datetime.datetime.utcnow()
    source.health_status = "healthy" if not result["errors"] else "degraded"
    db.commit()

    return result


async def collect_all(db: Session, source_ids: list[int] = None) -> list[dict]:
    """Collect from all enabled sources or specified sources."""
    query = db.query(Source).filter(Source.enabled == True)
    if source_ids:
        query = query.filter(Source.id.in_(source_ids))

    sources = query.all()
    results = []

    for source in sources:
        if source.source_type != "rss":
            continue  # MVP only supports RSS
        try:
            result = await collect_source(source, db)
            results.append(result)
        except Exception as e:
            results.append({
                "source_name": source.name,
                "new_articles": 0,
                "errors": [str(e)],
            })
            logger.error(f"Collection error for {source.name}: {e}")

    return results
