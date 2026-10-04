import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import (
    BufferedInputFile, CallbackQuery, FSInputFile, InlineKeyboardMarkup, LabeledPrice,
    MenuButtonWebApp, Message, PreCheckoutQuery, WebAppInfo, InlineKeyboardButton,
)
from aiohttp import web
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import ai, config, db, gcal, pricing, web as webmod
from .scenarios import SCENARIOS

logging.basicConfig(level=logging.INFO)
bot = Bot(config.BOT_TOKEN)
dp = Dispatcher()
current: dict[int, str] = {}  # user_id -> выбранный сценарий

PLANS = pricing.PLANS
WELCOME_IMG = Path(__file__).resolve().parent.parent / "assets" / "welcome.png"


def menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, s in SCENARIOS.items():
        kb.button(text=s["title"], callback_data=f"sc:{key}")
    kb.adjust(1)
    return kb.as_markup()


def paywall(created: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, (name, _, _) in PLANS.items():
        kb.button(text=f"{name} — {pricing.price(key, created)} ₽", callback_data=f"buy:{key}")
    kb.adjust(1)
    return kb.as_markup()


WELCOME = (
    "<b>Что умеет этот бот?</b>\nИИ, который общается и делает за тебя\n\n"
    "Например:\n📦 Продать на Авито\n💰 Найти клиентов\n🛒 Купить выгоднее\n📄 Разобрать договор\n\n"
    "И ещё десятки сценариев. Первые {n} запроса бесплатно."
)


@dp.message(CommandStart())
async def start(m: Message, command: CommandObject):
    await db.get_user(m.from_user.id, m.from_user.full_name)
    arg = command.args or ""
    if arg.startswith("sc_") and arg[3:] in SCENARIOS:  # пришли из Mini App
        current[m.from_user.id] = arg[3:]
        await m.answer(SCENARIOS[arg[3:]]["ask"])
        return
    text = WELCOME.format(n=config.FREE_MESSAGES)
    if WELCOME_IMG.exists():
        await m.answer_photo(FSInputFile(WELCOME_IMG), caption=text, parse_mode="HTML", reply_markup=menu())
    else:
        await m.answer(text, parse_mode="HTML", reply_markup=menu())


@dp.message(Command("calendar"))
async def calendar(m: Message):
    if not gcal.enabled():
        await m.answer("Google Календарь пока не настроен.")
        return
    if await db.get_google_token(m.from_user.id):
        await m.answer("✅ Календарь уже подключён. Переподключить: ссылка ниже.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="Подключить Google Календарь", url=gcal.auth_url(m.from_user.id))]])
    await m.answer("Я буду добавлять напоминания в твой календарь. Доступ только к событиям, можно отозвать в настройках Google.", reply_markup=kb)


@dp.message(Command("menu"))
async def show_menu(m: Message):
    await m.answer("Что делаем?", reply_markup=menu())


@dp.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id != config.ADMIN_ID:
        return
    users, paid, rev = await db.stats()
    await m.answer(f"Пользователей: {users}\nПодписчиков: {paid}\nВыручка: {rev} ₽")


@dp.callback_query(F.data.startswith("sc:"))
async def pick(c: CallbackQuery):
    key = c.data[3:]
    current[c.from_user.id] = key
    await c.message.answer(SCENARIOS[key]["ask"])
    await c.answer()


@dp.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery):
    if not config.PAYMENT_TOKEN:
        await c.answer("Оплата пока не подключена", show_alert=True)
        return
    key = c.data[4:]
    name, _, _ = PLANS[key]
    user = await db.get_user(c.from_user.id)
    price = pricing.price(key, user["created"])
    await bot.send_invoice(
        c.from_user.id,
        title=f"Подписка: {name}",
        description="Безлимитный доступ ко всем сценариям. Отмена в любой момент.",
        payload=f"{key}:{price}",
        provider_token=config.PAYMENT_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label=name, amount=price * 100)],
    )
    await c.answer()


@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@dp.message(F.successful_payment)
async def paid(m: Message):
    plan, amount = m.successful_payment.invoice_payload.split(":")
    await db.add_subscription(m.from_user.id, plan, PLANS[plan][2], int(amount))
    await m.answer("✅ Подписка активна! Пиши задачу.")


REMIND_RE = re.compile(r"REMIND\|(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\|(.+)")


async def process_reminders(text: str, uid: int) -> str:
    m = REMIND_RE.search(text)
    if m:
        tz = timezone(timedelta(hours=3))
        at = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        await db.add_reminder(uid, int(at.timestamp()), m.group(2))
        in_cal = await gcal.add_event(uid, at, m.group(2))
        text = REMIND_RE.sub("", text).strip() + "\n\n🔔 Напоминание поставлено" + (" и добавлено в Google Календарь." if in_cal else ".")
    return text


async def run(m: Message, text: str, attachment: dict | None = None, note: str = ""):
    uid = m.from_user.id
    user = await db.get_user(uid, m.from_user.full_name)
    if not await db.is_paid(uid) and user["used"] >= config.FREE_MESSAGES:
        await m.answer(
            "Бесплатные запросы закончились. Подписка окупается за первую неделю 👇",
            reply_markup=paywall(user["created"]),
        )
        return
    await bot.send_chat_action(uid, "typing")
    await db.save(uid, "user", note + text)
    scenario = SCENARIOS.get(current.get(uid, ""), {}).get("prompt")
    try:
        answer = await ai.ask(await db.history(uid), scenario, attachment)
    except Exception:
        logging.exception("AI error")
        await m.answer("Что-то пошло не так, попробуй ещё раз через минуту.")
        return
    answer = await process_reminders(answer, uid)
    await db.save(uid, "assistant", answer)
    await db.bump_used(uid)
    await m.answer(answer[:4096])


@dp.message(F.text)
async def handle(m: Message):
    await run(m, m.text)


@dp.message(F.photo)
async def handle_photo(m: Message):
    buf = await bot.download(m.photo[-1])
    await run(m, m.caption or "Посмотри это фото и сделай, что нужно по выбранному сценарию.",
              ai.attachment_block(buf.read(), "image"), "[фото] ")


@dp.message(F.document)
async def handle_doc(m: Message):
    d = m.document
    if d.mime_type != "application/pdf" or (d.file_size or 0) > 20 * 1024 * 1024:
        await m.answer("Пока принимаю PDF до 20 МБ и фото.")
        return
    buf = await bot.download(d)
    await run(m, m.caption or "Разбери документ: суть, риски, что поправить.",
              ai.attachment_block(buf.read(), "pdf"), f"[PDF {d.file_name}] ")


async def reminder_loop():
    while True:
        for _, uid, text in await db.due_reminders():
            await bot.send_message(uid, f"🔔 {text}")
        await asyncio.sleep(30)


async def main():
    await db.init()
    asyncio.create_task(reminder_loop())
    if config.WEBAPP_URL:
        runner = web.AppRunner(webmod.make_app(bot))
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", config.WEB_PORT).start()
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Меню", web_app=WebAppInfo(url=config.WEBAPP_URL))
        )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
