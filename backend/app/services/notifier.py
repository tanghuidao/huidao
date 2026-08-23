"""Notification service - email, webhook (Feishu/Slack), Telegram."""
import logging
import asyncio
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import (
    NOTIFY_EMAIL_ENABLED, NOTIFY_EMAIL_HOST, NOTIFY_EMAIL_PORT,
    NOTIFY_EMAIL_USER, NOTIFY_EMAIL_PASS, NOTIFY_EMAIL_TO,
    NOTIFY_WEBHOOK_ENABLED, NOTIFY_WEBHOOK_URL,
    NOTIFY_TELEGRAM_ENABLED, NOTIFY_TELEGRAM_BOT_TOKEN, NOTIFY_TELEGRAM_CHAT_ID,
)
from app.models import Briefing, Article

logger = logging.getLogger(__name__)


# --- Email ---

async def send_email(subject: str, body: str, to_addresses: list[str] = None):
    """Send email notification using aiosmtplib."""
    if not NOTIFY_EMAIL_ENABLED:
        return

    if not to_addresses:
        to_addresses = [a.strip() for a in NOTIFY_EMAIL_TO.split(",") if a.strip()]

    if not to_addresses:
        logger.warning("No email recipients configured")
        return

    try:
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart("alternative")
        msg["From"] = NOTIFY_EMAIL_USER
        msg["To"] = ", ".join(to_addresses)
        msg["Subject"] = subject

        # Plain text
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # HTML version
        html_body = body.replace("\n", "<br>")
        html_content = f"""
        <html>
        <body style="font-family: -apple-system, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #1d9bf0;">{subject}</h2>
            <div>{html_body}</div>
            <hr>
            <p style="color: #666; font-size: 12px;">AI + Crypto / Web3 /4全球动态</p>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=NOTIFY_EMAIL_HOST,
            port=NOTIFY_EMAIL_PORT,
            username=NOTIFY_EMAIL_USER,
            password=NOTIFY_EMAIL_PASS,
            use_tls=True,
        )
        logger.info(f"Email sent to {to_addresses}: {subject}")

    except ImportError:
        logger.warning("aiosmtplib not installed, email disabled")
    except Exception as e:
        logger.error(f"Email send error: {e}")


# --- Webhook (Feishu/Slack/Discord) ---

async def send_webhook(title: str, content: str, url: str = None):
    """Send webhook notification (supports Feishu, Slack, Discord formats)."""
    if not NOTIFY_WEBHOOK_ENABLED or not NOTIFY_WEBHOOK_URL:
        return

    webhook_url = url or NOTIFY_WEBHOOK_URL

    try:
        # Auto-detect webhook type
        if "feishu" in webhook_url or "lark" in webhook_url:
            payload = _format_feishu(title, content)
        elif "slack" in webhook_url:
            payload = _format_slack(title, content)
        elif "discord" in webhook_url:
            payload = _format_discord(title, content)
        else:
            # Generic JSON payload
            payload = {"title": title, "content": content}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Webhook sent: {title}")

    except Exception as e:
        logger.error(f"Webhook send error: {e}")


def _format_feishu(title: str, content: str) -> dict:
    """Format message for Feishu/Lark webhook."""
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content[:2000],
                }
            ],
        }
    }


def _format_slack(title: str, content: str) -> dict:
    """Format message for Slack webhook."""
    return {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": content[:3000]},
            },
        ]
    }


def _format_discord(title: str, content: str) -> dict:
    """Format message for Discord webhook."""
    return {
        "embeds": [
            {
                "title": title,
                "description": content[:4000],
                "color": 1941999,  # Blue
            }
        ]
    }


# --- Telegram ---

async def send_telegram(text: str, parse_mode: str = "Markdown"):
    """Send Telegram notification."""
    if not NOTIFY_TELEGRAM_ENABLED:
        return

    if not NOTIFY_TELEGRAM_BOT_TOKEN or not NOTIFY_TELEGRAM_CHAT_ID:
        logger.warning("Telegram bot token or chat ID not configured")
        return

    try:
        url = f"https://api.telegram.org/bot{NOTIFY_TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": NOTIFY_TELEGRAM_CHAT_ID,
            "text": text[:4000],  # Telegram limit
            "parse_mode": parse_mode,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Telegram message sent")

    except Exception as e:
        logger.error(f"Telegram send error: {e}")


# --- High-level notification functions ---

async def notify_new_articles(db: Session, total_new: int):
    """Notify about new articles collected."""
    if total_new < 5:  # Don't notify for small batches
        return

    title = f"📡 采集完成：新增 {total_new} 条内容"
    content = f"AI + Crypto / Web3 /4全球动态刚完成一轮信息采集，新增 {total_new} 条内容。\n\n请登录系统查看详情。"

    tasks = []
    if NOTIFY_WEBHOOK_ENABLED:
        tasks.append(send_webhook(title, content))
    if NOTIFY_TELEGRAM_ENABLED:
        tasks.append(send_telegram(f"*{title}*\n\n{content}"))
    # Email only for large batches
    if NOTIFY_EMAIL_ENABLED and total_new >= 20:
        tasks.append(send_email(title, content))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def notify_briefing(db: Session, briefing: Briefing):
    """Notify about a new briefing generated."""
    title = f"📋 简报已生成：{briefing.title}"
    # Truncate briefing content for notification
    content = briefing.content[:2000]
    if len(briefing.content) > 2000:
        content += "\n\n... [完整简报请登录系统查看]"

    tasks = []
    if NOTIFY_EMAIL_ENABLED:
        tasks.append(send_email(title, briefing.content))
    if NOTIFY_WEBHOOK_ENABLED:
        tasks.append(send_webhook(title, content))
    if NOTIFY_TELEGRAM_ENABLED:
        tasks.append(send_telegram(f"*{title}*\n\n{content}"))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def notify_high_risk(db: Session, article: Article, risk_type: str = "regulation"):
    """Notify about high-risk content detected."""
    title = f"⚠️ 高风险内容：{article.title[:60]}"
    content = (
        f"类型: {risk_type}\n"
        f"标题: {article.title}\n"
        f"链接: {article.url}\n"
    )
    if article.one_line_summary:
        content += f"摘要: {article.one_line_summary}\n"

    tasks = []
    if NOTIFY_WEBHOOK_ENABLED:
        tasks.append(send_webhook(title, content))
    if NOTIFY_TELEGRAM_ENABLED:
        tasks.append(send_telegram(f"*{title}*\n\n{content}"))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
