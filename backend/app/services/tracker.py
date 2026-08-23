"""Person and organization opinion tracking service."""
import datetime
import logging
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import String
from sqlalchemy import desc

from app.models import Article, Classification, Score, Entity
from app.services.classifier import KNOWN_ENTITIES

logger = logging.getLogger(__name__)

# Key people to track
TRACKED_PEOPLE = {
    # AI Leaders
    "Sam Altman": {"category": "ai", "org": "OpenAI"},
    "Demis Hassabis": {"category": "ai", "org": "Google DeepMind"},
    "Yann LeCun": {"category": "ai", "org": "Meta"},
    "Andrew Ng": {"category": "ai", "org": "Landing AI"},
    "Jensen Huang": {"category": "ai", "org": "Nvidia"},
    "Satya Nadella": {"category": "ai", "org": "Microsoft"},
    "Marc Andreessen": {"category": "investor", "org": "a16z"},

    # Crypto / Web3 Leaders
    "Vitalik Buterin": {"category": "crypto", "org": "Ethereum"},
    "Brian Armstrong": {"category": "crypto", "org": "Coinbase"},
    "Balaji Srinivasan": {"category": "crypto", "org": "Independent"},
    "Chris Dixon": {"category": "crypto", "org": "a16z crypto"},
    "Anatoly Yakovenko": {"category": "crypto", "org": "Solana"},
    "Arthur Hayes": {"category": "crypto", "org": "BitMEX / Maelstrom"},
    "Naval Ravikant": {"category": "crypto", "org": "AngelList"},

    # Investment / Macro
    "Cathie Wood": {"category": "investor", "org": "Ark Invest"},
    "Fred Wilson": {"category": "investor", "org": "USV"},
    "Kyle Samani": {"category": "investor", "org": "Multicoin Capital"},
    "Raoul Pal": {"category": "investor", "org": "Real Vision"},
    "Paul Graham": {"category": "investor", "org": "YC"},
}

# Key organizations to track
TRACKED_ORGANIZATIONS = {
    "OpenAI": {"category": "ai", "type": "company"},
    "Anthropic": {"category": "ai", "type": "company"},
    "Google": {"category": "ai", "type": "company"},
    "Microsoft": {"category": "ai", "type": "company"},
    "Nvidia": {"category": "ai", "type": "company"},
    "Coinbase": {"category": "crypto", "type": "company"},
    "Binance": {"category": "crypto", "type": "company"},
    "a16z": {"category": "investor", "type": "fund"},
    "Grayscale": {"category": "investor", "type": "fund"},
    "Ark Invest": {"category": "investor", "type": "fund"},
    "VanEck": {"category": "investor", "type": "fund"},
    "SEC": {"category": "regulator", "type": "government"},
    "Ethereum Foundation": {"category": "crypto", "type": "foundation"},
    "Solana Foundation": {"category": "crypto", "type": "foundation"},
    "Bittensor": {"category": "crypto", "type": "project"},
    "Worldcoin": {"category": "crypto", "type": "project"},
    "Fetch.ai": {"category": "crypto", "type": "project"},
}


def get_person_timeline(db: Session, person_name: str, days: int = 30) -> dict:
    """Get all articles mentioning a specific person with timeline."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
    ).join(Classification).filter(
        Article.fetched_at >= since,
        Classification.entities.cast(String).like(f'%"{person_name}"%'),
    ).order_by(desc(Article.published_at)).all()

    # Extract opinion context
    opinions = []
    for article in articles:
        opinions.append({
            "id": article.id,
            "title": article.title,
            "url": article.url,
            "date": article.published_at.isoformat() if article.published_at else None,
            "content_type": article.classification.content_type if article.classification else None,
            "summary": article.one_line_summary or article.summary[:200] if article.summary else None,
            "score": article.score.total_score if article.score else None,
            "tags": article.classification.tags if article.classification else [],
        })

    info = TRACKED_PEOPLE.get(person_name, {})
    return {
        "name": person_name,
        "category": info.get("category", "unknown"),
        "organization": info.get("org", "unknown"),
        "total_mentions": len(opinions),
        "articles": opinions,
    }


def get_organization_timeline(db: Session, org_name: str, days: int = 30) -> dict:
    """Get all articles mentioning a specific organization."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
    ).join(Classification).filter(
        Article.fetched_at >= since,
        Classification.entities.cast(String).like(f'%"{org_name}"%'),
    ).order_by(desc(Article.published_at)).all()

    activities = []
    for article in articles:
        activities.append({
            "id": article.id,
            "title": article.title,
            "url": article.url,
            "date": article.published_at.isoformat() if article.published_at else None,
            "content_type": article.classification.content_type if article.classification else None,
            "summary": article.one_line_summary or (article.summary[:200] if article.summary else None),
            "score": article.score.total_score if article.score else None,
            "tags": article.classification.tags if article.classification else [],
        })

    info = TRACKED_ORGANIZATIONS.get(org_name, {})
    return {
        "name": org_name,
        "category": info.get("category", "unknown"),
        "type": info.get("type", "unknown"),
        "total_mentions": len(activities),
        "articles": activities,
    }


def get_people_leaderboard(db: Session, days: int = 7) -> list[dict]:
    """Get leaderboard of most mentioned people."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    articles = db.query(Article).options(
        joinedload(Article.classification)
    ).filter(
        Article.fetched_at >= since
    ).all()

    person_counts = defaultdict(int)
    for article in articles:
        if not article.classification or not article.classification.entities:
            continue
        for entity in article.classification.entities:
            if entity.get("type") == "person":
                person_counts[entity["name"]] += 1

    result = []
    for name, count in sorted(person_counts.items(), key=lambda x: x[1], reverse=True):
        info = TRACKED_PEOPLE.get(name, {"category": "unknown", "org": "unknown"})
        result.append({
            "name": name,
            "count": count,
            "category": info.get("category", "unknown"),
            "organization": info.get("org", "unknown"),
        })

    return result[:20]


def get_org_leaderboard(db: Session, days: int = 7) -> list[dict]:
    """Get leaderboard of most mentioned organizations/projects."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    articles = db.query(Article).options(
        joinedload(Article.classification)
    ).filter(
        Article.fetched_at >= since
    ).all()

    org_counts = defaultdict(int)
    for article in articles:
        if not article.classification or not article.classification.entities:
            continue
        for entity in article.classification.entities:
            if entity.get("type") in ("company", "project", "organization"):
                org_counts[entity["name"]] += 1

    result = []
    for name, count in sorted(org_counts.items(), key=lambda x: x[1], reverse=True):
        info = TRACKED_ORGANIZATIONS.get(name, {"category": "unknown", "type": "unknown"})
        result.append({
            "name": name,
            "count": count,
            "category": info.get("category", "unknown"),
            "type": info.get("type", "unknown"),
        })

    return result[:20]


def get_opinion_shifts(db: Session, entity_name: str, days: int = 30) -> dict:
    """Analyze how sentiment/narrative around an entity has shifted over time."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    articles = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.score),
    ).join(Classification).filter(
        Article.fetched_at >= since,
        Classification.entities.cast(String).like(f'%"{entity_name}"%'),
    ).order_by(Article.published_at).all()

    # Group by week
    weekly_data = defaultdict(lambda: {
        "articles": 0, "avg_score": 0, "avg_hype": 0,
        "avg_risk": 0, "types": Counter(), "topics": Counter(),
    })

    for article in articles:
        if not article.published_at:
            continue
        week = article.published_at.strftime("%Y-W%W")
        weekly_data[week]["articles"] += 1

        if article.score:
            weekly_data[week]["avg_score"] += article.score.total_score
        if article.classification:
            weekly_data[week]["avg_hype"] += article.classification.hype_risk
            weekly_data[week]["avg_risk"] += article.classification.regulation_risk
            weekly_data[week]["types"][article.classification.content_type] += 1
            if article.classification.tags:
                for tag in article.classification.tags:
                    weekly_data[week]["topics"][tag] += 1

    # Compute averages
    result = []
    for week in sorted(weekly_data.keys()):
        data = weekly_data[week]
        count = data["articles"] or 1
        result.append({
            "week": week,
            "articles": data["articles"],
            "avg_score": round(data["avg_score"] / count, 3),
            "avg_hype_risk": round(data["avg_hype"] / count, 3),
            "avg_regulation_risk": round(data["avg_risk"] / count, 3),
            "top_types": dict(data["types"].most_common(3)),
            "top_topics": dict(data["topics"].most_common(5)),
        })

    return {
        "entity": entity_name,
        "period_days": days,
        "weekly_data": result,
    }
