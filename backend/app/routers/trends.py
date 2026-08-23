"""Trends and chart data router."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.trends import (
    get_article_count_by_day,
    get_topic_trend,
    get_entity_trend,
    get_content_type_distribution,
    get_source_activity,
    get_score_distribution,
    get_risk_trend,
    get_emerging_topics,
)

router = APIRouter(prefix="/api/trends", tags=["trends"])


@router.get("/article-count")
def article_count_trend(days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db)):
    """Get article count per day trend."""
    return get_article_count_by_day(db, days=days)


@router.get("/topics")
def topic_trend(
    days: int = Query(30, ge=1, le=90),
    top_n: int = Query(10, ge=3, le=20),
    db: Session = Depends(get_db),
):
    """Get topic trends over time."""
    return get_topic_trend(db, days=days, top_n=top_n)


@router.get("/entities")
def entity_trend(
    days: int = Query(30, ge=1, le=90),
    top_n: int = Query(10, ge=3, le=20),
    db: Session = Depends(get_db),
):
    """Get entity mention trends over time."""
    return get_entity_trend(db, days=days, top_n=top_n)


@router.get("/content-types")
def content_type_dist(days: int = Query(7, ge=1, le=30), db: Session = Depends(get_db)):
    """Get content type distribution."""
    return get_content_type_distribution(db, days=days)


@router.get("/source-activity")
def source_activity(days: int = Query(7, ge=1, le=30), db: Session = Depends(get_db)):
    """Get source activity ranking."""
    return get_source_activity(db, days=days)


@router.get("/score-distribution")
def score_dist(days: int = Query(7, ge=1, le=30), db: Session = Depends(get_db)):
    """Get score distribution histogram."""
    return get_score_distribution(db, days=days)


@router.get("/risk")
def risk_trend(days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db)):
    """Get risk trend over time."""
    return get_risk_trend(db, days=days)


@router.get("/emerging")
def emerging_topics(
    recent_days: int = Query(3, ge=1, le=7),
    compare_days: int = Query(14, ge=7, le=60),
    db: Session = Depends(get_db),
):
    """Detect emerging topics."""
    return get_emerging_topics(db, recent_days=recent_days, compare_days=compare_days)
