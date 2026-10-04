# Все ключи и права: что, где взять, куда положить

Куда класть: **EasyPanel → сервис бота → Environment** (локально — файл `.env`). Ключи не коммитить и не отправлять в чаты.

| Переменная | Обязательна | Где взять и какие права | Что без неё |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | да | @BotFather → `/mybots` → API Token | бот не запустится |
| `ANTHROPIC_API_KEY` | да | console.anthropic.com → API Keys; пополнить баланс | нет ответов |
| `WEBAPP_URL`, `DOMAIN` | для Mini App | https-адрес вашего бота (домен в EasyPanel) | нет Mini App, сайтов, Google, n8n-callback |
| `PAYMENT_PROVIDER_TOKEN` | для ₽ | @BotFather → Payments → ЮKassa (сначала тестовый) | нет оплаты в рублях |
| `STARS_MONTH`, `TOPUP_STARS` | нет | Stars включены у бота по умолчанию; ключей нет | нет подписки Stars |
| `YOOKASSA_RECEIPT`, `_VAT_CODE`, `_TAX_SYSTEM` | если касса 54-ФЗ | Параметры вашего магазина ЮKassa (уточните у бухгалтера) | платёж может отклоняться без чека |
| `GOOGLE_CLIENT_ID/SECRET` | нет | Google Cloud Console → Calendar API, Sheets API, Gmail API → OAuth client (Web); redirect URI `<WEBAPP_URL>/oauth/google/callback`; права: calendar.events, spreadsheets, gmail.compose | нет Календаря, Таблиц, черновиков |
| `DGIS_API_KEY` | нет | platform.2gis.ru → Places API | поиск мест без рейтингов (OSM) |
| `YANDEX_SEARCH_KEY`, `YANDEX_GEOCODER_KEY` | нет | developer.tech.yandex.ru — два разных ключа | пропускается Яндекс |
| `APIFY_TOKEN` | нет | apify.com → Settings → API (права на запуск Actors) | нет анализа Instagram |
| `REPLICATE_API_TOKEN` | нет | replicate.com → API tokens | нет правки фото |
| `OPENAI_API_KEY` | нет | platform.openai.com → только для Whisper | нет голосовых |
| `N8N_SECRET`, `N8N_WEBHOOKS` | нет | придумайте секрет (длинная случайная строка); адреса — Production URL ваших процессов | нет вызовов n8n |
| `ADMIN_ID` | нет | ваш Telegram id (например, через @userinfobot) | нет `/stats` |

Настройки не-ключей (цены, лимиты): `PRICE_*`, `CREDITS_*`, `TOPUP_*`, `FREE_MESSAGES`, `DISCOUNT_*`, `REFERRAL_BONUS` — см. `.env.example`.
Внутри Telegram: для групповых сводок отключить **Group Privacy** (@BotFather → Bot Settings → Group Privacy → Turn off).
Для Авито, hh.ru и т.п. ключи хранятся в **n8n Credentials**, а не в боте.
