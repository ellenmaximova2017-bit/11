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
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
STARS_MONTH = int(os.getenv("STARS_MONTH", "0"))
REFERRAL_BONUS = int(os.getenv("REFERRAL_BONUS", "3"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
REPLICATE_EDIT_MODEL = os.getenv("REPLICATE_EDIT_MODEL", "black-forest-labs/flux-kontext-pro")
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
MODELS = {
    "fast": ("⚡ Быстрая", "claude-haiku-4-5-20251001"),
    "std": ("⚖️ Стандартная", MODEL),
    "pro": ("🧠 Умная", "claude-opus-5-5"),
}
SITES_DIR = os.getenv("SITES_DIR", "sites")
