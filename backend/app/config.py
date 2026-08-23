"""Application configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/monitor.db")

# LLM
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Collector
FETCH_TIMEOUT = 30  # seconds
MAX_ARTICLES_PER_FEED = 50

# Scheduler
SCHEDULER_COLLECT_INTERVAL_MINUTES = int(os.getenv("SCHEDULER_COLLECT_INTERVAL", "60"))
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"

# Web Scraping
PLAYWRIGHT_HEADLESS = True
WEB_SCRAPE_TIMEOUT = 60  # seconds

# Notifications
NOTIFY_EMAIL_ENABLED = os.getenv("NOTIFY_EMAIL_ENABLED", "false").lower() == "true"
NOTIFY_EMAIL_HOST = os.getenv("NOTIFY_EMAIL_HOST", "smtp.gmail.com")
NOTIFY_EMAIL_PORT = int(os.getenv("NOTIFY_EMAIL_PORT", "587"))
NOTIFY_EMAIL_USER = os.getenv("NOTIFY_EMAIL_USER", "")
NOTIFY_EMAIL_PASS = os.getenv("NOTIFY_EMAIL_PASS", "")
NOTIFY_EMAIL_TO = os.getenv("NOTIFY_EMAIL_TO", "")  # comma-separated

NOTIFY_WEBHOOK_ENABLED = os.getenv("NOTIFY_WEBHOOK_ENABLED", "false").lower() == "true"
NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL", "")  # Feishu/Slack/Telegram webhook

NOTIFY_TELEGRAM_ENABLED = os.getenv("NOTIFY_TELEGRAM_ENABLED", "false").lower() == "true"
NOTIFY_TELEGRAM_BOT_TOKEN = os.getenv("NOTIFY_TELEGRAM_BOT_TOKEN", "")
NOTIFY_TELEGRAM_CHAT_ID = os.getenv("NOTIFY_TELEGRAM_CHAT_ID", "")
