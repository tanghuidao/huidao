"""Auto-discover new information sources from existing content."""
import re
import logging
from collections import Counter
from urllib.parse import urlparse
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Article, Source, DiscoveredSource

logger = logging.getLogger(__name__)

# Domains to skip (social media, generic sites)
SKIP_DOMAINS = {
    "twitter.com", "x.com", "facebook.com", "instagram.com", "youtube.com",
    "reddit.com", "linkedin.com", "t.me", "telegram.org", "discord.com",
    "google.com", "github.com", "medium.com", "substack.com",
    "wikipedia.org", "arxiv.org", "bit.ly", "t.co",
}

# Domain categories mapping
DOMAIN_CATEGORIES = {
    "coindesk.com": "crypto_media", "theblock.co": "crypto_media",
    "decrypt.co": "crypto_media", "cointelegraph.com": "crypto_media",
    "messari.io": "institution", "a16zcrypto.com": "institution",
    "reuters.com": "mainstream_media", "bloomberg.com": "mainstream_media",
    "ft.com": "mainstream_media", "wsj.com": "mainstream_media",
    "techcrunch.com": "mainstream_media", "venturebeat.com": "ai_media",
    "sec.gov": "regulation", "europa.eu": "regulation",
}

# Keywords that indicate relevant sources
RELEVANCE_KEYWORDS = [
    "crypto", "blockchain", "web3", "defi", "nft", "ai", "artificial intelligence",
    "machine learning", "decentralized", "token", "bitcoin", "ethereum",
    "regulation", "fintech", "digital asset", "smart contract",
]


def extract_urls_from_content(content: str) -> list[str]:
    """Extract all URLs from article content."""
    url_pattern = re.compile(
        r'https?://[^\s<>"\')\]},;]+',
        re.IGNORECASE
    )
    urls = url_pattern.findall(content)
    # Clean trailing punctuation
    cleaned = []
    for url in urls:
        url = url.rstrip('.,;:!?)]\'"')
        if len(url) > 20:
            cleaned.append(url)
    return cleaned


def get_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def guess_source_category(domain: str, url: str) -> str:
    """Guess the category of a source from its domain."""
    if domain in DOMAIN_CATEGORIES:
        return DOMAIN_CATEGORIES[domain]

    # Keyword-based guessing
    url_lower = url.lower()
    if any(kw in url_lower for kw in ["crypto", "coin", "token", "defi", "web3"]):
        return "crypto_media"
    if any(kw in url_lower for kw in ["ai", "ml", "intelligence", "deeplearn"]):
        return "ai_media"
    if any(kw in url_lower for kw in ["research", "report", "insight"]):
        return "institution"
    if any(kw in url_lower for kw in ["gov", "sec.", "regulation"]):
        return "regulation"

    return "unknown"


def calculate_relevance(domain: str, url: str, mention_count: int) -> float:
    """Calculate relevance score for a discovered source."""
    score = 0.3  # Base

    # Known relevant domains get a boost
    if domain in DOMAIN_CATEGORIES:
        score += 0.3

    # Keyword relevance
    url_lower = url.lower()
    keyword_matches = sum(1 for kw in RELEVANCE_KEYWORDS if kw in url_lower)
    score += min(keyword_matches * 0.1, 0.3)

    # Mention frequency boost
    if mention_count >= 5:
        score += 0.2
    elif mention_count >= 3:
        score += 0.1

    return min(score, 1.0)


def discover_from_articles(db: Session, limit: int = 200) -> list[dict]:
    """Discover new sources by analyzing URLs in existing articles."""
    # Get recent articles with content
    articles = db.query(Article).filter(
        Article.raw_content.isnot(None)
    ).order_by(Article.fetched_at.desc()).limit(limit).all()

    # Extract and count all external URLs
    url_counter = Counter()
    url_sources = {}  # url -> first article that referenced it

    existing_source_domains = {
        get_domain(s.url) for s in db.query(Source).all()
    }
    existing_discovered = {
        d.url for d in db.query(DiscoveredSource).all()
    }

    for article in articles:
        if not article.raw_content:
            continue
        urls = extract_urls_from_content(article.raw_content)
        for url in urls:
            domain = get_domain(url)
            if not domain or domain in SKIP_DOMAINS:
                continue
            if domain in existing_source_domains:
                continue

            # Normalize to domain-level for counting
            base_url = f"https://{domain}"
            url_counter[base_url] += 1
            if base_url not in url_sources:
                url_sources[base_url] = article.source.name if article.source else "unknown"

    # Filter and score
    discovered = []
    for url, count in url_counter.most_common(50):
        if url in existing_discovered:
            continue
        if count < 2:  # Require at least 2 mentions
            continue

        domain = get_domain(url)
        category = guess_source_category(domain, url)
        relevance = calculate_relevance(domain, url, count)

        if relevance < 0.3:
            continue

        # Save to DB
        new_source = DiscoveredSource(
            url=url,
            name=domain,
            discovered_from=url_sources.get(url, "unknown"),
            category_guess=category,
            relevance_score=round(relevance, 2),
            status="pending",
            extra_data={"mention_count": count},
        )
        db.add(new_source)
        discovered.append({
            "url": url,
            "domain": domain,
            "category": category,
            "relevance": round(relevance, 2),
            "mentions": count,
            "discovered_from": url_sources.get(url, "unknown"),
        })

    db.commit()
    logger.info(f"Discovered {len(discovered)} potential new sources")
    return discovered


def approve_discovered_source(db: Session, discovered_id: int) -> Optional[Source]:
    """Approve a discovered source and add it to the main source list."""
    discovered = db.query(DiscoveredSource).filter(
        DiscoveredSource.id == discovered_id
    ).first()

    if not discovered:
        return None

    # Check if already exists
    existing = db.query(Source).filter(Source.url == discovered.url).first()
    if existing:
        discovered.status = "added"
        db.commit()
        return existing

    # Create new source
    source = Source(
        name=discovered.name or get_domain(discovered.url),
        category=discovered.category_guess or "unknown",
        region="global",
        credibility_score=0.5,  # Start with neutral credibility
        url=discovered.url,
        source_type="web",  # Default to web scraping
        enabled=True,
    )
    db.add(source)
    discovered.status = "added"
    db.commit()
    db.refresh(source)
    return source


def reject_discovered_source(db: Session, discovered_id: int) -> bool:
    """Reject a discovered source."""
    discovered = db.query(DiscoveredSource).filter(
        DiscoveredSource.id == discovered_id
    ).first()
    if discovered:
        discovered.status = "rejected"
        db.commit()
        return True
    return False


def get_pending_discoveries(db: Session, limit: int = 30) -> list:
    """Get pending discovered sources for review."""
    return db.query(DiscoveredSource).filter(
        DiscoveredSource.status == "pending"
    ).order_by(DiscoveredSource.relevance_score.desc()).limit(limit).all()
