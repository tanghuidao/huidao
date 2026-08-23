"""Authentication and authorization service."""
import datetime
import logging
import re
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_HOURS

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Email format validation regex
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


def is_valid_email(email: str) -> bool:
    """Validate email format."""
    if not email or len(email) > 200:
        return False
    return EMAIL_REGEX.match(email) is not None


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + (
        expires_delta or datetime.timedelta(hours=JWT_EXPIRE_HOURS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        logger.debug(f"JWT decode error: {e}")
        return None


def get_user_by_email(db: Session, email: str):
    """Look up a user by email."""
    from app.models import User
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int):
    """Look up a user by ID."""
    from app.models import User
    return db.query(User).filter(User.id == user_id).first()


def register_user(db: Session, email: str, password: str, display_name: str = ""):
    """Register a new user with free tier membership.

    Pro trial is NOT activated here - it activates after email verification.
    """
    from app.models import User, Membership

    # Validate email format
    if not is_valid_email(email):
        return None, "邮箱格式不正确"

    # Check if email already exists
    existing = get_user_by_email(db, email)
    if existing:
        return None, "该邮箱已注册"

    user = User(
        email=email,
        hashed_password=hash_password(password),
        display_name=display_name or email.split("@")[0],
        membership_tier="free",
        is_active=True,
        email_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create free membership (trial activates after email verification)
    membership = Membership(
        user_id=user.id,
        tier="free",
        status="active",
        started_at=datetime.datetime.utcnow(),
    )
    db.add(membership)
    db.commit()

    # Send welcome email (async, non-blocking)
    try:
        from app.services.email_verify import send_welcome_email
        import asyncio
        asyncio.get_event_loop().create_task(send_welcome_email(user.email, user.display_name))
    except Exception as e:
        logger.warning(f"Welcome email failed for {email}: {e}")

    logger.info(f"New user registered (free, pending verification): {email} (id={user.id})")
    return user, None


def activate_user_trial(user, db: Session):
    """Activate 7-day Pro trial for a verified user."""
    from app.services.trial import activate_trial
    try:
        trial_info = activate_trial(user, db)
        logger.info(f"Trial activated for {user.email}: {trial_info}")
        return True
    except Exception as e:
        logger.error(f"Trial activation failed for {user.email}: {e}")
        return False


def authenticate_user(db: Session, email: str, password: str):
    """Authenticate a user and return user object or None."""
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def check_membership_permission(user_tier: str, required_tier: str) -> bool:
    """Check if user tier meets the required tier level.

    Tier hierarchy: free < basic < pro < max
    """
    tier_levels = {"free": 0, "basic": 1, "pro": 2, "max": 3}
    user_level = tier_levels.get(user_tier, 0)
    required_level = tier_levels.get(required_tier, 0)
    return user_level >= required_level


def get_tier_limits(tier: str) -> dict:
    """Get usage limits for a membership tier."""
    limits = {
        "free": {
            "articles_per_day": 5,
            "briefing_access": False,
            "alert_access": False,
            "trend_access": False,
            "watchlist_items": 0,
            "agent_tasks": 0,
            "api_access": False,
            "export_access": False,
        },
        "basic": {
            "articles_per_day": -1,
            "briefing_access": False,
            "alert_access": False,
            "trend_access": True,
            "watchlist_items": 5,
            "agent_tasks": 0,
            "api_access": False,
            "export_access": False,
        },
        "pro": {
            "articles_per_day": -1,
            "briefing_access": True,
            "alert_access": True,
            "trend_access": True,
            "watchlist_items": 20,
            "agent_tasks": 5,
            "api_access": False,
            "export_access": True,
        },
        "max": {
            "articles_per_day": -1,
            "briefing_access": True,
            "alert_access": True,
            "trend_access": True,
            "watchlist_items": -1,
            "agent_tasks": -1,
            "api_access": True,
            "export_access": True,
        },
    }
    return limits.get(tier, limits["free"])
