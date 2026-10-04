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

## Структура
- `bot/scenarios.py` — сценарии (кнопки меню), добавляйте свои под нишу
- `bot/ai.py` — Claude + веб-поиск
- `bot/db.py` — SQLite: пользователи, подписки, история, напоминания
- `bot/main.py` — хендлеры, paywall, оплата
