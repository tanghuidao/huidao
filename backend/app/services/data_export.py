"""Data export service for Max tier users."""
import csv
import io
import json
import datetime
import logging

from sqlalchemy.orm import Session
from app.models import User, Article, Classification, Score, Membership, Payment

logger = logging.getLogger(__name__)


def export_user_data(db, user_id):
    """Export all user data as a structured dict (for JSON/CSV generation).

    Only available for Max tier users.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"error": "\u7528\u6237\u4e0d\u5b58\u5728"}

    if user.membership_tier != "max":
        return {"error": "\u4ec5\u65d7\u8230\u7248\u4f1a\u5458\u53ef\u5bfc\u51fa\u6570\u636e"}

    # User profile
    profile = {
        "email": user.email,
        "display_name": user.display_name,
        "membership_tier": user.membership_tier,
        "created_at": str(user.created_at) if user.created_at else None,
        "email_verified": user.email_verified,
    }

    # Membership history
    memberships = db.query(Membership).filter(
        Membership.user_id == user_id
    ).order_by(Membership.created_at).all()
    membership_history = [
        {
            "tier": m.tier, "status": m.status,
            "started_at": str(m.started_at),
            "expires_at": str(m.expires_at) if m.expires_at else None,
        }
        for m in memberships
    ]

    # Payment history
    payments = db.query(Payment).filter(
        Payment.user_id == user_id
    ).order_by(Payment.created_at).all()
    payment_history = [
        {
            "order_id": p.order_id, "tier": p.tier, "amount": p.amount,
            "payment_method": p.payment_method, "status": p.status,
            "paid_at": str(p.paid_at) if p.paid_at else None,
            "created_at": str(p.created_at) if p.created_at else None,
        }
        for p in payments
    ]

    return {
        "exported_at": datetime.datetime.utcnow().isoformat(),
        "platform": "huidao.cc",
        "profile": profile,
        "membership_history": membership_history,
        "payment_history": payment_history,
    }


def export_articles_csv(db, days=30, limit=1000):
    """Export recent articles as CSV string."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    articles = db.query(Article).join(
        Classification, isouter=True
    ).join(
        Score, isouter=True
    ).filter(
        Article.fetched_at >= cutoff
    ).order_by(
        Article.fetched_at.desc()
    ).limit(limit).all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "ID", "Title", "URL", "Source ID", "Published", "Fetched",
        "Language", "Content Type", "Tags", "Total Score",
        "Credibility", "Impact", "Risk", "Summary"
    ])

    for a in articles:
        cls = a.classification
        score = a.score
        writer.writerow([
            a.id,
            a.title[:200],
            a.url,
            a.source_id,
            str(a.published_at) if a.published_at else "",
            str(a.fetched_at),
            a.language,
            cls.content_type if cls else "",
            "|".join(cls.tags) if cls and cls.tags else "",
            score.total_score if score else "",
            score.credibility if score else "",
            score.impact if score else "",
            score.risk if score else "",
            (a.one_line_summary or "")[:200],
        ])

    return output.getvalue()


def export_articles_json(db, days=30, limit=1000):
    """Export recent articles as JSON string."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)

    articles = db.query(Article).join(
        Classification, isouter=True
    ).join(
        Score, isouter=True
    ).filter(
        Article.fetched_at >= cutoff
    ).order_by(
        Article.fetched_at.desc()
    ).limit(limit).all()

    data = []
    for a in articles:
        cls = a.classification
        score = a.score
        data.append({
            "id": a.id,
            "title": a.title,
            "url": a.url,
            "source_id": a.source_id,
            "published_at": str(a.published_at) if a.published_at else None,
            "fetched_at": str(a.fetched_at),
            "language": a.language,
            "content_type": cls.content_type if cls else None,
            "tags": cls.tags if cls else [],
            "score": {
                "total": score.total_score if score else 0,
                "credibility": score.credibility if score else 0,
                "impact": score.impact if score else 0,
                "risk": score.risk if score else 0,
            } if score else None,
            "summary": a.one_line_summary or "",
        })

    return json.dumps(data, ensure_ascii=False, indent=2)
