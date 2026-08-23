"""Scheduler management and Phase 2 action router."""
from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
import tempfile
import os

from app.database import get_db
from app.services.middleware import get_current_user
from app.services.scheduler import (
    get_scheduler_status, pause_job, resume_job, remove_job
)
from app.services.pdf_parser import import_pdf_as_article, batch_import_pdf_urls
from app.services.language import batch_detect_languages, batch_translate_titles
from app.services.scraper import scrape_source
from app.models import Source

router = APIRouter(prefix="/api/v2", tags=["phase2"])


# --- Scheduler endpoints ---

@router.get("/scheduler/status")
def scheduler_status(user=Depends(get_current_user)):
    """Get scheduler status and all jobs."""
    return get_scheduler_status()


@router.post("/scheduler/pause/{job_id}")
def pause_scheduled_job(job_id: str, user=Depends(get_current_user)):
    """Pause a scheduled job."""
    success = pause_job(job_id)
    return {"success": success, "job_id": job_id, "action": "paused"}


@router.post("/scheduler/resume/{job_id}")
def resume_scheduled_job(job_id: str, user=Depends(get_current_user)):
    """Resume a paused job."""
    success = resume_job(job_id)
    return {"success": success, "job_id": job_id, "action": "resumed"}


@router.delete("/scheduler/{job_id}")
def delete_scheduled_job(job_id: str, user=Depends(get_current_user)):
    """Remove a scheduled job."""
    success = remove_job(job_id)
    return {"success": success, "job_id": job_id, "action": "removed"}


# --- Web Scraping endpoints ---

@router.post("/scrape")
async def trigger_scrape(source_ids: list[int] = None, db: Session = Depends(get_db)):
    """Manually trigger web scraping for specified or all web sources."""
    from app.services.classifier import classify_unclassified
    from app.services.scorer import score_unscored

    query = db.query(Source).filter(Source.source_type == "web", Source.enabled == True)
    if source_ids:
        query = query.filter(Source.id.in_(source_ids))

    sources = query.all()
    results = []

    for source in sources:
        try:
            result = await scrape_source(source, db)
            results.append(result)
        except Exception as e:
            results.append({"source_name": source.name, "new_articles": 0, "errors": [str(e)]})

    # Post-process
    classify_unclassified(db)
    score_unscored(db)

    return results


# --- PDF Import endpoints ---

@router.post("/pdf/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    source_name: str = Form("Manual PDF Import"),
    db: Session = Depends(get_db),
):
    """Upload and import a PDF file."""
    from app.config import DATA_DIR

    # Save uploaded file
    suffix = ".pdf"
    temp_path = os.path.join(str(DATA_DIR), f"upload_{file.filename}")
    with open(temp_path, "wb") as f:
        content = await file.read()
        f.write(content)

    try:
        article = import_pdf_as_article(db, pdf_path=temp_path, source_name=source_name)
        if article:
            # Classify and score
            from app.services.classifier import classify_article
            from app.services.scorer import score_article
            classify_article(article, db)
            article.classification = db.query(
                __import__('app.models', fromlist=['Classification']).Classification
            ).filter_by(article_id=article.id).first()
            score_article(article, db)

            return {"status": "success", "article_id": article.id, "title": article.title}
        else:
            return {"status": "failed", "error": "Could not parse PDF"}
    finally:
        # Cleanup
        try:
            os.unlink(temp_path)
        except Exception:
            pass


@router.post("/pdf/import-urls")
def import_pdf_urls(
    urls: list[str],
    source_name: str = "Research Reports",
    db: Session = Depends(get_db),
):
    """Import PDFs from URLs."""
    results = batch_import_pdf_urls(db, urls=urls, source_name=source_name)

    # Post-process imported articles
    from app.services.classifier import classify_unclassified
    from app.services.scorer import score_unscored
    classify_unclassified(db)
    score_unscored(db)

    return results


# --- Language endpoints ---

@router.post("/language/detect")
def detect_languages(limit: int = 100, db: Session = Depends(get_db)):
    """Run language detection on articles."""
    count = batch_detect_languages(db, limit=limit)
    return {"detected": count}


@router.post("/language/translate")
def translate_titles(limit: int = 50, db: Session = Depends(get_db)):
    """Translate non-Chinese article titles."""
    count = batch_translate_titles(db, limit=limit)
    return {"translated": count}


# --- Notification test ---

@router.post("/notify/test")
async def test_notification(message: str = "这是一条测试消息"):
    """Send a test notification to all configured channels."""
    from app.services.notifier import send_email, send_webhook, send_telegram
    import asyncio

    results = {}

    try:
        await send_webhook("🔔 测试通知", message)
        results["webhook"] = "sent"
    except Exception as e:
        results["webhook"] = f"error: {e}"

    try:
        await send_telegram(f"*🔔 测试通知*\n\n{message}")
        results["telegram"] = "sent"
    except Exception as e:
        results["telegram"] = f"error: {e}"

    try:
        await send_email("🔔 测试通知", message)
        results["email"] = "sent"
    except Exception as e:
        results["email"] = f"error: {e}"

    return results
