"""Investment and policy risk alert system."""
import datetime
import logging
from collections import Counter, defaultdict
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import String, desc

from app.models import Article, Classification, Score, Source, Alert
from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

logger = logging.getLogger(__name__)

# Alert thresholds
THRESHOLDS = {
    "regulation_risk_high": 0.7,        # Single article regulation risk
    "hype_spike_threshold": 5,           # Number of hype articles in short window
    "funding_cluster_threshold": 3,      # Multiple funding events for same entity
    "narrative_shift_threshold": 0.4,    # Topic growth rate that triggers alert
    "source_anomaly_threshold": 3,       # Sudden spike in mentions from one source
}


def check_regulation_alerts(db: Session, hours: int = 24) -> list[dict]:
    """Check for new regulation risk alerts."""
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)

    high_risk = db.query(Article).options(
        joinedload(Article.classification),
        joinedload(Article.source),
    ).join(Classification).filter(
        Article.fetched_at >= since,
        Classification.regulation_risk >= THRESHOLDS["regulation_risk_high"],
    ).all()

    alerts = []
    for article in high_risk:
        # Check if alert already exists
        existing = db.query(Alert).filter(
            Alert.alert_type == "regulation_risk",
            Alert.related_articles.cast(String).like(f'%{article.id}%'),
        ).first()
        if existing:
            continue

        entities = [e.get("name", "") for e in (article.classification.entities or [])]
        alert = Alert(
            alert_type="regulation_risk",
            severity="high" if article.classification.regulation_risk > 0.8 else "medium",
            title=f"监管风险: {article.title[:100]}",
            description=f"来源: {article.source.name if article.source else 'Unknown'}\n"
                       f"风险分数: {article.classification.regulation_risk:.2f}\n"
                       f"涉及实体: {', '.join(entities[:5])}",
            related_articles=[article.id],
            related_entities=entities[:10],
            extra_data={"regulation_risk": article.classification.regulation_risk},
        )
        db.add(alert)
        alerts.append({
            "type": "regulation_risk",
            "severity": alert.severity,
            "title": alert.title,
            "article_id": article.id,
        })

    db.commit()
    return alerts


def check_investment_signals(db: Session, hours: int = 24) -> list[dict]:
    """Check for investment signal alerts (funding clusters, capital movement)."""
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)

    funding_articles = db.query(Article).options(
        joinedload(Article.classification),
    ).join(Classification).filter(
        Article.fetched_at >= since,
        Classification.content_type == "funding",
    ).all()

    # Group by entity
    entity_funding = defaultdict(list)
    for article in funding_articles:
        if article.classification and article.classification.entities:
            for entity in article.classification.entities:
                name = entity.get("name", "")
                if name:
                    entity_funding[name].append(article.id)

    alerts = []
    for entity, article_ids in entity_funding.items():
        if len(article_ids) >= THRESHOLDS["funding_cluster_threshold"]:
            existing = db.query(Alert).filter(
                Alert.alert_type == "investment_signal",
                Alert.title.like(f'%{entity}%'),
                Alert.created_at >= since,
            ).first()
            if existing:
                continue

            alert = Alert(
                alert_type="investment_signal",
                severity="high" if len(article_ids) >= 5 else "medium",
                title=f"资本信号: {entity} ({len(article_ids)}条相关融资信息)",
                description=f"实体 '{entity}' 在近{hours}小时内出现 {len(article_ids)} 条融资相关信息，"
                           f"可能存在重大资本活动。",
                related_articles=article_ids,
                related_entities=[entity],
                extra_data={"funding_count": len(article_ids)},
            )
            db.add(alert)
            alerts.append({
                "type": "investment_signal",
                "severity": alert.severity,
                "title": alert.title,
                "entity": entity,
            })

    db.commit()
    return alerts


def check_hype_alerts(db: Session, hours: int = 12) -> list[dict]:
    """Check for hype/bubble warnings."""
    since = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)

    hype_articles = db.query(Article).options(
        joinedload(Article.classification),
    ).join(Classification).filter(
        Article.fetched_at >= since,
        Classification.hype_risk >= 0.6,
    ).all()

    if len(hype_articles) < THRESHOLDS["hype_spike_threshold"]:
        return []

    # Group by topic
    topic_hype = Counter()
    topic_articles = defaultdict(list)
    for article in hype_articles:
        if article.classification and article.classification.tags:
            for tag in article.classification.tags:
                topic_hype[tag] += 1
                topic_articles[tag].append(article.id)

    alerts = []
    for topic, count in topic_hype.most_common(5):
        if count >= 3:
            existing = db.query(Alert).filter(
                Alert.alert_type == "hype_warning",
                Alert.title.like(f'%{topic}%'),
                Alert.created_at >= since,
            ).first()
            if existing:
                continue

            alert = Alert(
                alert_type="hype_warning",
                severity="medium",
                title=f"炒作预警: {topic} ({count}条高炒作风险内容)",
                description=f"话题 '{topic}' 在近{hours}小时出现 {count} 条高炒作风险内容。"
                           f"建议审慎评估相关信息的真实性。",
                related_articles=topic_articles[topic][:10],
                related_entities=[topic],
                extra_data={"hype_count": count, "topic": topic},
            )
            db.add(alert)
            alerts.append({
                "type": "hype_warning",
                "severity": "medium",
                "title": alert.title,
                "topic": topic,
            })

    db.commit()
    return alerts


def check_narrative_shift_alerts(db: Session, days: int = 3) -> list[dict]:
    """Check for sudden narrative shifts (rapid topic growth/decline)."""
    from app.services.trends import get_emerging_topics

    emerging = get_emerging_topics(db, recent_days=days, compare_days=14)
    alerts = []

    for topic_data in emerging:
        if topic_data["growth_rate"] >= THRESHOLDS["narrative_shift_threshold"]:
            existing = db.query(Alert).filter(
                Alert.alert_type == "narrative_shift",
                Alert.title.like(f'%{topic_data["topic"]}%'),
                Alert.created_at >= datetime.datetime.utcnow() - datetime.timedelta(days=1),
            ).first()
            if existing:
                continue

            is_new = topic_data.get("is_new", False)
            growth_pct = int(topic_data.get("growth_rate", 0) * 100)
            topic_name = topic_data.get("topic", "unknown")
            recent_count = topic_data.get("recent_count", 0)
            suffix = "(新话题)" if is_new else "(+{}%)".format(growth_pct)
            desc_detail = "为新出现话题" if is_new else "增长率 {}%".format(growth_pct)
            alert = Alert(
                alert_type="narrative_shift",
                severity="medium" if not is_new else "low",
                title="叙事变化: {} {}".format(topic_name, suffix),
                description="话题 '{}' 近{}天提及 {} 次，{}。".format(topic_name, days, recent_count, desc_detail),
                related_entities=[topic_data["topic"]],
                extra_data=topic_data,
            )
            db.add(alert)
            alerts.append({
                "type": "narrative_shift",
                "severity": alert.severity,
                "title": alert.title,
            })

    db.commit()
    return alerts


def run_all_checks(db: Session) -> dict:
    """Run all alert checks and return summary."""
    results = {
        "regulation": check_regulation_alerts(db),
        "investment": check_investment_signals(db),
        "hype": check_hype_alerts(db),
        "narrative": check_narrative_shift_alerts(db),
    }

    total_new = sum(len(v) for v in results.values())
    logger.info(f"Alert check complete: {total_new} new alerts")
    return results


def get_active_alerts(db: Session, limit: int = 50) -> list:
    """Get all active alerts."""
    return db.query(Alert).filter(
        Alert.status == "active"
    ).order_by(desc(Alert.created_at)).limit(limit).all()


def acknowledge_alert(db: Session, alert_id: int) -> bool:
    """Mark an alert as acknowledged."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert:
        alert.status = "acknowledged"
        db.commit()
        return True
    return False


def resolve_alert(db: Session, alert_id: int) -> bool:
    """Mark an alert as resolved."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert:
        alert.status = "resolved"
        alert.resolved_at = datetime.datetime.utcnow()
        db.commit()
        return True
    return False
