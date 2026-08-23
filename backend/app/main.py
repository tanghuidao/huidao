"""FastAPI application entry point with 4B-1 security enhancements."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.responses import PlainTextResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.routers import sources, articles, briefings, dashboard
from app.routers import trends, tracking, phase2
from app.routers import phase3
from app.routers import feeds, api_v1
from app.schemas import CollectRequest, CollectResult, SummarizeRequest
from app.services.collector import collect_all
from app.services.classifier import classify_unclassified
from app.services.scorer import score_unscored
from app.services.summarizer import summarize_batch

# 4B-1: Rate limiter middleware
from app.services.rate_limiter import RateLimiterMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init DB on startup, start scheduler."""
    logger.info("Initializing database...")
    init_db()
    logger.info("Database ready.")

    from app.seed_sources import seed_if_empty
    db = next(get_db())
    seed_if_empty(db)
    db.close()

    try:
        from app.services.scheduler import init_scheduler
        init_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler init failed (non-critical): {e}")

    yield

    try:
        from app.services.scheduler import shutdown_scheduler
        shutdown_scheduler()
    except Exception:
        pass


# === Create App (docs disabled in production) ===
app = FastAPI(
    title="AI + Crypto / Web3 / Web4",
    description="Monitor global AI + Crypto, Web3, Web4.0 trends from multiple sources",
    version="4.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# === CORS (restricted to huidao.cc) ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://huidao.cc", "https://www.huidao.cc", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === 4B-1: Rate limiter ===
app.add_middleware(RateLimiterMiddleware)


# === Security Headers Middleware ===
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "img-src 'self' data: https:; "
        "font-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "connect-src 'self' https://huidao.cc"
    )
    if "server" in response.headers:
        del response.headers["server"]
    return response


# === SEO Endpoints ===
@app.get("/robots.txt")
async def robots_txt():
    content = """User-agent: *
Allow: /
Disallow: /api/

Sitemap: https://huidao.cc/sitemap.xml
"""
    return PlainTextResponse(content)


@app.get("/llms.txt")
async def llms_txt():
    content = """# huidao.cc

> AI驱动的Web4.0全球智库：实时监控60+全球信息源，通过AI进行智能分类、风险预警、趋势分析，并生成每日/每周简报。全站内容免费开放，遵循 CC BY 4.0 协议。

## 关于
huidao.cc 面向 AI、Crypto、Web3、Web4.0 领域，持续采集全球公开信息源，用AI模型对内容分类、评分、识别高风险与疑似炒作信息，追踪热门话题与新兴话题的增长趋势，并对关键人物与机构的观点进行追踪。无需注册或登录，全部功能免费使用。

## 核心功能
- 总览仪表盘：信息源规模、今日/本周动态、活跃预警统计
- 趋势分析：热门话题、新兴话题增长率
- 智能分析：风险预警、叙事强度评分、观点追踪
- 简报：AI生成的每日/每周简报

## 可抓取的内容入口
- 文章库（AI摘要 + 原文链接，纯HTML可直接抓取）: https://huidao.cc/a
- 单篇文章固定链接: https://huidao.cc/a/{id}
- 智能简报列表: https://huidao.cc/b
- 单份简报固定链接: https://huidao.cc/b/{id}
- 关于与方法论: https://huidao.cc/about
- 站点地图（含全部可索引页面）: https://huidao.cc/sitemap.xml

## 机器可读数据出口
- RSS 简报订阅: https://huidao.cc/rss/briefing.xml
- RSS 风险预警订阅: https://huidao.cc/rss/alerts.xml
- 公开 JSON API（文章列表，支持 category/tag/date_from/date_to/limit/offset 参数，限流 60次/分钟/IP）: https://huidao.cc/api/v1/articles

## 引用方式
引用本站内容时请注明"huidao.cc"并保留对应的固定链接（/a/编号 或 /b/编号）。文章的AI摘要基于原文生成，每篇文章页均附原文出处链接。本站内容遵循 CC BY 4.0 协议，转载与二次创作须署名并注明链接。

## 联系方式
- GitHub Issues: https://github.com/tanghuidao/huidao/issues
"""
    return PlainTextResponse(content)


# sitemap.xml is served dynamically by app.routers.seo


# === Mount Frontend ===
import os
from pathlib import Path
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

# === Routers ===
# SEO/GEO server-rendered pages (/a, /b, /about, /sitemap.xml)
from app.routers import seo
app.include_router(seo.router)

# Phase 1
app.include_router(sources.router)
app.include_router(articles.router)
app.include_router(briefings.router)
app.include_router(dashboard.router)

# Phase 2
app.include_router(trends.router)
app.include_router(tracking.router)
app.include_router(phase2.router)

# Phase 3
app.include_router(phase3.router)

# Public data feeds & open API
app.include_router(feeds.router)
app.include_router(api_v1.router)


# === Action Endpoints ===

@app.post("/api/collect", response_model=list[CollectResult])
async def trigger_collection(params: CollectRequest, db: Session = Depends(get_db)):
    """Manually trigger content collection from all source types."""
    results = await collect_all(db, source_ids=params.source_ids)

    from app.services.scraper import scrape_source
    from app.models import Source

    web_query = db.query(Source).filter(Source.source_type == "web", Source.enabled == True)
    if params.source_ids:
        web_query = web_query.filter(Source.id.in_(params.source_ids))
    web_sources = web_query.all()

    for source in web_sources:
        try:
            result = await scrape_source(source, db)
            results.append(CollectResult(**result))
        except Exception as e:
            results.append(CollectResult(
                source_name=source.name, new_articles=0, errors=[str(e)]
            ))

    classified = classify_unclassified(db)
    scored = score_unscored(db)
    from app.services.language import batch_detect_languages
    lang_detected = batch_detect_languages(db)
    summarized = summarize_batch(db, limit=30)

    logger.info(
        f"Collected, classified {classified}, scored {scored}, "
        f"detected {lang_detected} languages, summarized {summarized}"
    )
    return results


@app.post("/api/summarize")
async def trigger_summarize(params: SummarizeRequest, db: Session = Depends(get_db)):
    """Manually trigger LLM summarization."""
    count = summarize_batch(db, article_ids=params.article_ids, limit=params.limit)
    return {"summarized": count}


@app.get("/")
async def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/api/health")
async def health_check():
    from app.services.scheduler import get_scheduler_status
    sched_status = get_scheduler_status()
    return {"status": "ok", "version": "4.0.0", "scheduler": sched_status}
