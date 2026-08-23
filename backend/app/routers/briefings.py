"""Briefing router."""
import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models import Briefing
from app.schemas import BriefingCreate, BriefingResponse
from app.services.briefing import generate_briefing

router = APIRouter(prefix="/api/briefings", tags=["briefings"])


@router.get("/", response_model=list[BriefingResponse])
def list_briefings(
    period_type: str = None,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """List recent briefings."""
    query = db.query(Briefing)
    if period_type:
        query = query.filter(Briefing.period_type == period_type)
    return query.order_by(desc(Briefing.created_at)).limit(limit).all()


@router.post("/generate", response_model=BriefingResponse)
def create_briefing(params: BriefingCreate, db: Session = Depends(get_db)):
    """Generate a new briefing."""
    briefing = generate_briefing(
        db=db,
        period_type=params.period_type,
        start_date=params.start_date,
        end_date=params.end_date,
    )
    return briefing


@router.get("/{briefing_id}", response_model=BriefingResponse)
def get_briefing(briefing_id: int, db: Session = Depends(get_db)):
    """Get a briefing by ID."""
    briefing = db.query(Briefing).filter(Briefing.id == briefing_id).first()
    if not briefing:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Briefing not found")
    return briefing
