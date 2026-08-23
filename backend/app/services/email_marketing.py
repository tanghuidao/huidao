"""Email marketing service - trial reminders and newsletters."""
import datetime
import logging

from sqlalchemy.orm import Session
from app.models import User, Article, Briefing

logger = logging.getLogger(__name__)


async def send_trial_expiring_soon(db):
    """Send reminder to users whose trial expires in 1-2 days.
    Called by scheduler daily.
    """
    now = datetime.datetime.utcnow()
    soon = now + datetime.timedelta(days=2)
    very_soon = now + datetime.timedelta(days=1)

    # Find trial users expiring in 1-2 days
    users = db.query(User).filter(
        User.membership_tier == "pro",
        User.membership_expires_at.isnot(None),
        User.membership_expires_at.between(now, soon),
        User.is_active == True,
    ).all()

    sent = 0
    for user in users:
        extra = user.extra_data or {}
        if not extra.get("trial_used"):
            continue

        # Check if already sent
        reminder_key = "trial_reminder_sent"
        if extra.get(reminder_key):
            continue

        days_left = max(1, (user.membership_expires_at - now).days)
        is_urgent = user.membership_expires_at <= very_soon

        subject = f"\u60a8\u7684 Pro \u8bd5\u7528\u5c06\u5728 {days_left} \u5929\u540e\u7ed3\u675f"
        html = f"""
        <div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
          <div style="background:{'#dc2626' if is_urgent else '#f59e0b'};padding:20px;border-radius:12px 12px 0 0;text-align:center">
            <h2 style="color:white;margin:0">{'\u23f0 \u8bd5\u7528\u5373\u5c06\u5230\u671f' if is_urgent else '\ud83d\udd14 \u8bd5\u7528\u5230\u671f\u63d0\u9192'}</h2>
          </div>
          <div style="background:#fff;padding:24px;border:1px solid #e2e8f0;border-radius:0 0 12px 12px">
            <p style="color:#334155">Hi {user.display_name or ''}\uff0c</p>
            <p style="color:#334155;line-height:1.6">
              \u60a8\u7684 <strong>Pro \u4e13\u4e1a\u7248\u514d\u8d39\u8bd5\u7528</strong>\u5c06\u5728
              <strong style="color:#dc2626"> {days_left} \u5929\u540e</strong>\u7ed3\u675f\u3002
              \u5230\u671f\u540e\u60a8\u5c06\u81ea\u52a8\u8f6c\u4e3a\u514d\u8d39\u7248\uff0c\u90e8\u5206\u9ad8\u7ea7\u529f\u80fd\u5c06\u4e0d\u53ef\u7528\u3002
            </p>
            <p style="color:#475569;font-size:14px;line-height:1.8">
              \u5347\u7ea7\u4e3a\u4ed8\u8d39\u4f1a\u5458\uff0c\u7ee7\u7eed\u4eab\u53d7\uff1a<br/>
              \u2705 AI \u5b9e\u65f6\u7b80\u62a5\u548c\u5468\u62a5<br/>
              \u2705 \u53d9\u4e8b\u5f3a\u5ea6\u6307\u6570\u548c\u98ce\u9669\u9884\u8b66<br/>
              \u2705 Agent \u81ea\u5b9a\u4e49\u76d1\u63a7\u4efb\u52a1<br/>
              \u2705 \u65e0\u9650\u5173\u6ce8\u5217\u8868
            </p>
            <div style="text-align:center;margin:20px 0">
              <a href="https://huidao.cc/#membership" style="background:linear-gradient(135deg,#667eea,#764ba2);color:white;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600">
                \u7acb\u5373\u5347\u7ea7 \u2192
              </a>
            </div>
            <p style="color:#94a3b8;font-size:12px;border-top:1px solid #e2e8f0;padding-top:12px">
              \u5982\u60a8\u5df2\u5347\u7ea7\uff0c\u8bf7\u5ffd\u7565\u6b64\u90ae\u4ef6\u3002huidao.cc \u56e2\u961f
            </p>
          </div>
        </div>
        """

        try:
            from app.services.email_verify import send_verification_email
            await send_verification_email(user.email, subject, html)
            extra[reminder_key] = datetime.datetime.utcnow().isoformat()
            user.extra_data = extra
            sent += 1
            logger.info(f"Trial expiry reminder sent to {user.email} ({days_left} days left)")
        except Exception as e:
            logger.error(f"Failed to send trial reminder to {user.email}: {e}")

    db.commit()
    return sent


async def send_weekly_newsletter(db):
    """Send weekly newsletter to all active users.
    Called by scheduler weekly (Monday).
    """
    now = datetime.datetime.utcnow()
    week_start = now - datetime.timedelta(days=7)

    # Get weekly stats
    articles_this_week = db.query(Article).filter(
        Article.fetched_at >= week_start
    ).count()

    latest_briefing = db.query(Briefing).order_by(
        Briefing.created_at.desc()
    ).first()

    # Get active users who have email verified or are paid members
    users = db.query(User).filter(
        User.is_active == True,
        User.membership_tier.in_(["basic", "pro", "max"]),
    ).all()

    sent = 0
    briefing_preview = ""
    if latest_briefing and latest_briefing.content:
        briefing_preview = latest_briefing.content[:300] + "..."

    subject = f"huidao.cc \u5468\u62a5 \u2014 \u672c\u5468\u65b0\u589e {articles_this_week} \u7bc7\u8d44\u8baf"
    html = f"""
    <div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <div style="background:linear-gradient(135deg,#1e40af,#3b82f6);padding:24px;border-radius:12px 12px 0 0;text-align:center">
        <h2 style="color:white;margin:0">\ud83d\udcca huidao.cc \u5468\u62a5</h2>
        <p style="color:rgba(255,255,255,0.8);margin:8px 0 0;font-size:14px">{now.strftime('%Y\u5e74%m\u6708%d\u65e5')}</p>
      </div>
      <div style="background:#fff;padding:24px;border:1px solid #e2e8f0;border-radius:0 0 12px 12px">
        <div style="background:#f1f5f9;padding:16px;border-radius:8px;margin-bottom:16px">
          <p style="margin:0;color:#334155;font-size:15px">
            \ud83d\udcf0 \u672c\u5468\u5e73;&#x53f0;&#x65b0;&#x589e; <strong>{articles_this_week}</strong> \u7bc7&#x8d44;&#x8baf;
          </p>
        </div>
        {'<div style="margin-bottom:16px"><h3 style="color:#1e293b;font-size:15px;margin-bottom:8px">\ud83d\udcdd \u6700\u65b0\u7b80\u62a5\u6458\u8981</h3><p style="color:#475569;font-size:14px;line-height:1.6">' + briefing_preview.replace(chr(10), '<br/>') + '</p></div>' if briefing_preview else ''}
        <div style="text-align:center;margin:20px 0">
          <a href="https://huidao.cc" style="background:linear-gradient(135deg,#667eea,#764ba2);color:white;padding:10px 24px;border-radius:8px;text-decoration:none;font-weight:600">
            \u67e5\u770b\u5b8c\u6574\u5185\u5bb9 \u2192
          </a>
        </div>
        <p style="color:#94a3b8;font-size:11px;text-align:center;border-top:1px solid #e2e8f0;padding-top:12px">
          \u60a8\u6536\u5230\u6b64\u90ae\u4ef6\u56e0\u4e3a\u60a8\u662f huidao.cc \u4ed8\u8d39\u4f1a\u5458\u3002\u5982\u4e0d\u60f3\u6536\u5230\u5468\u62a5\uff0c\u8bf7\u56de\u590d"\u53d6\u6d88"\u3002
        </p>
      </div>
    </div>
    """

    for user in users:
        try:
            from app.services.email_verify import send_verification_email
            await send_verification_email(user.email, subject, html)
            sent += 1
        except Exception as e:
            logger.error(f"Newsletter send failed to {user.email}: {e}")

    logger.info(f"Weekly newsletter sent to {sent} users")
    return sent
