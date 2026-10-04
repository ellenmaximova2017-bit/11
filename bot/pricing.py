import time

from . import config

PLANS = {
    "month": ("Месяц", config.PRICE_MONTH, 30),
    "week": ("Неделя", config.PRICE_WEEK, 7),
}


def discount_until(created: int) -> int:
    return created + config.DISCOUNT_HOURS * 3600


def discount_active(created: int) -> bool:
    return config.DISCOUNT_PERCENT > 0 and time.time() < discount_until(created)


def price(plan: str, created: int) -> int:
    base = PLANS[plan][1]
    return round(base * (100 - config.DISCOUNT_PERCENT) / 100) if discount_active(created) else base
