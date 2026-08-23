"""Trial system service - 7-day Pro free trial for new users."""
import datetime
import logging

from sqlalchemy.orm import Session
from app.models import User, Membership

logger = logging.getLogger(__name__)

TRIAL_DAYS = 7
TRIAL_TIER = "pro"


def activate_trial(user, db):
    """Activate 7-day Pro trial for a new user. Called during registration."""
    now = datetime.datetime.utcnow()
    trial_end = now + datetime.timedelta(days=TRIAL_DAYS)

    user.membership_tier = TRIAL_TIER
    user.membership_expires_at = trial_end

    extra = user.extra_data or {}
    extra["trial_started_at"] = now.isoformat()
    extra["trial_ends_at"] = trial_end.isoformat()
    extra["trial_used"] = True
    user.extra_data = extra

    trial_membership = Membership(
        user_id=user.id,
        tier=TRIAL_TIER,
        status="trial",
        started_at=now,
        expires_at=trial_end,
    )
    db.add(trial_membership)
    db.commit()

    logger.info(f"Trial activated for user {user.id} ({user.email}), expires {trial_end}")
    return {
        "trial_started": now.isoformat(),
        "trial_ends": trial_end.isoformat(),
        "tier": TRIAL_TIER,
        "days_remaining": TRIAL_DAYS,
    }


def check_expired_trials(db):
    """Check and downgrade users whose trials have expired. Called by scheduler hourly."""
    now = datetime.datetime.utcnow()

    expired_users = db.query(User).filter(
        User.membership_tier == TRIAL_TIER,
        User.membership_expires_at.isnot(None),
        User.membership_expires_at < now,
        User.is_active == True,
    ).all()

    downgraded = 0
    for user in expired_users:
        extra = user.extra_data or {}
        if not extra.get("trial_used"):
            continue
        if extra.get("trial_downgraded_at"):
            continue

        user.membership_tier = "free"
        user.membership_expires_at = None

        trial_record = db.query(Membership).filter(
            Membership.user_id == user.id,
            Membership.status == "trial",
        ).first()
        if trial_record:
            trial_record.status = "expired"

        free_membership = Membership(
            user_id=user.id,
            tier="free",
            status="active",
            started_at=now,
        )
        db.add(free_membership)

        extra["trial_downgraded_at"] = now.isoformat()
        user.extra_data = extra
        downgraded += 1
        logger.info(f"Trial expired for user {user.id} ({user.email}), downgraded to free")

    db.commit()
    return downgraded


def get_trial_status(user):
    """Get current trial status for a user."""
    extra = user.extra_data or {}

    if not extra.get("trial_used"):
        return {"has_trial": False, "active": False, "eligible": True}

    trial_end_str = extra.get("trial_ends_at")
    if not trial_end_str:
        return {"has_trial": True, "active": False, "eligible": False}

    trial_end = datetime.datetime.fromisoformat(trial_end_str)
    now = datetime.datetime.utcnow()

    is_active = now < trial_end and user.membership_tier == TRIAL_TIER
    days_remaining = max(0, (trial_end - now).days) if is_active else 0

    return {
        "has_trial": True,
        "active": is_active,
        "eligible": False,
        "started_at": extra.get("trial_started_at"),
        "ends_at": trial_end_str,
        "days_remaining": days_remaining,
        "tier": TRIAL_TIER if is_active else user.membership_tier,
    }
