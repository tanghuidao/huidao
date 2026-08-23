"""Seed default information sources."""
from sqlalchemy.orm import Session
from app.models import Source


DEFAULT_SOURCES = [
    # Crypto / Web3 行业媒体
    {"name": "CoinDesk", "category": "crypto_media", "region": "US", "credibility_score": 0.8, "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "source_type": "rss"},
    {"name": "The Block", "category": "crypto_media", "region": "US", "credibility_score": 0.8, "url": "https://www.theblock.co/rss.xml", "source_type": "rss"},
    {"name": "Decrypt", "category": "crypto_media", "region": "US", "credibility_score": 0.75, "url": "https://decrypt.co/feed", "source_type": "rss"},
    {"name": "CryptoSlate", "category": "crypto_media", "region": "US", "credibility_score": 0.7, "url": "https://cryptoslate.com/feed/", "source_type": "rss"},
    {"name": "Cointelegraph", "category": "crypto_media", "region": "global", "credibility_score": 0.7, "url": "https://cointelegraph.com/rss", "source_type": "rss"},

    # AI 行业媒体
    {"name": "VentureBeat AI", "category": "ai_media", "region": "US", "credibility_score": 0.8, "url": "https://venturebeat.com/category/ai/feed/", "source_type": "rss"},
    {"name": "MIT Technology Review", "category": "ai_media", "region": "US", "credibility_score": 0.9, "url": "https://www.technologyreview.com/feed/", "source_type": "rss"},

    # 主流媒体 (Tech sections)
    {"name": "TechCrunch", "category": "mainstream_media", "region": "US", "credibility_score": 0.85, "url": "https://techcrunch.com/feed/", "source_type": "rss"},
    {"name": "The Verge", "category": "mainstream_media", "region": "US", "credibility_score": 0.8, "url": "https://www.theverge.com/rss/index.xml", "source_type": "rss"},
    {"name": "Wired", "category": "mainstream_media", "region": "US", "credibility_score": 0.85, "url": "https://www.wired.com/feed/rss", "source_type": "rss"},
    {"name": "Ars Technica", "category": "mainstream_media", "region": "US", "credibility_score": 0.85, "url": "https://feeds.arstechnica.com/arstechnica/technology-lab", "source_type": "rss"},

    # 机构和研究
    {"name": "a16z Crypto", "category": "institution", "region": "US", "credibility_score": 0.85, "url": "https://a16zcrypto.com/feed/", "source_type": "rss"},
    {"name": "Messari", "category": "institution", "region": "US", "credibility_score": 0.8, "url": "https://messari.io/rss", "source_type": "rss"},

    # 企业官方
    {"name": "Ethereum Blog", "category": "enterprise", "region": "global", "credibility_score": 0.9, "url": "https://blog.ethereum.org/feed.xml", "source_type": "rss"},
    {"name": "Solana News", "category": "enterprise", "region": "global", "credibility_score": 0.85, "url": "https://solana.com/news/rss.xml", "source_type": "rss"},
    {"name": "Coinbase Blog", "category": "enterprise", "region": "US", "credibility_score": 0.85, "url": "https://www.coinbase.com/blog/rss.xml", "source_type": "rss"},

    # 监管相关
    {"name": "SEC Press Releases", "category": "regulation", "region": "US", "credibility_score": 0.95, "url": "https://www.sec.gov/news/pressreleases.rss", "source_type": "rss"},
]


def seed_if_empty(db: Session):
    """Seed default sources if the database is empty."""
    count = db.query(Source).count()
    if count > 0:
        return

    for source_data in DEFAULT_SOURCES:
        source = Source(**source_data)
        db.add(source)

    db.commit()
    print(f"Seeded {len(DEFAULT_SOURCES)} default sources.")
