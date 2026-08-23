"""Dashboard data router."""
import datetime
from collections import Counter
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func

from app.database import get_db
from app.models import Article, Source, Classification, Score
from app.schemas import (
    DashboardData, DashboardStats, TopicCount, EntityCount, ArticleResponse
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/", response_model=DashboardData)
def get_dashboard(db: Session = Depends(get_db)):
    """Get dashboard overview data."""
    now = datetime.datetime.utcnow()
    today_start = datetime.datetime.combine(now.date(), datetime.time.min)
    week_start = today_start - datetime.timedelta(days=7)

    # Stats
    total_sources = db.query(Source).count()
    active_sources = db.query(Source).filter(Source.enabled == True).count()
    healthy_sources = db.query(Source).filter(Source.health_status == "healthy").count()
    total_articles = db.query(Article).count()
    articles_today = db.query(Article).filter(Article.fetched_at >= today_start).count()
    articles_this_week = db.query(Article).filter(Article.fetched_at >= week_start).count()

    from app.models import Briefing
    total_briefings = db.query(Briefing).count()

    stats = DashboardStats(
        total_sources=total_sources,
        active_sources=active_sources,
        healthy_sources=healthy_sources,
        total_articles=total_articles,
        articles_today=articles_today,
        articles_this_week=articles_this_week,
        total_briefings=total_briefings,
    )

    # Recent articles (top scored)
    recent_articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
    ).join(Score, isouter=True).filter(
        Article.fetched_at >= week_start,
    ).order_by(desc(Score.total_score)).limit(10).all()

    # Hot topics (from last 7 days)
    classifications = db.query(Classification).join(Article).filter(
        Article.fetched_at >= week_start
    ).all()

    tag_counter = Counter()
    entity_counter = Counter()
    for c in classifications:
        if c.tags:
            for tag in c.tags:
                tag_counter[tag] += 1
        if c.entities:
            for entity in c.entities:
                name = entity.get("name", "")
                etype = entity.get("type", "")
                if name:
                    entity_counter[(name, etype)] += 1

    hot_topics = [
        TopicCount(topic=topic, count=count)
        for topic, count in tag_counter.most_common(15)
    ]

    top_entities = [
        EntityCount(name=name, type=etype, count=count)
        for (name, etype), count in entity_counter.most_common(15)
    ]

    # High risk articles
    high_risk_articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
    ).join(Classification).filter(
        Article.fetched_at >= week_start,
        Classification.regulation_risk > 0.5,
    ).order_by(desc(Classification.regulation_risk)).limit(5).all()

    # Suspected hype
    suspected_hype = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
    ).join(Classification).filter(
        Article.fetched_at >= week_start,
        Classification.hype_risk > 0.5,
    ).order_by(desc(Classification.hype_risk)).limit(5).all()

    return DashboardData(
        stats=stats,
        recent_articles=recent_articles,
        hot_topics=hot_topics,
        top_entities=top_entities,
        high_risk_articles=high_risk_articles,
        suspected_hype=suspected_hype,
    )
