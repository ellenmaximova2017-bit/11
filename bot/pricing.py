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


def receipt_kwargs(description: str, amount_rub: int) -> dict:
    """Доп. параметры счёта ЮKassa с чеком 54-ФЗ (пусто, если чеки выключены)."""
    import json

    if not config.YOOKASSA_RECEIPT:
        return {}
    receipt = {"items": [{
        "description": description[:128], "quantity": "1.00",
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "vat_code": config.YOOKASSA_VAT_CODE, "payment_mode": "full_payment", "payment_subject": "service",
    }]}
    if config.YOOKASSA_TAX_SYSTEM:
        receipt["tax_system_code"] = int(config.YOOKASSA_TAX_SYSTEM)
    return {"need_email": True, "send_email_to_provider": True,
            "provider_data": json.dumps({"receipt": receipt}, ensure_ascii=False)}
