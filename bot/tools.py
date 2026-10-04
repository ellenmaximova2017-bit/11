"""Инструменты агента: что Claude может делать за пользователя. Показываем только настроенные."""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import BufferedInputFile

from . import config, db, gcal, services

TZ = timezone(timedelta(hours=3))


@dataclass
class Ctx:
    uid: int
    bot: Bot
    last_image: bytes | None = None
    location: tuple[float, float] | None = None  # геопозиция из Telegram (только в памяти)
    extra_cost: int = 0  # дорогие операции списывают больше запросов


def specs(ctx: Ctx) -> list[dict]:
    t = [
        {"name": "remember", "description": "Запомнить устойчивый факт о пользователе (ниша, город, услуги, предпочтения) для будущих диалогов. Не сохраняй пароли, документы и платёжные данные.",
         "input_schema": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}},
        {"name": "set_reminder", "description": "Поставить напоминание пользователю (и добавить в Google Календарь, если он подключён). Время по Москве.",
         "input_schema": {"type": "object", "properties": {
             "when": {"type": "string", "description": "YYYY-MM-DD HH:MM, UTC+3"}, "text": {"type": "string"}},
             "required": ["when", "text"]}},
    ]
    t.append({"name": "find_places", "description": "Найти рестораны/кафе/бары рядом с адресом или с геопозицией пользователя (данные 2ГИС или OpenStreetMap: название, рейтинг и отзывы — если есть в данных, кухня, адрес, расстояние, часы, телефон, ссылка на карту). Если рейтинга в данных нет — не выдумывай его; можно дополнить веб-поиском с указанием источника. Укажи пользователю источник данных.",
              "input_schema": {"type": "object", "properties": {
                  "address": {"type": "string", "description": "Адрес/место; не указывай, если нужно искать рядом с геопозицией пользователя"},
                  "kind": {"type": "string", "enum": sorted(services.KINDS)},
                  "cuisine": {"type": "string", "description": "Например итальянская, суши, грузинская (по-русски для 2ГИС; для OSM — italian, sushi)"},
                  "radius_m": {"type": "integer", "description": "100-3000, по умолчанию 1000"}}}})
    if gcal.enabled():
        t += [
            {"name": "create_google_sheet", "description": "Создать Google Таблицу в аккаунте пользователя и заполнить. Первая строка — заголовки.",
             "input_schema": {"type": "object", "properties": {
                 "title": {"type": "string"},
                 "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}},
                 "required": ["title", "rows"]}},
            {"name": "create_gmail_draft", "description": "Создать ЧЕРНОВИК письма в Gmail пользователя (не отправляет). Скажи пользователю проверить и отправить самому.",
             "input_schema": {"type": "object", "properties": {
                 "to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
                 "required": ["to", "subject", "body"]}},
        ]
    if config.APIFY_TOKEN:
        t.append({"name": "instagram_profile", "description": "Получить публичные данные Instagram-профиля и последних 30 постов (охваты, лайки, шапка).",
                  "input_schema": {"type": "object", "properties": {"username": {"type": "string"}}, "required": ["username"]}})
    if config.REPLICATE_API_TOKEN and ctx.last_image:
        t.append({"name": "edit_photo", "description": "Отредактировать последнее присланное пользователем фото по инструкции (убрать человека/предмет, заменить фон, улучшить) и отправить результат ему.",
                  "input_schema": {"type": "object", "properties": {"instruction": {"type": "string", "description": "Что изменить, по-английски"}}, "required": ["instruction"]}})
    if config.WEBAPP_URL:
        t.append({"name": "publish_site", "description": "Опубликовать одностраничный сайт (полный HTML со встроенным CSS, без внешних скриптов) и получить ссылку.",
                  "input_schema": {"type": "object", "properties": {"html": {"type": "string"}}, "required": ["html"]}})
    return t


async def _first(primary, fallback, *args):
    """Пробует основной источник, при ошибке — запасной."""
    if primary:
        try:
            return await primary(*args)
        except Exception:
            logging.exception("primary source failed, using fallback")
    return await fallback(*args)


async def run(name: str, args: dict, ctx: Ctx) -> str:
    try:
        if name == "remember":
            await db.add_fact(ctx.uid, args["fact"])
            return "Запомнил."
        if name == "set_reminder":
            at = datetime.strptime(args["when"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
            if at.timestamp() < datetime.now(TZ).timestamp():
                return "Ошибка: время в прошлом."
            await db.add_reminder(ctx.uid, int(at.timestamp()), args["text"])
            in_cal = await gcal.add_event(ctx.uid, at, args["text"])
            return "Напоминание поставлено" + (" и добавлено в Google Календарь." if in_cal else ".")
        if name == "create_google_sheet":
            return "Таблица создана: " + await gcal.create_sheet(ctx.uid, args["title"], args["rows"][:1000])
        if name == "create_gmail_draft":
            await gcal.create_gmail_draft(ctx.uid, args["to"], args["subject"], args["body"])
            return "Черновик создан в Gmail."
        if name == "find_places":
            src = "OpenStreetMap"
            if args.get("address"):
                lat, lon, shown = await _first(config.DGIS_API_KEY and services.dgis_geocode, services.geocode,
                                               args["address"])
            elif ctx.location:
                (lat, lon), shown = ctx.location, "геопозиция пользователя"
            else:
                return "Нужен адрес или геопозиция: попроси пользователя прислать адрес или нажать «Отправить геопозицию»."
            a = (lat, lon, args.get("kind", "restaurant"), args.get("cuisine", ""), args.get("radius_m", 1000))
            places = []
            if config.DGIS_API_KEY:
                try:
                    places, src = await services.dgis_places(*a), "2ГИС"
                except Exception:
                    logging.exception("2gis failed, fallback to OSM")
            if not places:
                places, src = await services.nearby_places(*a), "OpenStreetMap"
            if not places:
                return f"Рядом с «{shown}» ничего не найдено: предложи увеличить радиус или поискать через веб."
            return f"Источник: {src}. Центр поиска: {shown}\n" + "\n".join(str(x) for x in places)
        if name == "instagram_profile":
            result = await services.instagram_profile(args["username"])
            ctx.extra_cost += 1
            return result
        if name == "edit_photo":
            img = await services.edit_image(ctx.last_image, args["instruction"])
            await ctx.bot.send_photo(ctx.uid, BufferedInputFile(img, "result.jpg"))
            ctx.extra_cost += 2
            return "Готово, результат отправлен пользователю."
        if name == "publish_site":
            return "Сайт опубликован: " + services.publish_site(args["html"])
        return f"Неизвестный инструмент {name}"
    except Exception as e:
        logging.exception("tool %s failed", name)
        return f"Ошибка инструмента: {e}"
