from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "bot.db"

# Схема под будущий функционал: пользователи, каналы, RSS, учёт опубликованного.
INIT_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    chat_id INTEGER NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, chat_id)
);

CREATE TABLE IF NOT EXISTS rss_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    channel_id INTEGER REFERENCES channels (id) ON DELETE SET NULL,
    url TEXT NOT NULL,
    feed_title TEXT,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS posted_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES rss_sources (id) ON DELETE CASCADE,
    entry_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source_id, entry_key)
);

CREATE INDEX IF NOT EXISTS idx_channels_user ON channels (user_id);
CREATE INDEX IF NOT EXISTS idx_rss_user ON rss_sources (user_id);
CREATE INDEX IF NOT EXISTS idx_rss_channel ON rss_sources (channel_id);
CREATE INDEX IF NOT EXISTS idx_posted_source ON posted_entries (source_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rss_user_url ON rss_sources (user_id, url);
"""


async def _migrate(conn: aiosqlite.Connection) -> None:
    """Доп. поля/индексы для баз, созданных до обновления схемы."""
    cur = await conn.execute("PRAGMA table_info(rss_sources)")
    rows = await cur.fetchall()
    if not rows:
        return
    cols = {row[1] for row in rows}
    if "feed_title" not in cols:
        await conn.execute("ALTER TABLE rss_sources ADD COLUMN feed_title TEXT")
    cur2 = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_rss_user_url'"
    )
    if not await cur2.fetchone():
        await conn.execute(
            "CREATE UNIQUE INDEX idx_rss_user_url ON rss_sources (user_id, url)"
        )


async def init_db() -> None:
    """Создаёт каталог и таблицы, если их ещё нет."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(INIT_SQL)
        await _migrate(db)
        await db.commit()
    logger.info("SQLite готова: %s", DB_PATH)


async def connect() -> aiosqlite.Connection:
    """Новое соединение для запросов из хендлеров (не забывайте close)."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(DB_PATH)
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA journal_mode = WAL")
    return conn


async def ensure_user(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )
        await db.commit()


async def add_rss_source(
    user_id: int,
    *,
    url: str,
    feed_title: str | None,
    channel_id: int | None = None,
) -> int:
    """Добавляет RSS-источник. Возвращает id. Бросает aiosqlite.IntegrityError при дубликате URL."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            INSERT INTO rss_sources (user_id, channel_id, url, feed_title)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, channel_id, url, feed_title),
        )
        await db.commit()
        return int(cur.lastrowid)


async def list_rss_sources(user_id: int) -> list[dict[str, object]]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            SELECT id, url, feed_title, enabled, channel_id, created_at
            FROM rss_sources
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
    return [
        {
            "id": r[0],
            "url": r[1],
            "feed_title": r[2],
            "enabled": bool(r[3]),
            "channel_id": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


async def delete_rss_source(user_id: int, source_id: int) -> bool:
    """Удаляет источник, если он принадлежит user_id. True, если строка удалена."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "DELETE FROM rss_sources WHERE id = ? AND user_id = ?",
            (source_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0
