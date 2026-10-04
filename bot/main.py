import asyncio
import logging
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
    KeyboardButton, MenuButtonWebApp, Message, PreCheckoutQuery, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web

from . import ai, config, db, gcal, pricing, services, tools, web as webmod
from .scenarios import SCENARIOS

logging.basicConfig(level=logging.INFO)
bot = Bot(config.BOT_TOKEN)
dp = Dispatcher()

PLANS = pricing.PLANS
WELCOME_IMG = Path(__file__).resolve().parent.parent / "assets" / "welcome.png"
current: dict[int, str] = {}        # user_id -> выбранный сценарий
last_image: dict[int, bytes] = {}   # user_id -> последнее фото (для edit_photo)
last_location: dict[int, tuple[float, float]] = {}  # только в памяти, в базу не пишем
locks: dict[int, asyncio.Lock] = {}
PRIVATE = F.chat.type == "private"
GROUP = F.chat.type.in_({"group", "supergroup"})


# ---------- клавиатуры ----------
def menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, s in SCENARIOS.items():
        kb.button(text=s["title"], callback_data=f"sc:{key}")
    kb.adjust(1)
    return kb.as_markup()


def paywall(created: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if config.STARS_MONTH:
        kb.button(text=f"Месяц ⭐{config.STARS_MONTH} (автопродление)", callback_data="buy:stars")
    for key, (name, _, _) in PLANS.items():
        kb.button(text=f"{name} — {pricing.price(key, created)} ₽", callback_data=f"buy:{key}")
    kb.adjust(1)
    return kb.as_markup()


def topup_kb() -> InlineKeyboardMarkup | None:
    kb = InlineKeyboardBuilder()
    if config.TOPUP_RUB and config.PAYMENT_TOKEN:
        kb.button(text=f"+{config.TOPUP_CREDITS} запросов — {config.TOPUP_RUB} ₽", callback_data="buy:topup")
    if config.TOPUP_STARS:
        kb.button(text=f"+{config.TOPUP_CREDITS} запросов — ⭐{config.TOPUP_STARS}", callback_data="buy:topup_stars")
    kb.adjust(1)
    return kb.as_markup() if kb.buttons else None


LIMIT_TEXT = ("Запросы по подписке закончились. Можно докупить пакет — он добавится к лимиту, "
              "подписка при этом не меняется 👇")


async def gate(uid: int, user) -> tuple[bool, bool]:
    """(можно ли выполнять запрос, подписчик ли). Лимит подписки и бесплатный лимит считаются отдельно."""
    paid_user = await db.is_paid(uid)
    return (user["credits"] > 0 if paid_user else db.free_left(user) > 0), paid_user


async def charge(uid: int, paid_user: bool, cost: int = 1):
    await (db.spend(uid, cost) if paid_user else db.bump_used(uid))


@dp.message(Command("balance"), PRIVATE)
async def balance(m: Message):
    user = await db.get_user(m.from_user.id)
    if await db.is_paid(m.from_user.id):
        left = max(int((user["paid_until"] - time.time()) // 86400), 0)
        await m.answer(f"✅ Подписка активна (~{left} дн.)\nОсталось запросов: {user['credits']}\n"
                       "Правка фото списывает 3 запроса, анализ Instagram — 2, остальное — 1.",
                       reply_markup=topup_kb())
    else:
        await m.answer(f"Подписки нет. Бесплатных запросов: {db.free_left(user)}", reply_markup=paywall(user["created"]))


# ---------- старт, меню, профиль ----------
WELCOME = (
    "<b>Что умеет этот бот?</b>\nИИ, который общается и делает за тебя\n\n"
    "Например:\n📦 Продать на Авито\n💰 Найти клиентов\n🛒 Купить выгоднее\n📄 Разобрать договор\n"
    "🎨 Поправить фото\n🍽 Найти ресторан рядом\n\nИ ещё десятки сценариев. Можно писать текстом, голосом, слать фото и PDF.\n"
    "Первые {n} запроса бесплатно."
)


@dp.message(CommandStart(), PRIVATE)
async def start(m: Message, command: CommandObject):
    uid = m.from_user.id
    arg = command.args or ""
    new = await db.is_new(uid)
    await db.get_user(uid, m.from_user.full_name)
    if new and arg.startswith("ref_") and arg[4:].isdigit() and int(arg[4:]) != uid:
        ref = int(arg[4:])
        if not await db.is_new(ref):
            await db.set_ref(uid, ref)
            await db.add_bonus(uid, config.REFERRAL_BONUS)
            await db.add_bonus(ref, config.REFERRAL_BONUS)
            try:
                await bot.send_message(ref, f"🎁 По твоей ссылке пришёл друг: +{config.REFERRAL_BONUS} бесплатных запроса.")
            except Exception:
                pass
    if arg.startswith("sc_") and arg[3:] in SCENARIOS:  # пришли из Mini App
        current[uid] = arg[3:]
        kb = (ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]],
                                  resize_keyboard=True, one_time_keyboard=True) if arg[3:] == "food" else None)
        await m.answer(SCENARIOS[arg[3:]]["ask"], reply_markup=kb)
        return
    text = WELCOME.format(n=config.FREE_MESSAGES)
    if WELCOME_IMG.exists():
        await m.answer_photo(FSInputFile(WELCOME_IMG), caption=text, parse_mode="HTML", reply_markup=menu())
    else:
        await m.answer(text, parse_mode="HTML", reply_markup=menu())


@dp.message(Command("menu"), PRIVATE)
async def show_menu(m: Message):
    await m.answer("Что делаем?", reply_markup=menu())


@dp.message(Command("invite"), PRIVATE)
async def invite(m: Message):
    me = await bot.me()
    await m.answer(
        f"Твоя ссылка: https://t.me/{me.username}?start=ref_{m.from_user.id}\n"
        f"За каждого нового друга вы оба получите +{config.REFERRAL_BONUS} бесплатных запроса."
    )


@dp.message(Command("memory"), PRIVATE)
async def memory(m: Message):
    facts = await db.facts(m.from_user.id)
    await m.answer(("Что я о тебе помню:\n• " + "\n• ".join(facts) + "\n\nСтереть всё: /forget") if facts
                   else "Пока ничего не помню. Расскажи о себе и своих задачах.")


@dp.message(Command("forget"), PRIVATE)
async def forget(m: Message):
    await db.clear_facts(m.from_user.id)
    await m.answer("Всё забыл.")


@dp.message(Command("model"), PRIVATE)
async def model_cmd(m: Message):
    kb = InlineKeyboardBuilder()
    for key, (title, _) in config.MODELS.items():
        kb.button(text=title, callback_data=f"model:{key}")
    kb.adjust(1)
    await m.answer("Выбери модель (умная — только для подписчиков):", reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith("model:"))
async def model_pick(c: CallbackQuery):
    key = c.data[6:]
    if key not in config.MODELS:
        return await c.answer()
    if key == "pro" and not await db.is_paid(c.from_user.id):
        return await c.answer("Умная модель доступна по подписке", show_alert=True)
    await db.set_model(c.from_user.id, key)
    await c.message.answer(f"Модель: {config.MODELS[key][0]}")
    await c.answer()


@dp.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id != config.ADMIN_ID:
        return
    users, paid, rev, stars = await db.stats()
    await m.answer(f"Пользователей: {users}\nПодписчиков: {paid}\nВыручка: {rev} ₽ + ⭐{stars}")


@dp.message(Command("calendar"), PRIVATE)
async def calendar(m: Message):
    if not gcal.enabled():
        await m.answer("Google пока не настроен.")
        return
    if await db.get_google_token(m.from_user.id):
        await m.answer("✅ Google уже подключён. Переподключить: ссылка ниже.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="Подключить Google", url=gcal.auth_url(m.from_user.id))]])
    await m.answer(
        "Подключи Google, и я смогу ставить события в Календарь, создавать Таблицы и черновики писем в Gmail "
        "(письма сам не отправляю). Доступ можно отозвать в настройках Google.", reply_markup=kb)


@dp.callback_query(F.data.startswith("sc:"))
async def pick(c: CallbackQuery):
    key = c.data[3:]
    current[c.from_user.id] = key
    kb = None
    if key == "food":
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]],
                                 resize_keyboard=True, one_time_keyboard=True)
    await c.message.answer(SCENARIOS[key]["ask"], reply_markup=kb)
    await c.answer()


# ---------- оплата ----------
@dp.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery):
    key = c.data[4:]
    if key in ("topup", "topup_stars"):
        if not await db.is_paid(c.from_user.id):
            return await c.answer("Докупка доступна при активной подписке", show_alert=True)
        label = f"+{config.TOPUP_CREDITS} запросов"
        if key == "topup_stars" and config.TOPUP_STARS:
            await bot.send_invoice(c.from_user.id, title=label, description="Разовая докупка запросов к подписке.",
                                   payload="topup:stars", provider_token="", currency="XTR",
                                   prices=[LabeledPrice(label=label, amount=config.TOPUP_STARS)])
        elif key == "topup" and config.TOPUP_RUB and config.PAYMENT_TOKEN:
            await bot.send_invoice(c.from_user.id, title=label, description="Разовая докупка запросов к подписке.",
                                   payload=f"topup:{config.TOPUP_RUB}", provider_token=config.PAYMENT_TOKEN,
                                   currency="RUB", prices=[LabeledPrice(label=label, amount=config.TOPUP_RUB * 100)])
        else:
            return await c.answer("Недоступно", show_alert=True)
        return await c.answer()
    if key == "stars":
        if not config.STARS_MONTH:
            return await c.answer("Недоступно", show_alert=True)
        await bot.send_invoice(
            c.from_user.id, title="Подписка: месяц",
            description="Безлимитный доступ. Автопродление каждые 30 дней, отмена: /cancel.",
            payload="stars:month", provider_token="", currency="XTR",
            prices=[LabeledPrice(label="Месяц", amount=config.STARS_MONTH)], subscription_period=2592000,
        )
        return await c.answer()
    if not config.PAYMENT_TOKEN:
        return await c.answer("Оплата пока не подключена", show_alert=True)
    name, _, _ = PLANS[key]
    user = await db.get_user(c.from_user.id)
    price = pricing.price(key, user["created"])
    await bot.send_invoice(
        c.from_user.id, title=f"Подписка: {name}",
        description="Безлимитный доступ ко всем сценариям. Разовый платёж, без автосписаний.",
        payload=f"{key}:{price}", provider_token=config.PAYMENT_TOKEN, currency="RUB",
        prices=[LabeledPrice(label=name, amount=price * 100)],
    )
    await c.answer()


@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@dp.message(F.successful_payment)
async def paid(m: Message):
    sp, uid = m.successful_payment, m.from_user.id
    if sp.invoice_payload.startswith("topup:"):
        await db.add_credits(uid, config.TOPUP_CREDITS)
        await db.record_payment(uid, "stars" if sp.currency == "XTR" else "topup", sp.total_amount // (1 if sp.currency == "XTR" else 100))
        await m.answer(f"✅ Добавлено {config.TOPUP_CREDITS} запросов. Пиши задачу.")
        return
    if sp.currency == "XTR":  # подписка Stars: первый платёж и каждое автопродление
        user = await db.get_user(uid)
        until = sp.subscription_expiration_date or int(time.time()) + 30 * 86400
        await db.set_paid_until(uid, max(until, user["paid_until"]))
        await db.set_sub_charge(uid, sp.telegram_payment_charge_id)
        await db.record_payment(uid, "stars", sp.total_amount)
        await db.add_credits(uid, config.CREDITS_MONTH)  # и на первую оплату, и на каждое автопродление
        if not sp.is_recurring or sp.is_first_recurring:
            await m.answer(f"✅ Подписка активна: {config.CREDITS_MONTH} запросов в месяц, продлевается автоматически. Отменить: /cancel")
        return
    plan, amount = sp.invoice_payload.split(":")
    await db.add_subscription(uid, plan, PLANS[plan][2], int(amount))
    await m.answer("✅ Подписка активна! Пиши задачу.")


@dp.message(Command("cancel"), PRIVATE)
async def cancel(m: Message):
    user = await db.get_user(m.from_user.id)
    if not user["sub_charge_id"]:
        await m.answer("Автопродления нет: разовые платежи сами не списываются.")
        return
    try:
        await bot.edit_user_star_subscription(
            user_id=m.from_user.id, telegram_payment_charge_id=user["sub_charge_id"], is_canceled=True)
    except Exception:
        logging.exception("cancel failed")
        await m.answer("Не получилось отменить. Отмените в Telegram: Настройки → Telegram Stars → Подписки.")
        return
    left = max(int((user["paid_until"] - time.time()) // 86400), 0)
    await m.answer(f"Автопродление отключено. Доступ сохранится ещё примерно {left} дн.")


# ---------- агент ----------
async def _typing(chat_id: int, stop: asyncio.Event):
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), 4)
        except asyncio.TimeoutError:
            pass


async def run(m: Message, text: str, attachment: dict | None = None, note: str = ""):
    uid = m.from_user.id
    user = await db.get_user(uid, m.from_user.full_name)
    ok, paid_user = await gate(uid, user)
    if not ok:
        if paid_user:
            await m.answer(LIMIT_TEXT, reply_markup=topup_kb())
        else:
            await m.answer("Бесплатные запросы закончились. Подписка окупается за первую неделю 👇",
                           reply_markup=paywall(user["created"]))
        return
    asyncio.create_task(_work(m, uid, text, attachment, note, user, paid_user))  # не блокируем приём сообщений


async def _work(m, uid, text, attachment, note, user, paid_user):
    async with locks.setdefault(uid, asyncio.Lock()):
        stop = asyncio.Event()
        typing = asyncio.create_task(_typing(uid, stop))
        try:
            await db.save(uid, "user", note + text)
            key = user["model"] if (user["model"] != "pro" or paid_user) else "std"
            ctx = tools.Ctx(uid, bot, last_image.get(uid), last_location.get(uid))
            answer = await ai.ask(
                await db.history(uid), SCENARIOS.get(current.get(uid, ""), {}).get("prompt"),
                attachment, ctx, config.MODELS.get(key, config.MODELS["std"])[1], await db.facts(uid),
            )
            await db.save(uid, "assistant", answer)
            await charge(uid, paid_user, 1 + ctx.extra_cost)
            await m.answer(answer[:4096])
        except Exception:
            logging.exception("AI error")
            await m.answer("Что-то пошло не так, попробуй ещё раз через минуту.")
        finally:
            stop.set()
            await typing


@dp.message(F.text, PRIVATE, ~F.text.startswith("/"))
async def handle(m: Message):
    await run(m, m.text)


@dp.message(F.location, PRIVATE)
async def handle_location(m: Message):
    last_location[m.from_user.id] = (m.location.latitude, m.location.longitude)
    current.setdefault(m.from_user.id, "food")
    await m.answer("📍 Принял. Геопозицию храню только в памяти бота, пока он работает.", reply_markup=ReplyKeyboardRemove())
    await run(m, "Найди, где поесть рядом с моей геопозицией.")


@dp.message(F.photo, PRIVATE)
async def handle_photo(m: Message):
    data = (await bot.download(m.photo[-1])).read()
    last_image[m.from_user.id] = data
    await run(m, m.caption or "Посмотри это фото и сделай, что нужно по выбранному сценарию.",
              ai.attachment_block(data, "image"), "[фото] ")


@dp.message(F.document, PRIVATE)
async def handle_doc(m: Message):
    d = m.document
    if d.mime_type != "application/pdf" or (d.file_size or 0) > 20 * 1024 * 1024:
        await m.answer("Пока принимаю PDF до 20 МБ и фото.")
        return
    await run(m, m.caption or "Разбери документ: суть, риски, что поправить.",
              ai.attachment_block((await bot.download(d)).read(), "pdf"), f"[PDF {d.file_name}] ")


@dp.message(F.voice, PRIVATE)
async def handle_voice(m: Message):
    if not config.OPENAI_API_KEY:
        await m.answer("Голосовые пока не включены, напиши текстом.")
        return
    if (m.voice.file_size or 0) > 20 * 1024 * 1024:
        await m.answer("Слишком длинное голосовое.")
        return
    try:
        text = await services.transcribe((await bot.download(m.voice)).read())
    except Exception:
        logging.exception("transcribe failed")
        await m.answer("Не удалось расшифровать голосовое, напиши текстом.")
        return
    await m.answer(f"🎤 {text}")
    await run(m, text, note="[голос] ")


# ---------- агент в групповых чатах ----------
GROUP_PROMPTS = {
    "digest": "Сделай краткую сводку обсуждения за сутки: главные темы, решения, важные сообщения. Списком.",
    "best": "Найди в переписке лучшее: полезные советы, рекомендации, контакты и ссылки, которыми поделились. Укажи, кто что предложил.",
    "tasks": "Определи по переписке, кто что обещал и сделал, а что осталось не выполнено. Таблицей: человек — задача — статус.",
}


@dp.message(Command(*GROUP_PROMPTS), GROUP)
async def group_report(m: Message, command: CommandObject):
    uid = m.from_user.id
    user = await db.get_user(uid, m.from_user.full_name)
    ok, paid_user = await gate(uid, user)
    if not ok:
        await m.reply("Запросы закончились: напиши мне в личку /balance.")
        return
    rows = await db.chat_since(m.chat.id, int(time.time()) - 86400)
    if len(rows) < 3:
        await m.reply("Пока мало сообщений: бот видит только то, что написано после его добавления "
                      "(в BotFather нужно отключить Group Privacy).")
        return
    log = "\n".join(f"{time.strftime('%H:%M', time.gmtime(ts + 3 * 3600))} {a}: {t}" for a, t, ts in rows)
    answer = await ai.ask(
        [{"role": "user", "content": f"{GROUP_PROMPTS[command.command]}\n\nПереписка:\n{log}"}],
        use_tools=False, model=config.MODELS["std"][1],
    )
    await charge(uid, paid_user)
    await m.reply(answer[:4096])


@dp.message(F.text, GROUP, ~F.text.startswith("/"))
async def group_log(m: Message):
    await db.log_chat(m.chat.id, m.from_user.full_name if m.from_user else "?", m.text)


# ---------- фон ----------
async def reminder_loop():
    tick = 0
    while True:
        for _, uid, text in await db.due_reminders():
            try:
                await bot.send_message(uid, f"🔔 {text}")
            except Exception:
                logging.exception("reminder send failed")
        tick += 1
        if tick % 120 == 0:  # раз в час чистим лог групповых чатов (храним 7 дней)
            await db.purge_chat_log()
        await asyncio.sleep(30)


async def main():
    await db.init()
    asyncio.create_task(reminder_loop())
    if config.WEBAPP_URL:
        runner = web.AppRunner(webmod.make_app(bot))
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", config.WEB_PORT).start()
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Меню", web_app=WebAppInfo(url=config.WEBAPP_URL)))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
