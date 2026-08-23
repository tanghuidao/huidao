"""Personalized watchlist service."""
import datetime
import logging
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc

from app.models import Article, Classification, Watchlist

logger = logging.getLogger(__name__)


def create_watchlist_item(
    db: Session,
    name: str,
    watch_type: str,
    watch_value: str,
    description: str = None,
    notify_on_match: bool = True,
    min_score: float = 0.0,
) -> Watchlist:
    """Create a new watchlist item."""
    item = Watchlist(
        name=name,
        description=description,
        watch_type=watch_type,
        watch_value=watch_value,
        notify_on_match=notify_on_match,
        min_score=min_score,
        enabled=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def get_watchlist(db: Session, enabled_only: bool = True) -> list:
    """Get all watchlist items."""
    query = db.query(Watchlist)
    if enabled_only:
        query = query.filter(Watchlist.enabled == True)
    return query.order_by(Watchlist.created_at.desc()).all()


def update_watchlist_item(db: Session, item_id: int, **kwargs) -> Optional[Watchlist]:
    """Update a watchlist item."""
    item = db.query(Watchlist).filter(Watchlist.id == item_id).first()
    if not item:
        return None
    for key, value in kwargs.items():
        if hasattr(item, key) and value is not None:
            setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


def delete_watchlist_item(db: Session, item_id: int) -> bool:
    """Delete a watchlist item."""
    item = db.query(Watchlist).filter(Watchlist.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
        return True
    return False


def check_watchlist_matches(db: Session, hours: int = 24) -> list[dict]:
    """Check new articles against all watchlist items."""
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    watchlist = db.query(Watchlist).filter(Watchlist.enabled == True).all()

    if not watchlist:
        return []

    # Get recent articles
    articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
    ).filter(
        Article.fetched_at >= since,
    ).all()

    matches = []
    for item in watchlist:
        item_matches = _match_articles(item, articles)
        if item_matches:
            # Update match count and timestamp
            item.match_count += len(item_matches)
            item.last_triggered_at = datetime.datetime.utcnow()

            matches.append({
                "watchlist_item": {
                    "id": item.id,
                    "name": item.name,
                    "type": item.watch_type,
                    "value": item.watch_value,
                },
                "new_matches": len(item_matches),
                "articles": [
                    {"id": a.id, "title": a.title, "url": a.url,
                     "score": a.score.total_score if a.score else 0}
                    for a in item_matches[:10]
                ],
                "notify": item.notify_on_match,
            })

    db.commit()
    return matches


def _match_articles(item: Watchlist, articles: list[Article]) -> list[Article]:
    """Match articles against a single watchlist item."""
    matched = []
    value_lower = item.watch_value.lower()

    for article in articles:
        # Score filter
        if item.min_score > 0:
            if not article.score or article.score.total_score < item.min_score:
                continue

        if item.watch_type == "keyword":
            # Keyword matching in title and content
            text = f"{article.title} {article.raw_content or ''}".lower()
            if value_lower in text:
                matched.append(article)

        elif item.watch_type == "topic":
            # Tag matching
            if article.classification and article.classification.tags:
                if value_lower in [t.lower() for t in article.classification.tags]:
                    matched.append(article)

        elif item.watch_type == "entity":
            # Entity matching
            if article.classification and article.classification.entities:
                entity_names = [e.get("name", "").lower() for e in article.classification.entities]
                if value_lower in entity_names:
                    matched.append(article)

        elif item.watch_type == "source":
            # Source matching (by source name)
            if article.source and value_lower in article.source.name.lower():
                matched.append(article)

    return matched


def get_watchlist_feed(db: Session, item_id: int, days: int = 7, limit: int = 50) -> dict:
    """Get a personalized feed for a specific watchlist item."""
    item = db.query(Watchlist).filter(Watchlist.id == item_id).first()
    if not item:
        return {"error": "Watchlist item not found"}

    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
        joinedload(Article.source),
    ).filter(
        Article.fetched_at >= since,
    ).order_by(desc(Article.published_at)).limit(500).all()

    matched = _match_articles(item, articles)

    # Sort by score
    matched.sort(
        key=lambda a: a.score.total_score if a.score else 0,
        reverse=True
    )

    return {
        "watchlist_item": {
            "id": item.id,
            "name": item.name,
            "type": item.watch_type,
            "value": item.watch_value,
        },
        "total_matches": len(matched),
        "articles": [
            {
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "source": a.source.name if a.source else None,
                "score": a.score.total_score if a.score else 0,
                "content_type": a.classification.content_type if a.classification else None,
                "tags": a.classification.tags if a.classification else [],
                "summary": a.one_line_summary,
            }
            for a in matched[:limit]
        ],
    }
