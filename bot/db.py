import time

import aiosqlite

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT, used INTEGER DEFAULT 0,
  paid_until INTEGER DEFAULT 0, created INTEGER,
  bonus INTEGER DEFAULT 0, credits INTEGER DEFAULT 0, ref_by INTEGER, sub_charge_id TEXT, model TEXT DEFAULT 'std'
);
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, fact TEXT, UNIQUE(user_id, fact)
);
CREATE TABLE IF NOT EXISTS chat_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, author TEXT, text TEXT, ts INTEGER
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT
);
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan TEXT, amount INTEGER, ts INTEGER
);
CREATE TABLE IF NOT EXISTS google_tokens(
  user_id INTEGER PRIMARY KEY, refresh_token TEXT
);
CREATE TABLE IF NOT EXISTS reminders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, at INTEGER, text TEXT, sent INTEGER DEFAULT 0
);
"""


async def init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        for col, ddl in (("bonus", "INTEGER DEFAULT 0"), ("credits", "INTEGER DEFAULT 0"), ("ref_by", "INTEGER"),
                         ("sub_charge_id", "TEXT"), ("model", "TEXT DEFAULT 'std'")):
            try:  # миграция для баз, созданных раньше
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
            except aiosqlite.OperationalError:
                pass
        await db.commit()


async def _one(sql, args=()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, args) as cur:
            return await cur.fetchone()


async def _exec(sql, args=()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(sql, args)
        await db.commit()


async def get_user(uid, name=""):
    await _exec("INSERT OR IGNORE INTO users(id,name,created) VALUES(?,?,?)", (uid, name, int(time.time())))
    return await _one("SELECT * FROM users WHERE id=?", (uid,))


async def is_paid(uid) -> bool:
    row = await _one("SELECT paid_until FROM users WHERE id=?", (uid,))
    return bool(row and row["paid_until"] > time.time())


async def bump_used(uid):
    await _exec("UPDATE users SET used=used+1 WHERE id=?", (uid,))


async def record_payment(uid, plan, amount):
    await _exec("INSERT INTO payments(user_id,plan,amount,ts) VALUES(?,?,?,?)", (uid, plan, amount, int(time.time())))


async def add_credits(uid, n):
    await _exec("UPDATE users SET credits=credits+? WHERE id=?", (n, uid))


async def spend(uid, n=1):
    """Списывает запросы подписчика, не уходя ниже нуля."""
    await _exec("UPDATE users SET credits=MAX(credits-?,0) WHERE id=?", (n, uid))


async def add_subscription(uid, plan, days, amount):
    now = int(time.time())
    row = await _one("SELECT paid_until FROM users WHERE id=?", (uid,))
    start = max(now, row["paid_until"]) if row else now
    await _exec("UPDATE users SET paid_until=? WHERE id=?", (start + days * 86400, uid))
    from .config import CREDITS_MONTH, CREDITS_WEEK
    await add_credits(uid, CREDITS_MONTH if plan == "month" else CREDITS_WEEK)
    await _exec("INSERT INTO payments(user_id,plan,amount,ts) VALUES(?,?,?,?)", (uid, plan, amount, now))


async def history(uid, limit=12):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)
        ) as cur:
            rows = await cur.fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


async def save(uid, role, content):
    await _exec("INSERT INTO messages(user_id,role,content) VALUES(?,?,?)", (uid, role, content))


async def add_reminder(uid, at, text):
    await _exec("INSERT INTO reminders(user_id,at,text) VALUES(?,?,?)", (uid, at, text))


async def due_reminders():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id,user_id,text FROM reminders WHERE sent=0 AND at<=?", (int(time.time()),)
        ) as cur:
            rows = await cur.fetchall()
        for rid, *_ in rows:
            await db.execute("UPDATE reminders SET sent=1 WHERE id=?", (rid,))
        await db.commit()
    return rows


def free_left(user) -> int:
    from .config import FREE_MESSAGES
    return max(FREE_MESSAGES + (user["bonus"] or 0) - user["used"], 0)


async def stats():
    users = await _one("SELECT COUNT(*) c FROM users")
    paid = await _one("SELECT COUNT(*) c FROM users WHERE paid_until>?", (time.time(),))
    rev = await _one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE plan!='stars'")
    stars = await _one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE plan='stars'")
    return users["c"], paid["c"], rev["s"], stars["s"]


async def set_google_token(uid, token):
    await _exec("INSERT OR REPLACE INTO google_tokens(user_id,refresh_token) VALUES(?,?)", (uid, token))


async def get_google_token(uid):
    row = await _one("SELECT refresh_token FROM google_tokens WHERE user_id=?", (uid,))
    return row["refresh_token"] if row else None


async def is_new(uid) -> bool:
    return await _one("SELECT 1 FROM users WHERE id=?", (uid,)) is None


async def add_bonus(uid, n):
    await _exec("UPDATE users SET bonus=bonus+? WHERE id=?", (n, uid))


async def set_ref(uid, ref):
    await _exec("UPDATE users SET ref_by=? WHERE id=? AND ref_by IS NULL", (ref, uid))


async def set_model(uid, key):
    await _exec("UPDATE users SET model=? WHERE id=?", (key, uid))


async def set_sub_charge(uid, charge_id):
    await _exec("UPDATE users SET sub_charge_id=? WHERE id=?", (charge_id, uid))


async def set_paid_until(uid, ts):
    await _exec("UPDATE users SET paid_until=? WHERE id=?", (ts, uid))


async def add_fact(uid, fact):
    await _exec("INSERT OR IGNORE INTO facts(user_id,fact) VALUES(?,?)", (uid, fact[:300]))


async def facts(uid, limit=30):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT fact FROM facts WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)) as cur:
            return [r[0] for r in await cur.fetchall()]


async def clear_facts(uid):
    await _exec("DELETE FROM facts WHERE user_id=?", (uid,))


async def log_chat(chat_id, author, text):
    await _exec("INSERT INTO chat_log(chat_id,author,text,ts) VALUES(?,?,?,?)", (chat_id, author, text[:1000], int(time.time())))


async def chat_since(chat_id, since_ts, limit=400):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT author,text,ts FROM chat_log WHERE chat_id=? AND ts>=? ORDER BY id DESC LIMIT ?",
            (chat_id, since_ts, limit),
        ) as cur:
            rows = await cur.fetchall()
    return list(reversed(rows))


async def purge_chat_log(days=7):
    await _exec("DELETE FROM chat_log WHERE ts<?", (int(time.time()) - days * 86400,))


async def exists(uid) -> bool:
    return await _one("SELECT 1 FROM users WHERE id=?", (uid,)) is not None
