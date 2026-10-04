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
    t.append({"name": "find_places", "description": "Найти организации рядом с адресом или геопозицией пользователя: рестораны/кафе/бары или услуги (электрик, сантехник, мастер на дом и т.п. — через query). Данные 2ГИС, Яндекс Карт или OpenStreetMap: название, рейтинг и отзывы — если есть в данных, кухня, адрес, расстояние, часы, телефон, ссылка на карту). Если рейтинга в данных нет — не выдумывай его; можно дополнить веб-поиском с указанием источника. Укажи пользователю источник данных.",
              "input_schema": {"type": "object", "properties": {
                  "address": {"type": "string", "description": "Адрес/место; не указывай, если нужно искать рядом с геопозицией пользователя"},
                  "kind": {"type": "string", "enum": sorted(services.KINDS), "description": "Для еды"},
                  "query": {"type": "string", "description": "Свободная категория вместо kind, по-русски: «электрик», «сантехник», «мастер на дом», «ремонт техники»"},
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
    if config.N8N_WEBHOOKS and config.N8N_SECRET:
        names = sorted(config.N8N_WEBHOOKS)
        t.append({"name": "run_workflow",
                  "description": "Запустить заранее настроенный процесс n8n. Доступные:\n" + "\n".join(
                      f"- {n}: {w.get('description', '')}" + (" [ТРЕБУЕТ ПОДТВЕРЖДЕНИЯ]" if w.get("confirm") else "")
                      for n, w in sorted(config.N8N_WEBHOOKS.items())) +
                  "\nПроцессы с пометкой ТРЕБУЕТ ПОДТВЕРЖДЕНИЯ меняют что-то во внешнем мире (публикуют, отправляют): "
                  "сначала покажи пользователю, что именно будет сделано, и вызывай только после его явного «да».",
                  "input_schema": {"type": "object", "properties": {
                      "name": {"type": "string", "enum": names},
                      "payload": {"type": "object", "description": "Поля, которые принимает процесс"},
                      "user_confirmed": {"type": "boolean", "description": "true, только если пользователь явно подтвердил действие"}},
                      "required": ["name", "payload"]}})
    if config.WEBAPP_URL:
        t.append({"name": "publish_site", "description": "Опубликовать одностраничный сайт (полный HTML со встроенным CSS, без внешних скриптов) и получить ссылку.",
                  "input_schema": {"type": "object", "properties": {"html": {"type": "string"}}, "required": ["html"]}})
    return t


async def _first(funcs, *args):
    """Пробует источники по порядку; ошибка предыдущего не мешает следующему."""
    last = None
    for f in funcs:
        try:
            return await f(*args)
        except Exception as e:
            logging.exception("source %s failed", getattr(f, "__name__", f))
            last = e
    raise last


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
            geocoders = [g for ok, g in ((config.DGIS_API_KEY, services.dgis_geocode),
                                         (config.YANDEX_GEOCODER_KEY, services.yandex_geocode),
                                         (True, services.geocode)) if ok]
            finders = [(n, f) for ok, n, f in ((config.DGIS_API_KEY, "2ГИС", services.dgis_places),
                                               (config.YANDEX_SEARCH_KEY, "Яндекс Карты", services.yandex_places),
                                               (True, "OpenStreetMap", services.nearby_places)) if ok]
            if args.get("address"):
                lat, lon, shown = await _first(geocoders, args["address"])
            elif ctx.location:
                (lat, lon), shown = ctx.location, "геопозиция пользователя"
            else:
                return "Нужен адрес или геопозиция: попроси пользователя прислать адрес или нажать «Отправить геопозицию»."
            a = (lat, lon, args.get("query") or args.get("kind", "restaurant"), args.get("cuisine", ""),
                 args.get("radius_m", 1000))
            for src, finder in finders:  # первый источник, который дал результат
                try:
                    places = await finder(*a)
                except Exception:
                    logging.exception("%s failed, trying next source", src)
                    continue
                if places:
                    return f"Источник: {src}. Центр поиска: {shown}\n" + "\n".join(str(x) for x in places)
            return f"Рядом с «{shown}» ничего не найдено: предложи увеличить радиус или поискать через веб."
        if name == "instagram_profile":
            result = await services.instagram_profile(args["username"])
            ctx.extra_cost += 1
            return result
        if name == "edit_photo":
            img = await services.edit_image(ctx.last_image, args["instruction"])
            await ctx.bot.send_photo(ctx.uid, BufferedInputFile(img, "result.jpg"))
            ctx.extra_cost += 2
            return "Готово, результат отправлен пользователю."
        if name == "run_workflow":
            wf = config.N8N_WEBHOOKS.get(args["name"])
            if not wf:
                return "Такого процесса нет."
            if wf.get("confirm") and not args.get("user_confirmed"):
                return "Нужно подтверждение: покажи пользователю, что будет сделано, и спроси «да/нет»."
            return "Ответ n8n: " + await services.call_n8n(args["name"], args.get("payload", {}), ctx.uid)
        if name == "publish_site":
            return "Сайт опубликован: " + services.publish_site(args["html"])
        return f"Неизвестный инструмент {name}"
    except Exception as e:
        logging.exception("tool %s failed", name)
        return f"Ошибка инструмента: {e}"
