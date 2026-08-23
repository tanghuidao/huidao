"""Email verification service - Gmail SMTP version."""
import os
import logging
import secrets
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FROM_EMAIL = os.getenv("SMTP_FROM", SMTP_USER)
FROM_NAME = os.getenv("SMTP_FROM_NAME", "huidao.cc")

VERIFY_BASE_URL = os.getenv("VERIFY_BASE_URL", "https://huidao.cc")
VERIFICATION_TOKEN_EXPIRY_HOURS = 24
RESEND_COOLDOWN_SECONDS = 60


def generate_verification_token() -> str:
    return secrets.token_urlsafe(48)


def get_verification_url(token: str) -> str:
    return f"{VERIFY_BASE_URL}/api/auth/verify-email?token={token}"


def check_resend_cooldown(last_sent_at: Optional[datetime]) -> tuple:
    if last_sent_at is None:
        return True, 0
    now = datetime.now(timezone.utc)
    if last_sent_at.tzinfo is None:
        last_sent_at = last_sent_at.replace(tzinfo=timezone.utc)
    remaining = RESEND_COOLDOWN_SECONDS - (now - last_sent_at).total_seconds()
    if remaining > 0:
        return False, int(remaining) + 1
    return True, 0


def is_token_expired(sent_at: Optional[datetime]) -> bool:
    if sent_at is None:
        return True
    now = datetime.now(timezone.utc)
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    return (now - sent_at) > timedelta(hours=VERIFICATION_TOKEN_EXPIRY_HOURS)


async def _send_email(to_email: str, subject: str, html_content: str, text_content: str = "") -> dict:
    """Shared email sending helper. All email functions should use this."""
    if not SMTP_USER or not SMTP_PASS:
        logger.warning(f"SMTP not configured. Skipping email to {to_email}: {subject}")
        return {"success": False, "error": "smtp_not_configured"}

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg["To"] = to_email
        # Plain text fallback: strip HTML tags roughly
        if not text_content:
            import re
            text_content = re.sub(r'<[^>]+>', '', html_content)
        msg.attach(MIMEText(text_content, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        await aiosmtplib.send(
            msg, hostname=SMTP_HOST, port=SMTP_PORT,
            username=SMTP_USER, password=SMTP_PASS, start_tls=True,
        )

        logger.info(f"Email sent to {to_email} via {SMTP_HOST}: {subject}")
        return {"success": True, "error": None}

    except aiosmtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP auth failed: {e}")
        return {"success": False, "error": "smtp_auth_failed"}
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return {"success": False, "error": str(e)}


async def send_verification_email(to_email: str, token: str, display_name: str = "") -> dict:
    verify_url = get_verification_url(token)
    greeting = f"Hi {display_name}," if display_name else "\u4f60\u597d,"
    subject = "\u9a8c\u8bc1\u4f60\u7684 huidao.cc \u90ae\u7bb1"

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;padding:40px 20px;">
<tr><td align="center">
<table width="480" cellpadding="0" cellspacing="0" style="background:#1e293b;border-radius:12px;overflow:hidden;">
<tr><td style="padding:32px 32px 16px;text-align:center;">
<h1 style="color:#60a5fa;font-size:24px;margin:0;">huidao.cc</h1>
<p style="color:#94a3b8;font-size:14px;margin:8px 0 0;">AI + Crypto / Web3 \u5168\u7403\u52a8\u6001\u76d1\u6d4b\u7cfb\u7edf</p>
</td></tr>
<tr><td style="padding:16px 32px;">
<p style="color:#e2e8f0;font-size:16px;margin:0 0 16px;">{greeting}</p>
<p style="color:#cbd5e1;font-size:15px;line-height:1.6;margin:0 0 24px;">\u6b22\u8fce\u52a0\u5165 huidao.cc\uff01\u8bf7\u70b9\u51fb\u4e0b\u65b9\u6309\u94ae\u9a8c\u8bc1\u4f60\u7684\u90ae\u7bb1\u5730\u5740\uff0c\u5b8c\u6210\u8d26\u53f7\u6fc0\u6d3b\u3002</p>
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:16px 0;">
<a href="{verify_url}" style="display:inline-block;padding:14px 40px;background:#3b82f6;color:#ffffff;text-decoration:none;border-radius:8px;font-size:16px;font-weight:600;">\u9a8c\u8bc1\u90ae\u7bb1</a>
</td></tr></table>
<p style="color:#64748b;font-size:13px;text-align:center;margin:8px 0 0;">
\u6216\u590d\u5236\u94fe\u63a5\u5230\u6d4f\u89c8\u5668\uff1a<br><span style="color:#94a3b8;word-break:break-all;font-size:12px;">{verify_url}</span></p>
</td></tr>
<tr><td style="padding:24px 32px;border-top:1px solid #334155;">
<p style="color:#64748b;font-size:12px;margin:0;text-align:center;">\u6b64\u94fe\u63a5 24 \u5c0f\u65f6\u5185\u6709\u6548\u3002\u5982\u679c\u4f60\u6ca1\u6709\u6ce8\u518c huidao.cc \u8d26\u53f7\uff0c\u8bf7\u5ffd\u7565\u6b64\u90ae\u4ef6\u3002</p>
</td></tr>
</table></td></tr></table></body></html>"""

    text_content = f"""{greeting}\n\n\u6b22\u8fce\u52a0\u5165 huidao.cc\uff01\u8bf7\u70b9\u51fb\u94fe\u63a5\u9a8c\u8bc1\u90ae\u7bb1\uff1a\n\n{verify_url}\n\n\u6b64\u94fe\u63a524\u5c0f\u65f6\u5185\u6709\u6548\u3002\n\n\u2014 huidao.cc \u56e2\u961f"""

    return await _send_email(to_email, subject, html_content, text_content)


async def send_welcome_email(email: str, display_name: str = ""):
    """Send welcome email to newly registered user."""
    name = display_name or email.split("@")[0]
    subject = "\u6b22\u8fce\u52a0\u5165 huidao.cc\uff0c" + name + "\uff01"
    html_body = """
    <div style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
      <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
        <h1 style="color: white; margin: 0; font-size: 24px;">\ud83c\udf89 \u6b22\u8fce\u52a0\u5165 huidao.cc</h1>
      </div>
      <div style="background: #ffffff; padding: 30px; border: 1px solid #e2e8f0; border-radius: 0 0 12px 12px;">
        <p style="color: #334155; font-size: 16px;">Hi """ + name + """\uff0c</p>
        <p style="color: #334155; font-size: 15px; line-height: 1.6;">
          \u611f\u8c22\u6ce8\u518c huidao.cc\uff01\u6211\u4eec\u5df2\u4e3a\u60a8\u5f00\u542f\u4e86 <strong>7 \u5929 Pro \u4e13\u4e1a\u7248\u514d\u8d39\u8bd5\u7528</strong>\uff0c\u60a8\u53ef\u4ee5\u7acb\u5373\u4f53\u9a8c\u5168\u90e8\u9ad8\u7ea7\u529f\u80fd\uff1a
        </p>
        <ul style="color: #475569; font-size: 14px; line-height: 2;">
          <li>\u2705 AI \u5b9e\u65f6\u7b80\u62a5 \u2014 \u6bcf\u65e5/\u6bcf\u5468\u667a\u80fd\u6458\u8981</li>
          <li>\u2705 \u53d9\u4e8b\u5f3a\u5ea6\u6307\u6570 \u2014 \u8ffd\u8e2a\u70ed\u70b9\u8bae\u9898\u8d8b\u52bf</li>
          <li>\u2705 \u98ce\u9669\u9884\u8b66\u63a8\u9001 \u2014 \u53ca\u65f6\u6355\u6349\u5e02\u573a\u5f02\u52a8</li>
          <li>\u2705 Agent \u4efb\u52a1 \u2014 \u81ea\u5b9a\u4e49\u76d1\u63a7\u4efb\u52a1</li>
        </ul>
        <div style="text-align: center; margin: 25px 0;">
          <a href="https://huidao.cc" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 12px 30px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: 600;">
            \u5f00\u59cb\u63a2\u7d22 \u2192
          </a>
        </div>
        <p style="color: #94a3b8; font-size: 13px; border-top: 1px solid #e2e8f0; padding-top: 15px;">
          \u8bd5\u7528\u671f\u7ed3\u675f\u540e\u5c06\u81ea\u52a8\u8f6c\u4e3a\u514d\u8d39\u7248\uff0c\u968f\u65f6\u53ef\u5347\u7ea7\u3002\u5982\u6709\u95ee\u9898\u8bf7\u56de\u590d\u6b64\u90ae\u4ef6\u3002<br/>
          huidao.cc \u56e2\u961f
        </p>
      </div>
    </div>
    """

    result = await _send_email(email, subject, html_body)
    if result.get("success"):
        logger.info(f"Welcome email sent to {email}")
    else:
        logger.warning(f"Welcome email failed for {email}: {result.get('error')}")


async def send_reset_password_email(to_email: str, reset_url: str, display_name: str = ""):
    """Send password reset email."""
    subject = "huidao.cc - \u91cd\u7f6e\u5bc6\u7801"
    greeting = display_name + "\uff0c\u4f60\u597d\uff01" if display_name else "\u4f60\u597d\uff01"
    html_body = """
    <div style="max-width:520px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#16202a;color:#e7e9ea;border-radius:12px;overflow:hidden;">
        <div style="background:linear-gradient(135deg,#1d9bf0,#00ba7c);padding:24px;text-align:center;">
            <h1 style="color:white;margin:0;font-size:1.3rem;">\u91cd\u7f6e\u5bc6\u7801</h1>
        </div>
        <div style="padding:30px;">
            <p style="font-size:0.95rem;">""" + greeting + """</p>
            <p style="font-size:0.88rem;color:#b0b3b8;line-height:1.8;">
                \u6211\u4eec\u6536\u5230\u4e86\u4f60\u7684\u5bc6\u7801\u91cd\u7f6e\u8bf7\u6c42\u3002\u70b9\u51fb\u4e0b\u65b9\u6309\u94ae\u91cd\u7f6e\u5bc6\u7801\uff0c\u94fe\u63a5\u6709\u6548\u671f <strong style="color:#1d9bf0;">30 \u5206\u949f</strong>\u3002
            </p>
            <div style="text-align:center;margin:28px 0;">
                <a href=\"""" + reset_url + """\" style="display:inline-block;background:linear-gradient(135deg,#1d9bf0,#00ba7c);color:white;padding:12px 36px;border-radius:8px;text-decoration:none;font-weight:600;font-size:0.95rem;">
                    \u91cd\u7f6e\u5bc6\u7801
                </a>
            </div>
            <p style="font-size:0.78rem;color:#71767b;line-height:1.6;">
                \u5982\u679c\u4f60\u6ca1\u6709\u53d1\u8d77\u6b64\u8bf7\u6c42\uff0c\u8bf7\u5ffd\u7565\u6b64\u90ae\u4ef6\uff0c\u4f60\u7684\u5bc6\u7801\u4e0d\u4f1a\u88ab\u66f4\u6539\u3002<br>
                \u4e5f\u53ef\u4ee5\u590d\u5236\u4ee5\u4e0b\u94fe\u63a5\u5230\u6d4f\u89c8\u5668\u6253\u5f00\uff1a<br>
                <span style="color:#1d9bf0;word-break:break-all;">""" + reset_url + """</span>
            </p>
        </div>
        <div style="padding:16px 30px;border-top:1px solid #2f3336;text-align:center;">
            <p style="font-size:0.72rem;color:#536471;margin:0;">&copy; 2026 huidao.cc All rights reserved.</p>
        </div>
    </div>
    """

    result = await _send_email(to_email, subject, html_body)
    if result.get("success"):
        logger.info(f"Reset password email sent to {to_email}")
    else:
        logger.warning(f"Reset password email failed for {to_email}: {result.get('error')}")
