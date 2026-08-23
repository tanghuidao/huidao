"""Public read-only JSON API (v1): open article data endpoint.

GET /api/v1/articles?category=&tag=&date_from=&date_to=&limit=&offset=

No auth (free/open positioning). Rate limited to 60 requests/min/IP at the
middleware layer (see app/services/rate_limiter.py).
"""
import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Article, Classification, Score, Source

router = APIRouter(prefix="/api/v1", tags=["public-api"])

BASE_URL = "https://huidao.cc"


@router.get("/articles")
def list_articles(
    category: Optional[str] = Query(None, description="content_type filter, e.g. news / regulation / funding"),
    tag: Optional[str] = Query(None, description="tag filter (exact tag text)"),
    date_from: Optional[datetime.date] = Query(None, description="YYYY-MM-DD, filter by publish time"),
    date_to: Optional[datetime.date] = Query(None, description="YYYY-MM-DD (inclusive)"),
    source_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Public structured article list. Fields: title, source, tags, risk scores,
    publish time, original URL. Free to use, CC BY 4.0, rate limit 60 req/min/IP."""
    query = (
        db.query(Article)
        .options(
            joinedload(Article.classification),
            joinedload(Article.score),
            joinedload(Article.source),
        )
    )

    if category:
        query = query.join(Classification).filter(Classification.content_type == category)

    if tag:
        query = query.join(Classification, isouter=True).filter(
            Classification.tags.ilike(f'%"{tag}"%')
        )

    if source_id:
        query = query.filter(Article.source_id == source_id)

    if date_from:
        query = query.filter(func.coalesce(Article.published_at, Article.fetched_at) >= date_from)
    if date_to:
        end = datetime.datetime.combine(date_to, datetime.time.max)
        query = query.filter(func.coalesce(Article.published_at, Article.fetched_at) <= end)

    total = query.count()

    rows = (
        query.order_by(desc(func.coalesce(Article.published_at, Article.fetched_at)))
        .offset(offset)
        .limit(limit)
        .all()
    )

    articles = []
    for a in rows:
        c = a.classification
        articles.append(
            {
                "id": a.id,
                "title": a.title,
                "url": a.url,                      # original source URL
                "link": f"{BASE_URL}/a/{a.id}",    # canonical page on huidao.cc
                "source_id": a.source_id,
                "source_name": a.source.name if a.source else None,
                "language": a.language,
                "published_at": (a.published_at or a.fetched_at).isoformat()
                if (a.published_at or a.fetched_at)
                else None,
                "content_type": c.content_type if c else None,
                "tags": (c.tags if c and isinstance(c.tags, list) else [])[:10],
                "regulation_risk": round(c.regulation_risk, 4) if c else None,
                "hype_risk": round(c.hype_risk, 4) if c else None,
                "total_score": round(a.score.total_score, 4) if a.score else None,
                "summary": a.one_line_summary or (a.summary[:200] if a.summary else None),
            }
        )

    return {
        "total": total,
        "count": len(articles),
        "limit": limit,
        "offset": offset,
        "articles": articles,
    }
