"""Pydantic schemas for API request/response."""
import datetime
from typing import Optional
from pydantic import BaseModel


# --- Source Schemas ---

class SourceCreate(BaseModel):
    name: str
    category: str
    region: str = "global"
    credibility_score: float = 0.7
    url: str
    source_type: str = "rss"
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    region: Optional[str] = None
    credibility_score: Optional[float] = None
    url: Optional[str] = None
    source_type: Optional[str] = None
    enabled: Optional[bool] = None


class SourceResponse(BaseModel):
    id: int
    name: str
    category: str
    region: str
    credibility_score: float
    url: str
    source_type: str
    enabled: bool
    last_checked_at: Optional[datetime.datetime] = None
    health_status: str

    class Config:
        from_attributes = True


# --- Article Schemas ---

class ClassificationResponse(BaseModel):
    content_type: str
    tags: Optional[list] = None
    entities: Optional[list] = None
    topics: Optional[list] = None
    hype_risk: float = 0.0
    regulation_risk: float = 0.0

    class Config:
        from_attributes = True


class ScoreResponse(BaseModel):
    credibility: float
    impact: float
    execution: float
    capital_signal: float
    narrative_strength: float
    risk: float
    total_score: float

    class Config:
        from_attributes = True


class ArticleResponse(BaseModel):
    id: int
    source_id: int
    title: str
    url: str
    author: Optional[str] = None
    published_at: Optional[datetime.datetime] = None
    fetched_at: datetime.datetime
    summary: Optional[str] = None
    one_line_summary: Optional[str] = None
    language: str
    classification: Optional[ClassificationResponse] = None
    score: Optional[ScoreResponse] = None

    class Config:
        from_attributes = True


class ArticleListResponse(BaseModel):
    total: int
    articles: list[ArticleResponse]


# --- Briefing Schemas ---

class BriefingCreate(BaseModel):
    period_type: str = "daily"  # daily, weekly, monthly
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None


class BriefingResponse(BaseModel):
    id: int
    period_type: str
    start_date: datetime.date
    end_date: datetime.date
    title: str
    content: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True


# --- Dashboard Schemas ---

class DashboardStats(BaseModel):
    total_sources: int
    active_sources: int
    healthy_sources: int
    total_articles: int
    articles_today: int
    articles_this_week: int
    total_briefings: int
    last_updated: Optional[datetime.datetime] = None


class TopicCount(BaseModel):
    topic: str
    count: int


class EntityCount(BaseModel):
    name: str
    type: str
    count: int


class DashboardData(BaseModel):
    stats: DashboardStats
    recent_articles: list[ArticleResponse]
    hot_topics: list[TopicCount]
    top_entities: list[EntityCount]
    high_risk_articles: list[ArticleResponse]
    suspected_hype: list[ArticleResponse]


# --- Collect Schemas ---

class CollectRequest(BaseModel):
    source_ids: Optional[list[int]] = None  # None means collect all enabled


class CollectResult(BaseModel):
    source_name: str
    new_articles: int
    errors: list[str]


class SummarizeRequest(BaseModel):
    article_ids: Optional[list[int]] = None  # None means summarize all unsummarized
    limit: int = 20
