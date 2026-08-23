"""Phase 3 Router - Advanced intelligence, alerts, agents, and watchlists."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

from app.database import get_db
from app.services.middleware import get_current_user

router = APIRouter(prefix="/api/v3", tags=["phase3"])


# --- Pydantic schemas ---

class WatchlistCreate(BaseModel):
    name: str
    watch_type: str  # topic, entity, keyword, source
    watch_value: str
    description: str = None
    notify_on_match: bool = True
    min_score: float = 0.0


class WatchlistUpdate(BaseModel):
    name: str = None
    watch_value: str = None
    description: str = None
    notify_on_match: bool = None
    min_score: float = None
    enabled: bool = None


class AgentTaskCreate(BaseModel):
    name: str
    task_type: str  # monitor, investigate, verify, analyze
    target: str
    instructions: str = None
    schedule: str = None
    template: str = None  # monitor_topic, investigate_entity, verify_narrative, risk_assessment


class NarrativeQuery(BaseModel):
    topic: str
    days: int = 30


# ========== ALERTS ==========

@router.get("/alerts")
def list_alerts(limit: int = 50, db: Session = Depends(get_db)):
    """Get all active alerts (public read-only)."""
    from app.services.alerts import get_active_alerts
    alerts = get_active_alerts(db, limit=limit)
    return {"alerts": alerts, "count": len(alerts)}


@router.post("/alerts/scan")
def scan_for_alerts(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Run all alert checks and generate new alerts."""
    from app.services.alerts import run_all_checks
    result = run_all_checks(db)
    return result


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Mark an alert as acknowledged."""
    from app.services.alerts import acknowledge_alert as _ack
    success = _ack(db, alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"success": True, "alert_id": alert_id, "status": "acknowledged"}


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Mark an alert as resolved."""
    from app.services.alerts import resolve_alert as _resolve
    success = _resolve(db, alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"success": True, "alert_id": alert_id, "status": "resolved"}


# ========== NARRATIVE STRENGTH ==========

@router.post("/narrative/analyze")
def analyze_narrative(query: NarrativeQuery, db: Session = Depends(get_db)):
    """Analyze narrative strength for a topic."""
    from app.services.narrative import analyze_narrative_strength
    result = analyze_narrative_strength(db, topic=query.topic, days=query.days)
    return result


@router.get("/narrative/leaderboard")
def narrative_leaderboard(days: int = 14, top_n: int = 20, db: Session = Depends(get_db)):
    """Get top narratives ranked by strength."""
    from app.services.narrative import get_narrative_leaderboard
    rankings = get_narrative_leaderboard(db, days=days, top_n=top_n)
    return {"rankings": rankings, "days": days}


@router.get("/narrative/llm-analysis")
def narrative_llm_analysis(topic: str, days: int = 14, db: Session = Depends(get_db)):
    """Get LLM-powered qualitative narrative analysis."""
    from app.services.narrative import get_llm_narrative_analysis
    analysis = get_llm_narrative_analysis(db, topic=topic, days=days)
    return {"topic": topic, "analysis": analysis}


# ========== FACT CHECKING ==========

@router.post("/fact-check/{article_id}")
def verify_article(article_id: int, db: Session = Depends(get_db)):
    """Verify an article by cross-referencing with other sources."""
    from app.services.fact_checker import verify_article as _verify
    result = _verify(db, article_id=article_id)
    return result


@router.post("/fact-check/batch")
def batch_verify(days: int = 3, limit: int = 20, db: Session = Depends(get_db)):
    """Run batch fact-checking on recent high-importance articles."""
    from app.services.fact_checker import batch_verify as _batch
    results = _batch(db, days=days, limit=limit)
    return {"verified": len(results), "results": results}


@router.get("/fact-checks")
def list_fact_checks(limit: int = 30, db: Session = Depends(get_db)):
    """List recent fact check records."""
    from app.models import FactCheck
    from sqlalchemy import desc
    checks = db.query(FactCheck).order_by(desc(FactCheck.created_at)).limit(limit).all()
    return {
        "fact_checks": [
            {
                "id": fc.id,
                "claim": fc.claim,
                "source_article_id": fc.source_article_id,
                "verification_status": fc.verification_status,
                "confidence": fc.confidence,
                "analysis": fc.analysis,
                "supporting_articles": fc.supporting_articles,
                "contradicting_articles": fc.contradicting_articles,
                "created_at": fc.created_at.isoformat() if fc.created_at else None,
            }
            for fc in checks
        ]
    }


# ========== SOURCE DISCOVERY ==========

@router.get("/discovery/pending")
def get_pending_sources(limit: int = 30, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Get pending discovered sources for review."""
    from app.services.discovery import get_pending_discoveries
    sources = get_pending_discoveries(db, limit=limit)
    return {"pending_sources": sources, "count": len(sources)}


@router.post("/discovery/scan")
def scan_for_sources(limit: int = 200, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Scan existing articles to discover new potential sources."""
    from app.services.discovery import discover_from_articles
    results = discover_from_articles(db, limit=limit)
    return {"discovered": len(results), "sources": results}


@router.post("/discovery/{source_id}/approve")
def approve_source(source_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Approve a discovered source and add it to the main source list."""
    from app.services.discovery import approve_discovered_source
    source = approve_discovered_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Discovered source not found or already processed")
    return {"success": True, "source_id": source.id, "name": source.name, "url": source.url}


@router.post("/discovery/{source_id}/reject")
def reject_source(source_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Reject a discovered source."""
    from app.services.discovery import reject_discovered_source
    success = reject_discovered_source(db, source_id)
    if not success:
        raise HTTPException(status_code=404, detail="Discovered source not found")
    return {"success": True, "source_id": source_id, "status": "rejected"}


# ========== AGENT TASKS ==========

@router.get("/agents/templates")
def get_templates():
    """Get available agent task templates."""
    from app.services.agent import get_agent_templates
    return {"templates": get_agent_templates()}


@router.get("/agents/tasks")
def list_tasks(status: str = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """List all agent tasks, optionally filtered by status."""
    from app.services.agent import list_agent_tasks
    tasks = list_agent_tasks(db, status=status)
    return {"tasks": tasks, "count": len(tasks)}


@router.post("/agents/tasks")
def create_task(params: AgentTaskCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Create a new agent monitoring task."""
    from app.services.agent import create_agent_task
    task = create_agent_task(
        db,
        name=params.name,
        task_type=params.task_type,
        target=params.target,
        instructions=params.instructions,
        schedule=params.schedule,
        template=params.template,
    )
    return {
        "id": task.id,
        "name": task.name,
        "task_type": task.task_type,
        "target": task.target,
        "status": task.status,
    }


@router.post("/agents/tasks/{task_id}/execute")
def execute_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Execute an agent task and return results."""
    from app.services.agent import execute_agent_task
    result = execute_agent_task(db, task_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/agents/tasks/{task_id}/pause")
def pause_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Pause an agent task."""
    from app.services.agent import pause_agent_task
    success = pause_agent_task(db, task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or not active")
    return {"success": True, "task_id": task_id, "status": "paused"}


@router.post("/agents/tasks/{task_id}/resume")
def resume_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Resume a paused agent task."""
    from app.services.agent import resume_agent_task
    success = resume_agent_task(db, task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or not paused")
    return {"success": True, "task_id": task_id, "status": "active"}


@router.delete("/agents/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    """Delete an agent task."""
    from app.services.agent import delete_agent_task
    success = delete_agent_task(db, task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"success": True, "task_id": task_id, "action": "deleted"}


# ========== WATCHLIST ==========

@router.get("/watchlist")
def list_watchlist(enabled_only: bool = True, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Get all watchlist items."""
    from app.services.watchlist import get_watchlist
    items = get_watchlist(db, enabled_only=enabled_only)
    return {"watchlist": items, "count": len(items)}


@router.post("/watchlist")
def create_watchlist(params: WatchlistCreate, db: Session = Depends(get_db)):
    """Create a new watchlist item."""
    from app.services.watchlist import create_watchlist_item
    item = create_watchlist_item(
        db,
        name=params.name,
        watch_type=params.watch_type,
        watch_value=params.watch_value,
        description=params.description,
        notify_on_match=params.notify_on_match,
        min_score=params.min_score,
    )
    return {
        "id": item.id,
        "name": item.name,
        "watch_type": item.watch_type,
        "watch_value": item.watch_value,
        "enabled": item.enabled,
    }


@router.put("/watchlist/{item_id}")
def update_watchlist(item_id: int, params: WatchlistUpdate, db: Session = Depends(get_db)):
    """Update a watchlist item."""
    from app.services.watchlist import update_watchlist_item
    updates = {k: v for k, v in params.dict().items() if v is not None}
    item = update_watchlist_item(db, item_id, **updates)
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return {"success": True, "id": item.id, "name": item.name}


@router.delete("/watchlist/{item_id}")
def remove_watchlist(item_id: int, db: Session = Depends(get_db)):
    """Delete a watchlist item."""
    from app.services.watchlist import delete_watchlist_item
    success = delete_watchlist_item(db, item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return {"success": True, "item_id": item_id, "action": "deleted"}


@router.get("/watchlist/{item_id}/feed")
def watchlist_feed(item_id: int, days: int = 7, limit: int = 50, db: Session = Depends(get_db)):
    """Get personalized feed for a watchlist item."""
    from app.services.watchlist import get_watchlist_feed
    result = get_watchlist_feed(db, item_id=item_id, days=days, limit=limit)
    return result


@router.post("/watchlist/check")
def check_matches(hours: int = 24, db: Session = Depends(get_db)):
    """Check all watchlist items for new matches."""
    from app.services.watchlist import check_watchlist_matches
    matches = check_watchlist_matches(db, hours=hours)
    return {"matches": matches, "total_matches": sum(m.get("new_matches", 0) for m in matches)}


# ========== COMBINED INTELLIGENCE ==========

@router.get("/intelligence/summary")
def intelligence_summary(db: Session = Depends(get_db)):
    """Get a combined Phase 3 intelligence summary."""
    from app.services.alerts import get_active_alerts
    from app.services.narrative import get_narrative_leaderboard
    from app.services.discovery import get_pending_discoveries
    from app.services.agent import list_agent_tasks
    from app.services.watchlist import get_watchlist
    from app.models import FactCheck
    from sqlalchemy import desc

    alerts = get_active_alerts(db, limit=10)
    top_narratives = get_narrative_leaderboard(db, days=7, top_n=5)
    pending_sources = get_pending_discoveries(db, limit=5)
    active_tasks = list_agent_tasks(db, status="active")
    watchlist = get_watchlist(db, enabled_only=True)
    recent_checks = db.query(FactCheck).order_by(desc(FactCheck.created_at)).limit(5).all()

    alert_dicts = []
    for a in alerts:
        alert_dicts.append({
            "id": a.id,
            "type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "created_at": str(a.created_at) if a.created_at else None,
        })
    return {
        "alerts_summary": {
            "active_count": len(alerts),
            "critical": len([a for a in alerts if a.severity == "critical"]),
            "recent": alert_dicts[:5],
        },
        "narrative_summary": {
            "top_narratives": top_narratives[:5],
        },
        "discovery_summary": {
            "pending_count": len(pending_sources),
            "recent": [
                {"id": getattr(s, "id", None), "url": getattr(s, "url", str(s))}
                for s in pending_sources[:3]
            ],
        },
        "agent_summary": {
            "active_tasks": len(active_tasks),
            "tasks": [
                {"id": t.id if hasattr(t, "id") else t.get("id"),
                 "name": t.name if hasattr(t, "name") else t.get("name"),
                 "status": t.status if hasattr(t, "status") else t.get("status")}
                for t in active_tasks[:5]
            ],
        },
        "watchlist_summary": {
            "item_count": len(watchlist),
            "items": [
                {"id": w.id if hasattr(w, "id") else w.get("id"),
                 "name": w.name if hasattr(w, "name") else w.get("name"),
                 "watch_type": w.watch_type if hasattr(w, "watch_type") else w.get("watch_type")}
                for w in watchlist[:5]
            ],
        },
        "fact_check_summary": {
            "recent_count": len(recent_checks),
            "results": [
                {"id": fc.id, "status": fc.verification_status, "confidence": fc.confidence}
                for fc in recent_checks
            ],
        },
    }
