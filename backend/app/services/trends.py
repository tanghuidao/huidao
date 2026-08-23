"""Trend analysis service - aggregates data over time for charts."""
import datetime
import logging
from collections import Counter, defaultdict
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc

from app.models import Article, Classification, Score, Source

logger = logging.getLogger(__name__)


def get_article_count_by_day(db: Session, days: int = 30) -> list[dict]:
    """Get article counts grouped by day."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    results = db.query(
        func.date(Article.fetched_at).label("date"),
        func.count(Article.id).label("count"),
    ).filter(
        Article.fetched_at >= since
    ).group_by(
        func.date(Article.fetched_at)
    ).order_by("date").all()

    return [{"date": str(r.date), "count": r.count} for r in results]


def get_topic_trend(db: Session, days: int = 30, top_n: int = 10) -> dict:
    """Get topic trends over time (daily counts per topic)."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    articles = db.query(Article).options(
        joinedload(Article.classification)
    ).filter(
        Article.fetched_at >= since
    ).all()

    # Aggregate: {date: {topic: count}}
    daily_topics = defaultdict(Counter)
    topic_totals = Counter()

    for article in articles:
        if not article.classification or not article.classification.tags:
            continue
        date_str = article.fetched_at.strftime("%Y-%m-%d")
        for tag in article.classification.tags:
            daily_topics[date_str][tag] += 1
            topic_totals[tag] += 1

    # Get top N topics overall
    top_topics = [t for t, _ in topic_totals.most_common(top_n)]

    # Build time series for each top topic
    all_dates = sorted(daily_topics.keys())
    series = {}
    for topic in top_topics:
        series[topic] = [
            {"date": d, "count": daily_topics[d].get(topic, 0)}
            for d in all_dates
        ]

    return {
        "topics": top_topics,
        "series": series,
        "dates": all_dates,
    }


def get_entity_trend(db: Session, days: int = 30, top_n: int = 10) -> dict:
    """Get entity mention trends over time."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    articles = db.query(Article).options(
        joinedload(Article.classification)
    ).filter(
        Article.fetched_at >= since
    ).all()

    daily_entities = defaultdict(Counter)
    entity_totals = Counter()

    for article in articles:
        if not article.classification or not article.classification.entities:
            continue
        date_str = article.fetched_at.strftime("%Y-%m-%d")
        for entity in article.classification.entities:
            name = entity.get("name", "")
            if name:
                daily_entities[date_str][name] += 1
                entity_totals[name] += 1

    top_entities = [e for e, _ in entity_totals.most_common(top_n)]
    all_dates = sorted(daily_entities.keys())

    series = {}
    for entity in top_entities:
        series[entity] = [
            {"date": d, "count": daily_entities[d].get(entity, 0)}
            for d in all_dates
        ]

    return {
        "entities": top_entities,
        "series": series,
        "dates": all_dates,
    }


def get_content_type_distribution(db: Session, days: int = 7) -> list[dict]:
    """Get content type distribution."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    results = db.query(
        Classification.content_type,
        func.count(Classification.id).label("count"),
    ).join(Article).filter(
        Article.fetched_at >= since
    ).group_by(
        Classification.content_type
    ).order_by(desc("count")).all()

    return [{"type": r.content_type, "count": r.count} for r in results]


def get_source_activity(db: Session, days: int = 7) -> list[dict]:
    """Get source activity (articles per source)."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    results = db.query(
        Source.name,
        Source.category,
        func.count(Article.id).label("count"),
    ).join(Article).filter(
        Article.fetched_at >= since
    ).group_by(
        Source.id
    ).order_by(desc("count")).limit(20).all()

    return [{"source": r.name, "category": r.category, "count": r.count} for r in results]


def get_score_distribution(db: Session, days: int = 7) -> dict:
    """Get score distribution histogram."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    scores = db.query(Score.total_score).join(Article).filter(
        Article.fetched_at >= since
    ).all()

    # Create histogram buckets (0-0.2, 0.2-0.4, etc.)
    buckets = {"0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    for (score,) in scores:
        if score < 0.2:
            buckets["0-0.2"] += 1
        elif score < 0.4:
            buckets["0.2-0.4"] += 1
        elif score < 0.6:
            buckets["0.4-0.6"] += 1
        elif score < 0.8:
            buckets["0.6-0.8"] += 1
        else:
            buckets["0.8-1.0"] += 1

    return buckets


def get_risk_trend(db: Session, days: int = 30) -> list[dict]:
    """Get regulation and hype risk over time."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    articles = db.query(Article).options(
        joinedload(Article.classification)
    ).filter(
        Article.fetched_at >= since
    ).all()

    daily_risk = defaultdict(lambda: {"regulation_avg": 0, "hype_avg": 0, "count": 0})

    for article in articles:
        if not article.classification:
            continue
        date_str = article.fetched_at.strftime("%Y-%m-%d")
        daily_risk[date_str]["regulation_avg"] += article.classification.regulation_risk
        daily_risk[date_str]["hype_avg"] += article.classification.hype_risk
        daily_risk[date_str]["count"] += 1

    result = []
    for date_str in sorted(daily_risk.keys()):
        data = daily_risk[date_str]
        count = data["count"] or 1
        result.append({
            "date": date_str,
            "regulation_risk": round(data["regulation_avg"] / count, 3),
            "hype_risk": round(data["hype_avg"] / count, 3),
        })

    return result


def get_emerging_topics(db: Session, recent_days: int = 3, compare_days: int = 14) -> list[dict]:
    """Detect emerging topics by comparing recent vs. historical frequency."""
    now = datetime.datetime.utcnow()
    recent_start = now - datetime.timedelta(days=recent_days)
    compare_start = now - datetime.timedelta(days=compare_days)

    # Recent topic counts
    recent_articles = db.query(Article).options(
        joinedload(Article.classification)
    ).filter(Article.fetched_at >= recent_start).all()

    recent_topics = Counter()
    for a in recent_articles:
        if a.classification and a.classification.tags:
            for tag in a.classification.tags:
                recent_topics[tag] += 1

    # Historical topic counts (excluding recent)
    historical_articles = db.query(Article).options(
        joinedload(Article.classification)
    ).filter(
        Article.fetched_at >= compare_start,
        Article.fetched_at < recent_start,
    ).all()

    historical_topics = Counter()
    for a in historical_articles:
        if a.classification and a.classification.tags:
            for tag in a.classification.tags:
                historical_topics[tag] += 1

    # Calculate growth ratio
    emerging = []
    for topic, recent_count in recent_topics.items():
        historical_count = historical_topics.get(topic, 0)
        # Normalize by time period
        recent_daily = recent_count / recent_days
        historical_daily = historical_count / max(compare_days - recent_days, 1)

        if historical_daily > 0:
            growth = (recent_daily - historical_daily) / historical_daily
        elif recent_count >= 2:
            growth = 10.0  # New topic
        else:
            growth = 0

        if growth > 0.3:  # At least 30% growth
            emerging.append({
                "topic": topic,
                "recent_count": recent_count,
                "historical_avg_daily": round(historical_daily, 2),
                "growth_rate": round(growth, 2),
                "is_new": historical_count == 0,
            })

    emerging.sort(key=lambda x: x["growth_rate"], reverse=True)
    return emerging[:15]
