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


KINDS = {"restaurant", "cafe", "fast_food", "bar", "pub", "cinema"}


CRAFTS = (  # подстрока запроса -> тег craft в OSM
    ("электр", "electrician"), ("electric", "electrician"), ("сантех", "plumber"), ("plumb", "plumber"),
    ("плотник", "carpenter"), ("carpent", "carpenter"), ("отоплен", "hvac"), ("кондиц", "hvac"), ("hvac", "hvac"),
    ("маляр", "painter"), ("painter", "painter"), ("кровел", "roofer"), ("roof", "roofer"),
    ("замк", "locksmith"), ("lock", "locksmith"), ("мастер", "handyman"), ("handyman", "handyman"),
    ("мебел", "carpenter"), ("ремонт", "handyman"),
)


def osm_filter(kind: str) -> str | None:
    """Фильтр Overpass для категории: еда (amenity) или ремесло (craft); None — в OSM такого нет."""
    if kind in KINDS:
        return f'["amenity"="{kind}"]'
    k = kind.lower()
    return next((f'["craft"="{tag}"]' for key, tag in CRAFTS if key in k), None)


async def nearby_places(lat: float, lon: float, kind: str = "restaurant", cuisine: str = "",
                        radius: int = 1000, limit: int = 10) -> list[dict]:
    flt = osm_filter(kind)
    if not flt:
        return []
    radius = max(100, min(int(radius), 3000))
    q = f'[out:json][timeout:25];nwr{flt}(around:{radius},{lat},{lon});out center 80;'
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


# ---------- 2ГИС (основной источник, если задан DGIS_API_KEY) ----------
DGIS_URL = "https://catalog.api.2gis.com/3.0/items"
KIND_RU = {"restaurant": "ресторан", "cafe": "кафе", "fast_food": "фастфуд", "bar": "бар", "pub": "паб", "cinema": "кинотеатр"}
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


async def _dgis(path: str, params: dict) -> dict:
    params = {**params, "key": config.DGIS_API_KEY, "locale": "ru_RU"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s, s.get(
        DGIS_URL + path, params=params
    ) as r:
        body = await r.json(content_type=None)
        meta = body.get("meta", {})
        if r.status != 200 or meta.get("code", 200) != 200:
            raise RuntimeError(f"2ГИС вернул {meta.get('code', r.status)}")
        return body.get("result", {})


async def dgis_geocode(address: str) -> tuple[float, float, str]:
    res = await _dgis("/geocode", {"q": address, "fields": "items.point", "page_size": 1})
    items = [i for i in res.get("items", []) if i.get("point")]
    if not items:
        raise RuntimeError("Адрес не найден")
    it = items[0]
    return it["point"]["lat"], it["point"]["lon"], it.get("full_name") or it.get("name") or address


def _dgis_hours(schedule: dict | None) -> str:
    out = []
    for d in DAYS:
        wh = (schedule or {}).get(d, {}).get("working_hours") or []
        if wh:
            out.append(f"{d} " + ",".join(f"{w['from']}-{w['to']}" for w in wh))
    return "; ".join(out)


def parse_dgis(items: list[dict], lat: float, lon: float) -> list[dict]:
    out = []
    for it in items:
        pt = it.get("point")
        if not pt or not it.get("name"):
            continue
        contacts = [c for g in it.get("contact_groups", []) for c in g.get("contacts", [])]
        rev = it.get("reviews") or {}
        out.append({
            "name": it["name"], "address": it.get("address_name", ""),
            "cuisine": ", ".join(r.get("name", "") for r in it.get("rubrics", [])[:3]),
            "distance_m": haversine(lat, lon, pt["lat"], pt["lon"]),
            "rating": rev.get("general_rating"), "reviews": rev.get("general_review_count"),
            "hours": _dgis_hours(it.get("schedule")),
            "phone": next((c.get("text") or c.get("value", "") for c in contacts if c.get("type") == "phone"), ""),
            "website": next((c.get("value", "") for c in contacts if c.get("type") == "website"), ""),
            "map": f"https://2gis.ru/?m={pt['lon']},{pt['lat']}/17", "source": "2ГИС",
        })
    return out


async def dgis_places(lat, lon, kind="restaurant", cuisine="", radius=1000, limit=10) -> list[dict]:
    q = f"{KIND_RU.get(kind, kind)} {cuisine}".strip()
    res = await _dgis("", {
        "q": q, "point": f"{lon},{lat}", "radius": max(100, min(int(radius), 3000)),
        "sort": "distance", "sort_point": f"{lon},{lat}", "page_size": 20,
        "fields": "items.point,items.address_name,items.rubrics,items.reviews,items.schedule,items.contact_groups",
    })
    return sorted(parse_dgis(res.get("items", []), lat, lon), key=lambda x: x["distance_m"])[:limit]


# ---------- Яндекс (Поиск по организациям + Геокодер) ----------
async def _yget(url: str, params: dict) -> dict:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s, s.get(url, params=params) as r:
        if r.status != 200:
            raise RuntimeError(f"Яндекс вернул {r.status}")
        return await r.json(content_type=None)


async def yandex_geocode(address: str) -> tuple[float, float, str]:
    data = await _yget("https://geocode-maps.yandex.ru/1.x/", {
        "apikey": config.YANDEX_GEOCODER_KEY, "geocode": address, "format": "json", "results": 1, "lang": "ru_RU"})
    members = data["response"]["GeoObjectCollection"]["featureMember"]
    if not members:
        raise RuntimeError("Адрес не найден")
    g = members[0]["GeoObject"]
    lon, lat = map(float, g["Point"]["pos"].split())
    return lat, lon, g["metaDataProperty"]["GeocoderMetaData"]["text"]


def parse_yandex(features: list[dict], lat: float, lon: float) -> list[dict]:
    out = []
    for f in features:
        meta = f.get("properties", {}).get("CompanyMetaData", {})
        coords = f.get("geometry", {}).get("coordinates")
        if not coords or not meta.get("name"):
            continue
        out.append({
            "name": meta["name"], "address": meta.get("address", ""),
            "cuisine": ", ".join(c.get("name", "") for c in meta.get("Categories", [])[:3]),
            "distance_m": haversine(lat, lon, coords[1], coords[0]),
            "hours": (meta.get("Hours") or {}).get("text", ""),
            "phone": next((p.get("formatted", "") for p in meta.get("Phones", [])), ""),
            "website": meta.get("url", ""),
            "map": f"https://yandex.ru/maps/?pt={coords[0]},{coords[1]}&z=17&l=map", "source": "Яндекс Карты",
        })
    return out


async def yandex_places(lat, lon, kind="restaurant", cuisine="", radius=1000, limit=10) -> list[dict]:
    radius = max(100, min(int(radius), 3000))
    dlat = 2 * radius / 111000
    dlon = dlat / max(math.cos(math.radians(lat)), 0.01)
    data = await _yget("https://search-maps.yandex.ru/v1/", {
        "apikey": config.YANDEX_SEARCH_KEY, "text": f"{KIND_RU.get(kind, kind)} {cuisine}".strip(),
        "type": "biz", "lang": "ru_RU", "ll": f"{lon},{lat}", "spn": f"{dlon:.5f},{dlat:.5f}",
        "rspn": 1, "results": 20,
    })
    return sorted(parse_yandex(data.get("features", []), lat, lon), key=lambda x: x["distance_m"])[:limit]
