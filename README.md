# AI-агент в Telegram для заработка (по мотивам Spru)

Бот делает «дела за пользователя» (поиск клиентов, цены, тексты, документы, напоминания)
и зарабатывает на подписке: 3 бесплатных запроса → paywall → Неделя / Месяц.

## Запуск
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполнить токены
python -m bot.main
```

## Деньги
1. @BotFather → Payments → подключить ЮKassa → токен в `PAYMENT_PROVIDER_TOKEN`.
2. Цены: `PRICE_WEEK_RUB`, `PRICE_MONTH_RUB`. `/stats` (для `ADMIN_ID`) — пользователи, подписчики, выручка.
3. Следите за себестоимостью: запрос с веб-поиском стоит заметно дороже обычного — подберите лимиты/цену.

## Mini App (меню, онбординг, оплата)
1. Задеплойте бота на сервер с публичным **https**-адресом (VPS + Caddy/nginx, порт `WEB_PORT`) и укажите его в `WEBAPP_URL`.
2. При старте бот сам поставит кнопку «Меню» в чате — она открывает Mini App.
3. Скидка новичкам (`DISCOUNT_PERCENT` на `DISCOUNT_HOURS` часов после первого /start) и таймер настоящие: цена в счёте считается на сервере.
4. Приветственная картинка: положите `assets/welcome.png` (необязательно).
5. Без `WEBAPP_URL` бот работает как обычный чат-бот с кнопками.

## Google Календарь
1. Google Cloud Console → OAuth client (Web), включить Calendar API, redirect URI `<WEBAPP_URL>/oauth/google/callback`.
2. `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` в `.env`. Пользователь подключается командой `/calendar`.
3. Запрашивается только доступ к событиям (`calendar.events`); напоминания дублируются в календарь.

## Фото и PDF
Фото и PDF (до 20 МБ) уходят в Claude вместе с выбранным сценарием.

## Структура
- `webapp/index.html` — Mini App; `bot/web.py` — API и проверка подписи Telegram; `bot/pricing.py` — цены и скидка
- `bot/scenarios.py` — сценарии (кнопки меню), добавляйте свои под нишу
- `bot/ai.py` — Claude + веб-поиск
- `bot/db.py` — SQLite: пользователи, подписки, история, напоминания
- `bot/main.py` — хендлеры, paywall, оплата
