"""SQLAlchemy ORM models."""
import datetime
from typing import Optional
from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Source(Base):
    """Information source (RSS feeds, websites, APIs, etc.)."""
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)  # mainstream_media, crypto_media, ai_media, institution, enterprise, person
    region: Mapped[str] = mapped_column(String(50), default="global")
    credibility_score: Mapped[float] = mapped_column(Float, default=0.7)
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(50), default="rss")  # rss, web, api, manual
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    health_status: Mapped[str] = mapped_column(String(20), default="unknown")  # healthy, degraded, error, unknown
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    articles: Mapped[list["Article"]] = relationship(back_populates="source")


class Article(Base):
    """Collected content item."""
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    published_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    raw_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    one_line_summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    source: Mapped["Source"] = relationship(back_populates="articles")
    classification: Mapped[Optional["Classification"]] = relationship(
        back_populates="article", uselist=False, cascade="all, delete-orphan"
    )
    score: Mapped[Optional["Score"]] = relationship(
        back_populates="article", uselist=False, cascade="all, delete-orphan"
    )


class Classification(Base):
    """Content classification, tags, and entities."""
    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(Integer, ForeignKey("articles.id"), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)  # news, opinion, report, funding, regulation, product_launch, partnership, market_signal, person_speech, suspected_hype
    tags: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # list of topic tags
    entities: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # list of {name, type}
    topics: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # list of main topics
    hype_risk: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1
    regulation_risk: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1

    article: Mapped["Article"] = relationship(back_populates="classification")


class Score(Base):
    """Multi-dimensional scoring for an article."""
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(Integer, ForeignKey("articles.id"), unique=True, nullable=False)
    credibility: Mapped[float] = mapped_column(Float, default=0.5)
    impact: Mapped[float] = mapped_column(Float, default=0.5)
    execution: Mapped[float] = mapped_column(Float, default=0.5)
    capital_signal: Mapped[float] = mapped_column(Float, default=0.5)
    narrative_strength: Mapped[float] = mapped_column(Float, default=0.5)
    risk: Mapped[float] = mapped_column(Float, default=0.5)
    total_score: Mapped[float] = mapped_column(Float, default=0.5)

    article: Mapped["Article"] = relationship(back_populates="score")


class Briefing(Base):
    """Generated briefing (daily/weekly/monthly)."""
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)  # daily, weekly, monthly
    start_date: Mapped[datetime.date] = mapped_column(nullable=False)
    end_date: Mapped[datetime.date] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )


class Entity(Base):
    """Named entities (people, companies, projects)."""
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # person, company, project, organization
    aliases: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # ai, crypto, web3, investor, regulator


# ===== Phase 3 Models =====

class Alert(Base):
    """Risk alerts and warnings."""
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)  # regulation_risk, investment_signal, hype_warning, narrative_shift, source_anomaly
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # critical, high, medium, low
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    related_articles: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # list of article_ids
    related_entities: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # list of entity names
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, acknowledged, resolved, expired
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    extra_data: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)


class Watchlist(Base):
    """Personalized watchlist items."""
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # watchlist name
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    watch_type: Mapped[str] = mapped_column(String(50), nullable=False)  # topic, entity, keyword, source
    watch_value: Mapped[str] = mapped_column(String(200), nullable=False)  # the thing being watched
    notify_on_match: Mapped[bool] = mapped_column(Boolean, default=True)
    min_score: Mapped[float] = mapped_column(Float, default=0.0)  # minimum score to trigger
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    last_triggered_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    match_count: Mapped[int] = mapped_column(Integer, default=0)


class AgentTask(Base):
    """Agent monitoring tasks."""
    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)  # monitor, investigate, verify, analyze
    target: Mapped[str] = mapped_column(String(500), nullable=False)  # what to monitor/investigate
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # LLM instructions
    schedule: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # cron or interval
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, paused, completed, failed
    last_run_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    extra_data: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)


class DiscoveredSource(Base):
    """Auto-discovered potential information sources."""
    __tablename__ = "discovered_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    discovered_from: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # where we found it
    category_guess: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, approved, rejected, added
    discovered_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    extra_data: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)


class FactCheck(Base):
    """Cross-source fact verification records."""
    __tablename__ = "fact_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim: Mapped[str] = mapped_column(Text, nullable=False)  # the claim being verified
    source_article_id: Mapped[int] = mapped_column(Integer, ForeignKey("articles.id"), nullable=False)
    supporting_articles: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # article_ids that support
    contradicting_articles: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # article_ids that contradict
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False)  # confirmed, contradicted, unverified, partially_confirmed
    confidence: Mapped[float] = mapped_column(Float, default=0.5)  # 0-1
    analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # LLM analysis
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)


# ===== Phase 4A Models - Membership System =====

class User(Base):
    """User accounts for membership system."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    membership_tier: Mapped[str] = mapped_column(String(20), default="free")  # free, pro, max
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    last_login_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    membership_expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    extra_data: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)
    # 4B-1: Email verification fields
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    verification_sent_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")
    payments: Mapped[list["Payment"]] = relationship(back_populates="user")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user")


class Membership(Base):
    """Membership records tracking tier changes."""
    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)  # free, pro, max
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, expired, cancelled, upgraded
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="memberships")


class Payment(Base):
    """Payment and subscription records."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    order_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)  # pro, max
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # amount in CNY
    payment_method: Mapped[str] = mapped_column(String(30), default="alipay")  # alipay, wechat, stripe
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, completed, cancelled, refunded
    payment_proof: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    paid_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    extra_data: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)

    user: Mapped["User"] = relationship(back_populates="payments")


class ApiKey(Base):
    """API keys for programmatic access (Max tier only)."""
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(100), default="default")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_keys")

class Coupon(Base):
    """Discount coupons for membership purchases."""
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    discount_type: Mapped[str] = mapped_column(String(20), nullable=False)  # percent, fixed
    discount_value: Mapped[float] = mapped_column(Float, nullable=False)  # percentage or CNY amount
    applicable_tiers: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # ["basic","pro","max"] or None=all
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # None=unlimited
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
