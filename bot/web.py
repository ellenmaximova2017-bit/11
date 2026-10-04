"""HTTP-сервер: отдаёт Mini App и API (статус, ссылка на оплату). Всё проверяется по initData Telegram."""
import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram.types import LabeledPrice

from . import config, db, gcal, pricing
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
    users, paid, _, _ = await db.stats()
    active = pricing.discount_active(user["created"])
    me_bot = await request.app["bot"].me()
    return web.json_response({
        "bot": me_bot.username,
        "name": tg_user.get("first_name", ""),
        "paid": await db.is_paid(user["id"]),
        "free_left": db.free_left(user),
        "credits": user["credits"],
        "credits_plan": {"month": config.CREDITS_MONTH, "week": config.CREDITS_WEEK},
        "topup": {"credits": config.TOPUP_CREDITS,
                  "rub": config.TOPUP_RUB if config.PAYMENT_TOKEN else 0, "stars": config.TOPUP_STARS},
        "paid_until": user["paid_until"],
        "auto_renew": bool(user["sub_charge_id"]) and await db.is_paid(user["id"]),
        "stars_price": config.STARS_MONTH,
        "facts": await db.facts(user["id"], 10),
        "ref_link": f"https://t.me/{me_bot.username}?start=ref_{user['id']}",
        "discount": config.DISCOUNT_PERCENT if active else 0,
        "discount_until": pricing.discount_until(user["created"]) if active else 0,
        "plans": {
            k: {"name": n, "base": base, "price": pricing.price(k, user["created"]), "days": d}
            for k, (n, base, d) in pricing.PLANS.items()
        },
        "scenarios": {k: s["title"] for k, s in SCENARIOS.items()},
        # честные цифры, только из нашей базы
        "stats": {"users": users, "subscribers": paid},
        "payments": bool(config.PAYMENT_TOKEN or config.STARS_MONTH),
    })


async def invoice(request):
    tg_user = await _auth(request)
    plan = (await request.json()).get("plan")
    if plan in ("topup", "topup_stars"):
        user = await db.get_user(tg_user["id"])
        if not await db.is_paid(user["id"]):
            raise web.HTTPForbidden(text="subscription required")
        label = f"+{config.TOPUP_CREDITS} запросов"
        if plan == "topup_stars" and config.TOPUP_STARS:
            kw = dict(payload="topup:stars", provider_token="", currency="XTR",
                      prices=[LabeledPrice(label=label, amount=config.TOPUP_STARS)])
        elif plan == "topup" and config.TOPUP_RUB and config.PAYMENT_TOKEN:
            kw = dict(payload=f"topup:{config.TOPUP_RUB}", provider_token=config.PAYMENT_TOKEN, currency="RUB",
                      prices=[LabeledPrice(label=label, amount=config.TOPUP_RUB * 100)],
                      **pricing.receipt_kwargs(label, config.TOPUP_RUB))
        else:
            raise web.HTTPBadRequest()
        link = await request.app["bot"].create_invoice_link(
            title=label, description="Разовая докупка запросов к подписке.", **kw)
        return web.json_response({"link": link})
    if plan == "stars" and config.STARS_MONTH:
        link = await request.app["bot"].create_invoice_link(
            title="Подписка: месяц", description="Автопродление каждые 30 дней, отмена в любой момент.",
            payload="stars:month", provider_token="", currency="XTR",
            prices=[LabeledPrice(label="Месяц", amount=config.STARS_MONTH)], subscription_period=2592000,
        )
        return web.json_response({"link": link})
    if plan not in pricing.PLANS:
        raise web.HTTPBadRequest()
    if not config.PAYMENT_TOKEN:
        raise web.HTTPServiceUnavailable(text="payments disabled")
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
        **pricing.receipt_kwargs(f"Подписка: {name}", amount),
    )
    return web.json_response({"link": link})


async def cancel(request):
    tg_user = await _auth(request)
    user = await db.get_user(tg_user["id"])
    if not user["sub_charge_id"]:
        raise web.HTTPBadRequest(text="no subscription")
    await request.app["bot"].edit_user_star_subscription(
        user_id=user["id"], telegram_payment_charge_id=user["sub_charge_id"], is_canceled=True)
    return web.json_response({"ok": True})


async def forget(request):
    tg_user = await _auth(request)
    await db.clear_facts(tg_user["id"])
    return web.json_response({"ok": True})


async def site(request):
    slug = request.match_info["slug"]
    path = Path(config.SITES_DIR) / f"{slug}.html"
    if not re.fullmatch(r"[A-Za-z0-9]{4,16}", slug) or not path.exists():
        raise web.HTTPNotFound()
    # sandbox: страница без доступа к origin Mini App; без внешних ресурсов и форм
    return web.Response(
        text=path.read_text(encoding="utf-8"), content_type="text/html",
        headers={"Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; img-src data:; "
                                            "style-src 'unsafe-inline'; script-src 'unsafe-inline'",
                 "X-Content-Type-Options": "nosniff"},
    )


async def google_callback(request):
    uid = gcal.verify_state(request.query.get("state", ""))
    code = request.query.get("code")
    if uid is None or not code:
        return web.Response(text="Ссылка недействительна или доступ не выдан.", status=400)
    try:
        await gcal.connect(uid, code)
    except Exception:
        return web.Response(text="Не удалось подключить календарь, попробуйте ещё раз.", status=500)
    await request.app["bot"].send_message(uid, "✅ Google Календарь подключён. Теперь напоминания попадут и туда.")
    return web.Response(text="Готово! Календарь подключён, можно вернуться в Telegram.", content_type="text/plain")


async def index(request):
    return web.FileResponse(WEBAPP_DIR / "index.html")


def make_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", index)
    app.router.add_get("/api/me", me)
    app.router.add_post("/api/invoice", invoice)
    app.router.add_post("/api/cancel", cancel)
    app.router.add_post("/api/forget", forget)
    app.router.add_get("/s/{slug}", site)
    app.router.add_get("/oauth/google/callback", google_callback)
    return app
