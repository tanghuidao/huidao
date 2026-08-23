"""Public RSS 2.0 feeds: briefings and risk alerts.

- /rss/briefing.xml : latest AI-generated daily/weekly briefings
- /rss/alerts.xml   : recent high regulation-risk / suspected-hype articles
"""
import datetime
import html
from email.utils import format_datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func, or_

from app.database import get_db
from app.models import Article, Briefing, Classification

router = APIRouter(prefix="/rss", tags=["rss"])

BASE_URL = "https://huidao.cc"
CACHE = {"Cache-Control": "public, max-age=300"}


def _rfc822(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, datetime.datetime):
        return format_datetime(dt)
    return str(dt)


def _escape(text: str, limit: int = 0) -> str:
    if not text:
        return ""
    if limit and len(text) > limit:
        text = text[:limit] + "..."
    return html.escape(text)


def _channel(title: str, link: str, description: str, language: str, items: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
        "<channel>"
        f"<title>{_escape(title)}</title>"
        f"<link>{link}</link>"
        f"<description>{_escape(description)}</description>"
        f"<language>{language}</language>"
        f"<lastBuildDate>{_rfc822(datetime.datetime.utcnow())}</lastBuildDate>"
        f'<atom:link href="{link}" rel="self" type="application/rss+xml"/>'
        f"{items}"
        "</channel></rss>"
    )


@router.get("/briefing.xml")
def rss_briefings(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    """RSS feed of the latest AI-generated briefings."""
    rows = (
        db.query(Briefing)
        .order_by(desc(Briefing.created_at))
        .limit(limit)
        .all()
    )

    items = []
    for b in rows:
        label = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}.get(
            b.period_type, b.period_type
        )
        link = f"{BASE_URL}/b/{b.id}"
        desc = _escape((b.content or "")[:500], 500)
        items.append(
            "<item>"
            f"<title>{_escape(b.title)}</title>"
            f"<link>{link}</link>"
            f"<guid isPermaLink=\"true\">{link}</guid>"
            f"<description>{desc}</description>"
            f"<category>{label}</category>"
            f"<pubDate>{_rfc822(b.created_at)}</pubDate>"
            "</item>"
        )

    content = _channel(
        "huidao.cc - AI Briefings",
        f"{BASE_URL}/rss/briefing.xml",
        "AI-generated daily/weekly briefings on AI, Crypto, Web3 and Web4, "
        "aggregated from 60+ global sources. CC BY 4.0.",
        "zh-CN",
        "".join(items),
    )
    return Response(content=content, media_type="application/rss+xml", headers=CACHE)


@router.get("/alerts.xml")
def rss_alerts(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """RSS feed of recent risk alerts: high regulation-risk and suspected-hype articles."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    rows = (
        db.query(Article)
        .options(joinedload(Article.classification), joinedload(Article.source))
        .join(Classification)
        .filter(
            Article.fetched_at >= since,
            or_(
                Classification.regulation_risk > 0.5,
                Classification.hype_risk > 0.5,
            ),
        )
        .order_by(
            desc(
                func.greatest(
                    Classification.regulation_risk, Classification.hype_risk
                )
            )
        )
        .limit(limit)
        .all()
    )

    items = []
    for a in rows:
        c = a.classification
        reg = c.regulation_risk if c else 0.0
        hype = c.hype_risk if c else 0.0
        cats = []
        if reg > 0.5:
            cats.append(f"regulation_risk:{int(reg * 100)}%")
        if hype > 0.5:
            cats.append(f"hype_warning:{int(hype * 100)}%")
        link = f"{BASE_URL}/a/{a.id}"
        source_name = a.source.name if a.source else ""
        desc = (
            f"regulation_risk={int(reg * 100)}%, hype_risk={int(hype * 100)}%"
            + (f", source={source_name}" if source_name else "")
            + (f", summary={_escape(a.one_line_summary or '', 300)}" if a.one_line_summary else "")
        )
        items.append(
            "<item>"
            f"<title>{_escape(a.title)}</title>"
            f"<link>{link}</link>"
            f'<guid isPermaLink="true">{link}</guid>'
            f"<description>{_escape(desc)}</description>"
            + "".join(f"<category>{_escape(cat)}</category>" for cat in cats)
            + f"<pubDate>{_rfc822(a.published_at or a.fetched_at)}</pubDate>"
            "</item>"
        )

    content = _channel(
        "huidao.cc - Risk Alerts",
        f"{BASE_URL}/rss/alerts.xml",
        "Auto-generated risk alerts: high regulation risk and suspected hype "
        "content detected by AI across 60+ global sources. Research reference only, "
        "not investment advice.",
        "zh-CN",
        "".join(items),
    )
    return Response(content=content, media_type="application/rss+xml", headers=CACHE)
