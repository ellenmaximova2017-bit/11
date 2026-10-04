"""HTTP-сервер: отдаёт Mini App и API (статус, ссылка на оплату). Всё проверяется по initData Telegram."""
import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram.types import LabeledPrice

from . import config, db, pricing
from .scenarios import SCENARIOS

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"


def verify_init_data(init_data: str) -> dict | None:
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    got = data.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), got):
        return None
    if time.time() - int(data.get("auth_date", 0)) > 86400:
        return None
    return json.loads(data["user"])


async def _auth(request) -> dict:
    user = verify_init_data(request.headers.get("X-Init-Data", ""))
    if not user:
        raise web.HTTPUnauthorized()
    return user


async def me(request):
    tg_user = await _auth(request)
    user = await db.get_user(tg_user["id"], tg_user.get("first_name", ""))
    users, paid, _ = await db.stats()
    active = pricing.discount_active(user["created"])
    me_bot = await request.app["bot"].me()
    return web.json_response({
        "bot": me_bot.username,
        "name": tg_user.get("first_name", ""),
        "paid": await db.is_paid(user["id"]),
        "free_left": max(config.FREE_MESSAGES - user["used"], 0),
        "discount": config.DISCOUNT_PERCENT if active else 0,
        "discount_until": pricing.discount_until(user["created"]) if active else 0,
        "plans": {
            k: {"name": n, "base": base, "price": pricing.price(k, user["created"]), "days": d}
            for k, (n, base, d) in pricing.PLANS.items()
        },
        "scenarios": {k: s["title"] for k, s in SCENARIOS.items()},
        # честные цифры, только из нашей базы
        "stats": {"users": users, "subscribers": paid},
        "payments": bool(config.PAYMENT_TOKEN),
    })


async def invoice(request):
    tg_user = await _auth(request)
    if not config.PAYMENT_TOKEN:
        raise web.HTTPServiceUnavailable(text="payments disabled")
    plan = (await request.json()).get("plan")
    if plan not in pricing.PLANS:
        raise web.HTTPBadRequest()
    user = await db.get_user(tg_user["id"])
    name, _, _ = pricing.PLANS[plan]
    amount = pricing.price(plan, user["created"])
    link = await request.app["bot"].create_invoice_link(
        title=f"Подписка: {name}",
        description="Безлимитный доступ ко всем сценариям. Отмена в любой момент.",
        payload=f"{plan}:{amount}",
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label=name, amount=amount * 100)],
    )
    return web.json_response({"link": link})


async def index(request):
    return web.FileResponse(WEBAPP_DIR / "index.html")


def make_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", index)
    app.router.add_get("/api/me", me)
    app.router.add_post("/api/invoice", invoice)
    return app
