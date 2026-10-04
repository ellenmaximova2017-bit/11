import time

import aiosqlite

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT, used INTEGER DEFAULT 0,
  paid_until INTEGER DEFAULT 0, created INTEGER
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT
);
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, plan TEXT, amount INTEGER, ts INTEGER
);
CREATE TABLE IF NOT EXISTS reminders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, at INTEGER, text TEXT, sent INTEGER DEFAULT 0
);
"""


async def init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
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


async def add_subscription(uid, plan, days, amount):
    now = int(time.time())
    row = await _one("SELECT paid_until FROM users WHERE id=?", (uid,))
    start = max(now, row["paid_until"]) if row else now
    await _exec("UPDATE users SET paid_until=? WHERE id=?", (start + days * 86400, uid))
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


async def stats():
    users = await _one("SELECT COUNT(*) c FROM users")
    paid = await _one("SELECT COUNT(*) c FROM users WHERE paid_until>?", (time.time(),))
    rev = await _one("SELECT COALESCE(SUM(amount),0) s FROM payments")
    return users["c"], paid["c"], rev["s"]
