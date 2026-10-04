import asyncio
import hashlib
import hmac
import json
import os
import time
from types import SimpleNamespace as NS
from urllib.parse import urlencode

os.environ.update(TELEGRAM_BOT_TOKEN="1:abc", ANTHROPIC_API_KEY="x", DB_PATH="/tmp/test_bot.db",
                  STARS_MONTH="500", WEBAPP_URL="https://x.io", SITES_DIR="/tmp/test_sites")
if os.path.exists("/tmp/test_bot.db"):
    os.remove("/tmp/test_bot.db")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from bot import ai, db, tools, web  # noqa: E402


def run(c):
    return asyncio.run(c)


def test_agent_loop_calls_tool_then_answers(monkeypatch):
    run(db.init())
    calls = []

    async def fake_create(**kw):
        calls.append(kw)
        if len(calls) == 1:
            blk = NS(type="tool_use", id="t1", name="remember", input={"fact": "ниша: маникюр"})
            return NS(content=[blk], stop_reason="tool_use")
        return NS(content=[NS(type="text", text="Готово")], stop_reason="end_turn")

    monkeypatch.setattr(ai.client.messages, "create", fake_create)
    ctx = tools.Ctx(7, bot=None)
    out = run(ai.ask([{"role": "user", "content": "привет"}], ctx=ctx))
    assert out == "Готово" and len(calls) == 2
    assert run(db.facts(7)) == ["ниша: маникюр"]
    assert calls[1]["messages"][-1]["content"][0]["type"] == "tool_result"


def test_reminder_rejects_past_and_saves_future():
    run(db.init())
    ctx = tools.Ctx(8, bot=None)
    assert "прошлом" in run(tools.run("set_reminder", {"when": "2001-01-01 10:00", "text": "x"}, ctx))
    assert "поставлено" in run(tools.run("set_reminder", {"when": "2099-01-01 10:00", "text": "x"}, ctx))


def test_tool_error_is_reported_not_raised():
    ctx = tools.Ctx(9, bot=None)
    assert "Ошибка" in run(tools.run("instagram_profile", {"username": "a"}, ctx))


def test_quota_and_bonus():
    async def go():
        await db.init()
        u = await db.get_user(100, "a")
        assert db.free_left(u) == 3
        await db.add_bonus(100, 3)
        await db.bump_used(100)
        assert db.free_left(await db.get_user(100)) == 5
    run(go())


def sign(uid):
    d = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid, "first_name": "T"})}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    sec = hmac.new(b"WebAppData", b"1:abc", hashlib.sha256).digest()
    d["hash"] = hmac.new(sec, chk.encode(), hashlib.sha256).hexdigest()
    return urlencode(d)


def test_web_api():
    async def go():
        await db.init()
        links = []

        class FakeBot:
            async def me(self): return NS(username="b")
            async def create_invoice_link(self, **kw): links.append(kw); return "https://t.me/$x"

        async with TestClient(TestServer(web.make_app(FakeBot()))) as c:
            assert (await c.get("/api/me")).status == 401
            h = {"X-Init-Data": sign(5)}
            me = await (await c.get("/api/me", headers=h)).json()
            assert me["stars_price"] == 500 and me["free_left"] == 3 and me["payments"]
            r = await c.post("/api/invoice", json={"plan": "stars"}, headers=h)
            assert (await r.json())["link"] and links[0]["subscription_period"] == 2592000
            assert (await c.post("/api/cancel", headers=h)).status == 400  # нет подписки
            from bot import services
            url = services.publish_site("<h1>hi</h1>")
            r = await c.get("/s/" + url.rsplit("/", 1)[1])
            assert r.status == 200 and "sandbox" in r.headers["Content-Security-Policy"]
            assert (await c.get("/s/..%2Fbot")).status == 404
    run(go())


def test_credits_granted_spent_and_floored():
    async def go():
        await db.init()
        await db.get_user(200, "a")
        await db.add_subscription(200, "week", 7, 790)
        assert (await db.get_user(200))["credits"] == 40
        await db.spend(200, 3)
        assert (await db.get_user(200))["credits"] == 37
        await db.spend(200, 999)
        assert (await db.get_user(200))["credits"] == 0
        await db.add_credits(200, 50)
        assert (await db.get_user(200))["credits"] == 50
    run(go())


def test_extra_cost_for_expensive_tools(monkeypatch):
    from bot import services
    async def fake_ig(u): return "{}"
    monkeypatch.setattr(services, "instagram_profile", fake_ig)
    monkeypatch.setattr(tools.config, "APIFY_TOKEN", "t")
    ctx = tools.Ctx(1, bot=None)
    run(tools.run("instagram_profile", {"username": "a"}, ctx))
    assert ctx.extra_cost == 1


def test_topup_requires_subscription_and_web_exposes_credits():
    async def go():
        await db.init()

        class FakeBot:
            async def me(self): return NS(username="b")
            async def create_invoice_link(self, **kw): return "https://t.me/$t"

        async with TestClient(TestServer(web.make_app(FakeBot()))) as c:
            h = {"X-Init-Data": sign(300)}
            me = await (await c.get("/api/me", headers=h)).json()
            assert me["credits"] == 0 and me["topup"]["stars"] == 200
            assert (await c.post("/api/invoice", json={"plan": "topup_stars"}, headers=h)).status == 403
            await db.add_subscription(300, "month", 30, 1490)
            r = await c.post("/api/invoice", json={"plan": "topup_stars"}, headers=h)
            assert r.status == 200
            assert (await (await c.get("/api/me", headers=h)).json())["credits"] == 150
    run(go())


def test_places_sorted_filtered_and_location_fallback(monkeypatch):
    from bot import services
    async def fake_overpass(q):
        return {"elements": [
            {"lat": 54.7200, "lon": 55.9500, "tags": {"name": "Далеко", "cuisine": "italian"}},
            {"lat": 54.7101, "lon": 55.9501, "tags": {"name": "Близко", "cuisine": "georgian;italian", "addr:street": "Ленина", "addr:housenumber": "1"}},
            {"center": {"lat": 54.7105, "lon": 55.9505}, "tags": {"name": "Way-кафе"}},
            {"lat": 54.71, "lon": 55.95, "tags": {}},  # без названия — пропускаем
        ]}
    monkeypatch.setattr(services, "_overpass", fake_overpass)
    res = run(services.nearby_places(54.71, 55.95, cuisine="italian"))
    assert [r["name"] for r in res] == ["Близко", "Далеко"] and res[0]["address"] == "Ленина, 1"
    assert services.haversine(54.71, 55.95, 54.71, 55.95) == 0
    assert "Нужен адрес" in run(tools.run("find_places", {}, tools.Ctx(1, bot=None)))
    out = run(tools.run("find_places", {"cuisine": "italian"}, tools.Ctx(1, bot=None, location=(54.71, 55.95))))
    assert "Близко" in out and "yandex.ru/maps" in out


def test_2gis_parse_and_fallback(monkeypatch):
    from bot import services
    items = [{"name": "Пушкин", "address_name": "Ленина, 1", "point": {"lat": 54.7101, "lon": 55.9501},
              "rubrics": [{"name": "Рестораны"}], "reviews": {"general_rating": 4.6, "general_review_count": 120},
              "schedule": {"Mon": {"working_hours": [{"from": "09:00", "to": "22:00"}]}},
              "contact_groups": [{"contacts": [{"type": "phone", "text": "+7 347 000-00-00"}]}]},
             {"name": "", "point": {"lat": 1, "lon": 1}}]
    r = services.parse_dgis(items, 54.71, 55.95)
    assert len(r) == 1 and r[0]["rating"] == 4.6 and r[0]["hours"] == "Mon 09:00-22:00" and r[0]["phone"].startswith("+7")

    async def boom(*a, **k): raise RuntimeError("2ГИС вернул 403")
    async def osm(*a, **k): return [{"name": "OSM-кафе", "distance_m": 5}]
    monkeypatch.setattr(tools.config, "DGIS_API_KEY", "k")
    monkeypatch.setattr(tools.config, "YANDEX_SEARCH_KEY", "")
    monkeypatch.setattr(services, "dgis_places", boom)
    monkeypatch.setattr(services, "nearby_places", osm)
    out = run(tools.run("find_places", {}, tools.Ctx(1, bot=None, location=(54.71, 55.95))))
    assert "OpenStreetMap" in out and "OSM-кафе" in out


def test_yandex_parse_and_chain_order(monkeypatch):
    from bot import services
    feats = [{"geometry": {"coordinates": [55.9501, 54.7101]},
              "properties": {"CompanyMetaData": {"name": "Ясли", "address": "Ленина, 2",
                                                  "Categories": [{"name": "Ресторан"}], "Hours": {"text": "ежедневно, 10:00–23:00"},
                                                  "Phones": [{"formatted": "+7 (347) 111-11-11"}], "url": "http://y.ru"}}},
             {"geometry": {"coordinates": [1, 1]}, "properties": {"CompanyMetaData": {}}}]
    r = services.parse_yandex(feats, 54.71, 55.95)
    assert len(r) == 1 and r[0]["phone"].startswith("+7") and r[0]["source"] == "Яндекс Карты"

    order = []
    async def d(*a, **k): order.append("2gis"); raise RuntimeError("x")
    async def y(*a, **k): order.append("yandex"); return [{"name": "Ясли", "distance_m": 1}]
    async def o(*a, **k): order.append("osm"); return []
    monkeypatch.setattr(tools.config, "DGIS_API_KEY", "k")
    monkeypatch.setattr(tools.config, "YANDEX_SEARCH_KEY", "k")
    monkeypatch.setattr(services, "dgis_places", d)
    monkeypatch.setattr(services, "yandex_places", y)
    monkeypatch.setattr(services, "nearby_places", o)
    out = run(tools.run("find_places", {}, tools.Ctx(1, bot=None, location=(54.71, 55.95))))
    assert order == ["2gis", "yandex"] and "Источник: Яндекс Карты" in out
