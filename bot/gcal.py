"""Google Календарь: OAuth для пользователя и создание событий (REST, без SDK)."""
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import aiohttp

from . import config, db

SCOPE = " ".join([
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.compose",  # только черновики/отправка своих писем
])
REDIRECT = config.WEBAPP_URL.rstrip("/") + "/oauth/google/callback"


def enabled() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET and config.WEBAPP_URL)


def _sign(uid: int) -> str:
    return hmac.new(config.BOT_TOKEN.encode(), f"gcal:{uid}".encode(), hashlib.sha256).hexdigest()[:24]


def verify_state(state: str) -> int | None:
    uid, _, sig = state.partition(".")
    return int(uid) if uid.isdigit() and hmac.compare_digest(sig, _sign(int(uid))) else None


def auth_url(uid: int) -> str:
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": config.GOOGLE_CLIENT_ID, "redirect_uri": REDIRECT, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": f"{uid}.{_sign(uid)}",
    })


async def _token_request(data: dict) -> dict:
    data = {"client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET, **data}
    async with aiohttp.ClientSession() as s, s.post("https://oauth2.googleapis.com/token", data=data) as r:
        body = await r.json()
        if r.status != 200:
            raise RuntimeError(f"google token error: {body.get('error')}")
        return body


async def connect(uid: int, code: str):
    body = await _token_request({"code": code, "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    if not body.get("refresh_token"):
        raise RuntimeError("no refresh_token")
    await db.set_google_token(uid, body["refresh_token"])


async def access_token(uid: int) -> str | None:
    refresh = await db.get_google_token(uid)
    if not (enabled() and refresh):
        return None
    return (await _token_request({"refresh_token": refresh, "grant_type": "refresh_token"}))["access_token"]


async def create_sheet(uid: int, title: str, rows: list[list]) -> str:
    """Создаёт таблицу и заполняет. Возвращает ссылку."""
    token = await access_token(uid)
    if not token:
        raise RuntimeError("Google не подключён: попроси пользователя выполнить /calendar")
    h = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession(headers=h) as s:
        async with s.post("https://sheets.googleapis.com/v4/spreadsheets", json={"properties": {"title": title}}) as r:
            if r.status != 200:
                raise RuntimeError(f"sheets create failed: {r.status}")
            sheet = await r.json()
        async with s.put(
            f"https://sheets.googleapis.com/v4/spreadsheets/{sheet['spreadsheetId']}/values/A1",
            params={"valueInputOption": "USER_ENTERED"}, json={"values": rows},
        ) as r:
            if r.status != 200:
                raise RuntimeError(f"sheets fill failed: {r.status}")
    return sheet["spreadsheetUrl"]


async def create_gmail_draft(uid: int, to: str, subject: str, body: str) -> None:
    """Только черновик: пользователь сам проверяет и отправляет."""
    import base64
    from email.message import EmailMessage

    token = await access_token(uid)
    if not token:
        raise RuntimeError("Google не подключён: попроси пользователя выполнить /calendar")
    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    async with aiohttp.ClientSession() as s, s.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
        json={"message": {"raw": raw}}, headers={"Authorization": f"Bearer {token}"},
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"gmail draft failed: {r.status}")


async def add_event(uid: int, at: datetime, text: str) -> bool:
    """Создаёт событие и напоминание за 3 дня/в момент. False, если календарь не подключён или ошибка."""
    refresh = await db.get_google_token(uid)
    if not (enabled() and refresh):
        return False
    try:
        access = (await _token_request({"refresh_token": refresh, "grant_type": "refresh_token"}))["access_token"]
        event = {
            "summary": text,
            "start": {"dateTime": at.isoformat()},
            "end": {"dateTime": (at + timedelta(hours=1)).isoformat()},
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 60 * 24 * 3},
                                                              {"method": "popup", "minutes": 0}]},
        }
        async with aiohttp.ClientSession() as s, s.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            json=event, headers={"Authorization": f"Bearer {access}"},
        ) as r:
            return r.status == 200
    except Exception:
        logging.exception("gcal add_event failed")
        return False
