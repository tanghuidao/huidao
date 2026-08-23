"""Database connection and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import DATABASE_URL

# Build engine args based on database type
_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    echo=False,
    pool_pre_ping=True,  # Reconnect stale connections (important for PostgreSQL)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables."""
    from app.models import (  # noqa
        Source, Article, Classification, Score, Briefing, Entity,
        Alert, Watchlist, AgentTask, DiscoveredSource, FactCheck,
        User, Membership, Payment, ApiKey,
    )
    Base.metadata.create_all(bind=engine)
