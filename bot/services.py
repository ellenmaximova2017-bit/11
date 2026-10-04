"""Внешние сервисы: Instagram (Apify), правка фото (Replicate), голос (Whisper), публикация сайтов."""
import asyncio
import base64
import math
import re
import secrets
from pathlib import Path

import aiohttp

from . import config


def _need(value: str, name: str):
    if not value:
        raise RuntimeError(f"Не настроен {name}")


async def instagram_profile(username: str) -> str:
    _need(config.APIFY_TOKEN, "APIFY_TOKEN")
    username = username.lstrip("@").strip()
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", username):
        raise RuntimeError("Некорректный ник")
    url = "https://api.apify.com/v2/acts/apify~instagram-profile-scraper/run-sync-get-dataset-items"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as s, s.post(
        url, params={"token": config.APIFY_TOKEN}, json={"usernames": [username]}
    ) as r:
        if r.status not in (200, 201):
            raise RuntimeError(f"Apify вернул {r.status}")
        items = await r.json()
    if not items:
        return "Профиль не найден или закрыт."
    p = items[0]
    posts = [
        {"likes": x.get("likesCount"), "comments": x.get("commentsCount"),
         "type": x.get("type"), "caption": (x.get("caption") or "")[:200]}
        for x in (p.get("latestPosts") or [])[:30]
    ]
    return str({
        "followers": p.get("followersCount"), "following": p.get("followsCount"),
        "posts_total": p.get("postsCount"), "bio": p.get("biography"),
        "category": p.get("businessCategoryName"), "latest_posts": posts,
    })


async def edit_image(image: bytes, prompt: str) -> bytes:
    _need(config.REPLICATE_API_TOKEN, "REPLICATE_API_TOKEN")
    data_uri = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    headers = {"Authorization": f"Bearer {config.REPLICATE_API_TOKEN}", "Prefer": "wait=60"}
    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=240)) as s:
        async with s.post(
            f"https://api.replicate.com/v1/models/{config.REPLICATE_EDIT_MODEL}/predictions",
            json={"input": {"prompt": prompt, "input_image": data_uri, "output_format": "jpg"}},
        ) as r:
            if r.status not in (200, 201):
                raise RuntimeError(f"Replicate вернул {r.status}")
            pred = await r.json()
        for _ in range(60):  # дождаться, если не успело за wait=60
            if pred["status"] in ("succeeded", "failed", "canceled"):
                break
            await asyncio.sleep(3)
            async with s.get(pred["urls"]["get"]) as r:
                pred = await r.json()
        if pred["status"] != "succeeded":
            raise RuntimeError("Не удалось обработать фото")
        out = pred["output"]
        async with s.get(out[0] if isinstance(out, list) else out) as r:
            return await r.read()


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    _need(config.OPENAI_API_KEY, "OPENAI_API_KEY")
    form = aiohttp.FormData()
    form.add_field("model", "whisper-1")
    form.add_field("file", audio, filename=filename)
    async with aiohttp.ClientSession() as s, s.post(
        "https://api.openai.com/v1/audio/transcriptions", data=form,
        headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"Whisper вернул {r.status}")
        return (await r.json())["text"]


def publish_site(html: str) -> str:
    """Сохраняет HTML и возвращает публичную ссылку (/s/<slug>)."""
    _need(config.WEBAPP_URL, "WEBAPP_URL")
    if len(html) > 500_000:
        raise RuntimeError("Страница слишком большая")
    slug = secrets.token_urlsafe(6).replace("_", "x").replace("-", "y")
    Path(config.SITES_DIR).mkdir(parents=True, exist_ok=True)
    (Path(config.SITES_DIR) / f"{slug}.html").write_text(html, encoding="utf-8")
    return f"{config.WEBAPP_URL.rstrip('/')}/s/{slug}"


UA = {"User-Agent": "earnings-bot/1.0 (telegram assistant)"}  # требование Nominatim


async def geocode(address: str) -> tuple[float, float, str]:
    async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=20)) as s, s.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": address, "format": "json", "limit": 1, "accept-language": "ru"},
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"Геокодер вернул {r.status}")
        data = await r.json()
    if not data:
        raise RuntimeError("Адрес не найден, попроси уточнить (город, улица, дом)")
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"]


async def _overpass(query: str) -> dict:
    async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=40)) as s, s.post(
        "https://overpass-api.de/api/interpreter", data={"data": query}
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"Overpass вернул {r.status}")
        return await r.json()


def haversine(lat1, lon1, lat2, lon2) -> int:
    """Расстояние в метрах."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return round(6371000 * 2 * math.asin(math.sqrt(a)))


KINDS = {"restaurant", "cafe", "fast_food", "bar", "pub"}


async def nearby_places(lat: float, lon: float, kind: str = "restaurant", cuisine: str = "",
                        radius: int = 1000, limit: int = 10) -> list[dict]:
    kind = kind if kind in KINDS else "restaurant"
    radius = max(100, min(int(radius), 3000))
    q = f'[out:json][timeout:25];nwr["amenity"="{kind}"](around:{radius},{lat},{lon});out center 80;'
    out = []
    for el in (await _overpass(q)).get("elements", []):
        t = el.get("tags", {})
        if not t.get("name"):
            continue
        plat = el.get("lat") or el.get("center", {}).get("lat")
        plon = el.get("lon") or el.get("center", {}).get("lon")
        if plat is None or (cuisine and cuisine.lower() not in t.get("cuisine", "").lower()):
            continue
        addr = ", ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x)
        out.append({
            "name": t["name"], "cuisine": t.get("cuisine", ""), "address": addr,
            "distance_m": haversine(lat, lon, plat, plon), "hours": t.get("opening_hours", ""),
            "phone": t.get("phone") or t.get("contact:phone", ""), "website": t.get("website", ""),
            "map": f"https://yandex.ru/maps/?pt={plon},{plat}&z=17&l=map",
        })
    return sorted(out, key=lambda x: x["distance_m"])[:limit]
