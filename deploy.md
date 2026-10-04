# Развёртывание на сервере

Нужно: сервер с Docker (Ubuntu 22.04+), домен с A-записью на IP сервера, открытые порты 80 и 443.

```bash
git clone -b claude/earnings-bot-tj8qoc <репозиторий> bot && cd bot
cp .env.example .env
nano .env        # заполнить: токены, WEBAPP_URL=https://ваш-домен, DOMAIN=ваш-домен (см. ниже)
docker compose up -d --build
docker compose logs -f bot     # смотреть логи, выход Ctrl+C
```

В `.env` добавьте строку `DOMAIN=bot.example.com` (её читает Caddy) и `WEBAPP_URL=https://bot.example.com`.
Caddy сам получит и будет продлевать https-сертификат.

Проверка: откройте `https://ваш-домен/` в браузере (страница Mini App покажет «Открой приложение из Telegram») — значит
https и прокси работают. Затем в Telegram: кнопка «Меню» рядом с полем ввода открывает Mini App.

Обновление: `git pull && docker compose up -d --build`. Данные (база, сайты) лежат в томе `botdata` и переживают пересборку.
Резервная копия базы: `docker compose cp bot:/data/bot.db ./bot-backup.db`.

Без Docker: `pip install -r requirements.txt`, затем `python -m bot.main` под systemd/supervisor; https — своим nginx/Caddy
на порт `WEB_PORT`.

Безопасность: `.env` не коммитить; на сервере включить firewall (открыть только 22, 80, 443); порт 8080 наружу не открывать.
