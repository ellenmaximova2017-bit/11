import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
PAYMENT_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
FREE_MESSAGES = int(os.getenv("FREE_MESSAGES", "3"))
PRICE_MONTH = int(os.getenv("PRICE_MONTH_RUB", "1490"))
PRICE_WEEK = int(os.getenv("PRICE_WEEK_RUB", "790"))
ADMIN_ID = int(os.getenv("ADMIN_ID") or 0)
DB_PATH = os.getenv("DB_PATH", "bot.db")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
DISCOUNT_PERCENT = int(os.getenv("DISCOUNT_PERCENT", "30"))
DISCOUNT_HOURS = int(os.getenv("DISCOUNT_HOURS", "24"))
