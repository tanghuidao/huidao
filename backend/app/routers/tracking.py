"""Entity/People/Organization tracking router."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.tracker import (
    get_person_timeline,
    get_organization_timeline,
    get_people_leaderboard,
    get_org_leaderboard,
    get_opinion_shifts,
    TRACKED_PEOPLE,
    TRACKED_ORGANIZATIONS,
)

router = APIRouter(prefix="/api/tracking", tags=["tracking"])


@router.get("/people")
def list_tracked_people():
    """List all tracked people with their metadata."""
    return [
        {"name": name, **info}
        for name, info in TRACKED_PEOPLE.items()
    ]


@router.get("/organizations")
def list_tracked_organizations():
    """List all tracked organizations with their metadata."""
    return [
        {"name": name, **info}
        for name, info in TRACKED_ORGANIZATIONS.items()
    ]


@router.get("/people/leaderboard")
def people_leaderboard(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    """Get most mentioned people leaderboard."""
    return get_people_leaderboard(db, days=days)


@router.get("/organizations/leaderboard")
def org_leaderboard(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    """Get most mentioned organizations leaderboard."""
    return get_org_leaderboard(db, days=days)


@router.get("/person/{person_name}")
def person_timeline(person_name: str, days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db)):
    """Get timeline of articles mentioning a specific person."""
    return get_person_timeline(db, person_name=person_name, days=days)


@router.get("/organization/{org_name}")
def org_timeline(org_name: str, days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db)):
    """Get timeline of articles mentioning an organization."""
    return get_organization_timeline(db, org_name=org_name, days=days)


@router.get("/shifts/{entity_name}")
def opinion_shifts(entity_name: str, days: int = Query(30, ge=1, le=90), db: Session = Depends(get_db)):
    """Analyze opinion/narrative shifts for an entity over time."""
    return get_opinion_shifts(db, entity_name=entity_name, days=days)
