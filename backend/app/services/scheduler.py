"""Scheduled task management using APScheduler."""
import logging
import asyncio
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from sqlalchemy.orm import Session

from app.config import SCHEDULER_COLLECT_INTERVAL_MINUTES, SCHEDULER_ENABLED
from app.database import SessionLocal

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the scheduler instance."""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={"coalesce": True, "max_instances": 1},
        )
    return scheduler


async def job_collect_all():
    """Scheduled job: collect from all enabled sources."""
    logger.info("[Scheduler] Starting scheduled collection...")
    db = SessionLocal()
    try:
        from app.services.collector import collect_all
        from app.services.scraper import scrape_source
        from app.services.classifier import classify_unclassified
        from app.services.scorer import score_unscored
        from app.services.language import batch_detect_languages
        from app.services.summarizer import summarize_batch
        from app.models import Source

        # RSS collection
        results = await collect_all(db)
        total_new = sum(r["new_articles"] for r in results)

        # Web scraping for web-type sources
        web_sources = db.query(Source).filter(
            Source.enabled == True,
            Source.source_type == "web",
        ).all()
        for source in web_sources:
            try:
                result = await scrape_source(source, db)
                total_new += result["new_articles"]
            except Exception as e:
                logger.error(f"[Scheduler] Scrape error for {source.name}: {e}")

        # Post-processing
        classified = classify_unclassified(db)
        scored = score_unscored(db)
        lang_detected = batch_detect_languages(db)
        summarized = summarize_batch(db, limit=80)

        logger.info(
            f"[Scheduler] Done: {total_new} new articles, "
            f"{classified} classified, {scored} scored, "
            f"{lang_detected} languages detected, {summarized} summarized"
        )

        # Trigger notifications if there are important articles
        if total_new > 0:
            try:
                from app.services.notifier import notify_new_articles
                await notify_new_articles(db, total_new)
            except Exception as e:
                logger.error(f"[Scheduler] Notification error: {e}")

    except Exception as e:
        logger.error(f"[Scheduler] Collection job error: {e}")
    finally:
        db.close()


async def job_daily_briefing():
    """Scheduled job: generate daily briefing."""
    logger.info("[Scheduler] Generating daily briefing...")
    db = SessionLocal()
    try:
        from app.services.briefing import generate_briefing
        briefing = generate_briefing(db, period_type="daily")
        logger.info(f"[Scheduler] Daily briefing generated: {briefing.title}")

        # Send briefing notification
        try:
            from app.services.notifier import notify_briefing
            await notify_briefing(db, briefing)
        except Exception as e:
            logger.error(f"[Scheduler] Briefing notification error: {e}")

    except Exception as e:
        logger.error(f"[Scheduler] Briefing job error: {e}")
    finally:
        db.close()


async def job_weekly_briefing():
    """Scheduled job: generate weekly briefing."""
    logger.info("[Scheduler] Generating weekly briefing...")
    db = SessionLocal()
    try:
        from app.services.briefing import generate_briefing
        briefing = generate_briefing(db, period_type="weekly")
        logger.info(f"[Scheduler] Weekly briefing generated: {briefing.title}")

        try:
            from app.services.notifier import notify_briefing
            await notify_briefing(db, briefing)
        except Exception as e:
            logger.error(f"[Scheduler] Briefing notification error: {e}")

    except Exception as e:
        logger.error(f"[Scheduler] Weekly briefing job error: {e}")
    finally:
        db.close()



async def job_trial_expiry():
    """Scheduled job: check and downgrade expired trials."""
    logger.info("[Scheduler] Checking expired trials...")
    db = SessionLocal()
    try:
        from app.services.trial import check_expired_trials
        count = check_expired_trials(db)
        if count > 0:
            logger.info(f"[Scheduler] Downgraded {count} expired trials")
    except Exception as e:
        logger.error(f"[Scheduler] Trial expiry check error: {e}")
    finally:
        db.close()



async def job_order_expiry():
    """Scheduled job: cancel expired pending orders."""
    db = SessionLocal()
    try:
        from app.services.payment_service import cancel_expired_orders
        count = cancel_expired_orders(db)
        if count > 0:
            logger.info(f"[Scheduler] Cancelled {count} expired orders")
    except Exception as e:
        logger.error(f"[Scheduler] Order expiry error: {e}")
    finally:
        db.close()



async def job_trial_reminder():
    """Scheduled job: send trial expiry reminders."""
    logger.info("[Scheduler] Sending trial expiry reminders...")
    db = SessionLocal()
    try:
        from app.services.email_marketing import send_trial_expiring_soon
        count = await send_trial_expiring_soon(db)
        if count > 0:
            logger.info(f"[Scheduler] Sent {count} trial reminders")
    except Exception as e:
        logger.error(f"[Scheduler] Trial reminder error: {e}")
    finally:
        db.close()


async def job_weekly_newsletter():
    """Scheduled job: send weekly newsletter to paid users."""
    logger.info("[Scheduler] Sending weekly newsletter...")
    db = SessionLocal()
    try:
        from app.services.email_marketing import send_weekly_newsletter
        count = await send_weekly_newsletter(db)
        logger.info(f"[Scheduler] Newsletter sent to {count} users")
    except Exception as e:
        logger.error(f"[Scheduler] Newsletter error: {e}")
    finally:
        db.close()


def init_scheduler():
    """Initialize and start the scheduler with default jobs."""
    if not SCHEDULER_ENABLED:
        logger.info("[Scheduler] Disabled by configuration")
        return

    sched = get_scheduler()

    # Job 1: Collect every N minutes
    sched.add_job(
        job_collect_all,
        trigger=IntervalTrigger(minutes=SCHEDULER_COLLECT_INTERVAL_MINUTES),
        id="collect_all",
        name="Collect from all sources",
        replace_existing=True,
    )

    # Job 2: Daily briefing at 8:00 AM (UTC)
    sched.add_job(
        job_daily_briefing,
        trigger=CronTrigger(hour=8, minute=0),
        id="daily_briefing",
        name="Generate daily briefing",
        replace_existing=True,
    )

    # Job 3: Weekly briefing on Monday at 9:00 AM (UTC)
    sched.add_job(
        job_weekly_briefing,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_briefing",
        name="Generate weekly briefing",
        replace_existing=True,
    )

    # Job 4: Check trial expiry every hour
    sched.add_job(
        job_trial_expiry,
        trigger=IntervalTrigger(hours=1),
        id="trial_expiry",
        name="Check trial expiry",
        replace_existing=True,
    )

    # Job 5: Cancel expired orders every 5 minutes
    sched.add_job(
        job_order_expiry,
        trigger=IntervalTrigger(minutes=5),
        id="order_expiry",
        name="Cancel expired orders",
        replace_existing=True,
    )

    # Job 6: Trial expiry reminder daily at 10:00 UTC
    sched.add_job(
        job_trial_reminder,
        trigger=CronTrigger(hour=10, minute=0),
        id="trial_reminder",
        name="Trial expiry reminder",
        replace_existing=True,
    )

    # Job 7: Weekly newsletter on Monday at 10:30 UTC
    sched.add_job(
        job_weekly_newsletter,
        trigger=CronTrigger(day_of_week="mon", hour=10, minute=30),
        id="weekly_newsletter",
        name="Weekly newsletter",
        replace_existing=True,
    )

    sched.start()
    logger.info(
        f"[Scheduler] Started with collect interval={SCHEDULER_COLLECT_INTERVAL_MINUTES}min, "
        f"daily briefing at 08:00 UTC, weekly briefing on Mon 09:00 UTC, "
        f"trial expiry check every 1h"
    )


def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Shutdown complete")


def get_scheduler_status() -> dict:
    """Get current scheduler status and jobs."""
    sched = get_scheduler()
    jobs = []
    if sched.running:
        for job in sched.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            })

    return {
        "running": sched.running if sched else False,
        "jobs": jobs,
    }


def add_custom_job(job_id: str, cron_expr: str, job_func, name: str = ""):
    """Add a custom scheduled job."""
    sched = get_scheduler()
    parts = cron_expr.split()
    if len(parts) == 5:
        trigger = CronTrigger(
            minute=parts[0], hour=parts[1],
            day=parts[2], month=parts[3], day_of_week=parts[4]
        )
    else:
        raise ValueError(f"Invalid cron expression: {cron_expr}")

    sched.add_job(
        job_func,
        trigger=trigger,
        id=job_id,
        name=name or job_id,
        replace_existing=True,
    )


def remove_job(job_id: str) -> bool:
    """Remove a scheduled job."""
    sched = get_scheduler()
    try:
        sched.remove_job(job_id)
        return True
    except Exception:
        return False


def pause_job(job_id: str) -> bool:
    """Pause a scheduled job."""
    sched = get_scheduler()
    try:
        sched.pause_job(job_id)
        return True
    except Exception:
        return False


def resume_job(job_id: str) -> bool:
    """Resume a paused job."""
    sched = get_scheduler()
    try:
        sched.resume_job(job_id)
        return True
    except Exception:
        return False
