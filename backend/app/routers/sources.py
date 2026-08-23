"""Source management router."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.middleware import require_api_key
from app.models import Source
from app.schemas import SourceCreate, SourceUpdate, SourceResponse

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/", response_model=list[SourceResponse])
def list_sources(
    category: str = None,
    enabled: bool = None,
    db: Session = Depends(get_db),
):
    """List all sources with optional filters."""
    query = db.query(Source)
    if category:
        query = query.filter(Source.category == category)
    if enabled is not None:
        query = query.filter(Source.enabled == enabled)
    return query.order_by(Source.category, Source.name).all()


@router.post("/", response_model=SourceResponse)
def create_source(source: SourceCreate, db: Session = Depends(get_db), _admin=Depends(require_api_key)):
    """Create a new information source."""
    existing = db.query(Source).filter(Source.url == source.url).first()
    if existing:
        raise HTTPException(status_code=400, detail="Source with this URL already exists")
    
    db_source = Source(**source.model_dump())
    db.add(db_source)
    db.commit()
    db.refresh(db_source)
    return db_source


@router.get("/{source_id}", response_model=SourceResponse)
def get_source(source_id: int, db: Session = Depends(get_db)):
    """Get a source by ID."""
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.put("/{source_id}", response_model=SourceResponse)
def update_source(source_id: int, update: SourceUpdate, db: Session = Depends(get_db), _admin=Depends(require_api_key)):
    """Update a source."""
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    
    db.commit()
    db.refresh(source)
    return source


@router.delete("/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db), _admin=Depends(require_api_key)):
    """Delete a source."""
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    
    db.delete(source)
    db.commit()
    return {"detail": "Source deleted"}


@router.post("/batch", response_model=list[SourceResponse])
def batch_create_sources(sources: list[SourceCreate], db: Session = Depends(get_db), _admin=Depends(require_api_key)):
    """Batch create sources (skip duplicates)."""
    created = []
    for source_data in sources:
        existing = db.query(Source).filter(Source.url == source_data.url).first()
        if existing:
            continue
        db_source = Source(**source_data.model_dump())
        db.add(db_source)
        db.commit()
        db.refresh(db_source)
        created.append(db_source)
    return created
