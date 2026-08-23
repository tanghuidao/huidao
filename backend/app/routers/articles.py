"""Article management router."""
import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc

from app.database import get_db
from app.models import Article, Classification, Score
from app.schemas import ArticleResponse, ArticleListResponse

router = APIRouter(prefix="/api/articles", tags=["articles"])


@router.get("/", response_model=ArticleListResponse)
def list_articles(
    keyword: str = None,
    source_id: int = None,
    content_type: str = None,
    tag: str = None,
    min_score: float = None,
    days: int = 7,
    sort_by: str = "published_at",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List articles with filters and pagination."""
    query = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
    )

    # Time filter
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    query = query.filter(Article.fetched_at >= since)

    # Keyword search
    if keyword:
        query = query.filter(
            Article.title.ilike(f"%{keyword}%") |
            Article.raw_content.ilike(f"%{keyword}%")
        )

    # Source filter
    if source_id:
        query = query.filter(Article.source_id == source_id)

    # Content type filter
    if content_type:
        query = query.join(Classification).filter(
            Classification.content_type == content_type
        )

    # Tag filter
    if tag:
        query = query.join(Classification, isouter=True).filter(
            Classification.tags.ilike(f'%"{tag}"%')
        )

    # Score filter
    if min_score is not None:
        query = query.join(Score, isouter=True).filter(
            Score.total_score >= min_score
        )

    # Total count
    total = query.count()

    # Sorting
    if sort_by == "score":
        query = query.join(Score, isouter=True).order_by(desc(Score.total_score))
    else:
        query = query.order_by(desc(Article.published_at))

    # Pagination
    articles = query.offset((page - 1) * page_size).limit(page_size).all()

    return ArticleListResponse(total=total, articles=articles)


@router.get("/{article_id}", response_model=ArticleResponse)
def get_article(article_id: int, db: Session = Depends(get_db)):
    """Get a single article with full details."""
    article = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
    ).filter(Article.id == article_id).first()

    if not article:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Article not found")
    return article
