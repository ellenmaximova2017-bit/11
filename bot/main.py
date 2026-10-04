import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
    Message, PreCheckoutQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import ai, config, db
from .scenarios import SCENARIOS

logging.basicConfig(level=logging.INFO)
bot = Bot(config.BOT_TOKEN)
dp = Dispatcher()
current: dict[int, str] = {}  # user_id -> выбранный сценарий

PLANS = {
    "month": ("Месяц", config.PRICE_MONTH, 30),
    "week": ("Неделя", config.PRICE_WEEK, 7),
}


def menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, s in SCENARIOS.items():
        kb.button(text=s["title"], callback_data=f"sc:{key}")
    kb.adjust(1)
    return kb.as_markup()


def paywall() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, (name, price, _) in PLANS.items():
        kb.button(text=f"{name} — {price} ₽", callback_data=f"buy:{key}")
    kb.adjust(1)
    return kb.as_markup()


@dp.message(CommandStart())
async def start(m: Message):
    await db.get_user(m.from_user.id, m.from_user.full_name)
    await m.answer(
        f"Привет, {m.from_user.first_name}! Я делаю дела за тебя: нахожу клиентов, "
        f"сравниваю цены, пишу тексты, разбираю документы.\n\n"
        f"Выбери сценарий или просто напиши задачу. Первые {config.FREE_MESSAGES} запроса бесплатно.",
        reply_markup=menu(),
    )


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
    name, price, _ = PLANS[key]
    await bot.send_invoice(
        c.from_user.id,
        title=f"Подписка: {name}",
        description="Безлимитный доступ ко всем сценариям. Отмена в любой момент.",
        payload=key,
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
    plan = m.successful_payment.invoice_payload
    _, price, days = PLANS[plan]
    await db.add_subscription(m.from_user.id, plan, days, price)
    await m.answer("✅ Подписка активна! Пиши задачу.")


REMIND_RE = re.compile(r"REMIND\|(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\|(.+)")


async def process_reminders(text: str, uid: int) -> str:
    m = REMIND_RE.search(text)
    if m:
        tz = timezone(timedelta(hours=3))
        at = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        await db.add_reminder(uid, int(at.timestamp()), m.group(2))
        text = REMIND_RE.sub("", text).strip() + "\n\n🔔 Напоминание поставлено."
    return text


@dp.message(F.text)
async def handle(m: Message):
    uid = m.from_user.id
    user = await db.get_user(uid, m.from_user.full_name)
    if not await db.is_paid(uid) and user["used"] >= config.FREE_MESSAGES:
        await m.answer(
            "Бесплатные запросы закончились. Подписка окупается за первую неделю 👇",
            reply_markup=paywall(),
        )
        return
    await bot.send_chat_action(uid, "typing")
    await db.save(uid, "user", m.text)
    scenario = SCENARIOS.get(current.get(uid, ""), {}).get("prompt")
    try:
        answer = await ai.ask(await db.history(uid), scenario)
    except Exception:
        logging.exception("AI error")
        await m.answer("Что-то пошло не так, попробуй ещё раз через минуту.")
        return
    answer = await process_reminders(answer, uid)
    await db.save(uid, "assistant", answer)
    await db.bump_used(uid)
    await m.answer(answer[:4096])


async def reminder_loop():
    while True:
        for _, uid, text in await db.due_reminders():
            await bot.send_message(uid, f"🔔 {text}")
        await asyncio.sleep(30)


async def main():
    await db.init()
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
