from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import aiosqlite

from text_utils import normalize_article_link

logger = logging.getLogger(__name__)

DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "bot.db"

# Схема: пользователи, каналы, источники новостей (RSS-ленты), учёт опубликованного.
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

CREATE TABLE IF NOT EXISTS worker_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    source_id INTEGER,
    level TEXT NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_channels_user ON channels (user_id);
CREATE INDEX IF NOT EXISTS idx_rss_user ON rss_sources (user_id);
CREATE INDEX IF NOT EXISTS idx_rss_channel ON rss_sources (channel_id);
CREATE INDEX IF NOT EXISTS idx_posted_source ON posted_entries (source_id);
CREATE INDEX IF NOT EXISTS idx_worker_events_user_created ON worker_events (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS rss_monitor_state (
    source_id INTEGER PRIMARY KEY REFERENCES rss_sources (id) ON DELETE CASCADE,
    last_top_entry_key TEXT,
    last_check_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_error TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rss_user_url ON rss_sources (user_id, url);

CREATE TABLE IF NOT EXISTS user_posting_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    posting_enabled INTEGER NOT NULL DEFAULT 0 CHECK (posting_enabled IN (0, 1)),
    posting_mode TEXT NOT NULL DEFAULT 'manual' CHECK (posting_mode IN ('manual', 'auto')),
    max_posts_per_day INTEGER NOT NULL DEFAULT 20,
    quiet_start_hour INTEGER,
    quiet_end_hour INTEGER,
    send_images INTEGER NOT NULL DEFAULT 1 CHECK (send_images IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_published_links (
    user_id INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    link_norm TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, link_norm)
);

CREATE TABLE IF NOT EXISTS user_daily_posts (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE INDEX IF NOT EXISTS idx_user_daily_day ON user_daily_posts (day);

CREATE TABLE IF NOT EXISTS news_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES rss_sources (id) ON DELETE CASCADE,
    entry_key TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    body_text TEXT NOT NULL DEFAULT '',
    image_url TEXT,
    published_at TEXT,
    discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, source_id, entry_key)
);

CREATE INDEX IF NOT EXISTS idx_news_inbox_user_sort ON news_inbox (
    user_id,
    published_at DESC,
    discovered_at DESC
);
"""


async def _migrate(conn: aiosqlite.Connection) -> None:
    """Доп. поля/индексы для баз, созданных до обновления схемы."""
    cur = await conn.execute("PRAGMA table_info(rss_sources)")
    rows = await cur.fetchall()
    if rows:
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

    cur_ups = await conn.execute("PRAGMA table_info(user_posting_settings)")
    ups_rows = await cur_ups.fetchall()
    ups_cols = {row[1] for row in ups_rows} if ups_rows else set()
    if ups_cols and "posting_mode" not in ups_cols:
        await conn.execute(
            "ALTER TABLE user_posting_settings ADD COLUMN posting_mode TEXT NOT NULL DEFAULT 'auto'"
        )
        await conn.execute(
            "UPDATE user_posting_settings SET posting_mode = 'manual' WHERE posting_enabled = 0"
        )
        await conn.execute(
            "UPDATE user_posting_settings SET posting_mode = 'auto' WHERE posting_enabled = 1"
        )

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_published_links (
            user_id INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
            link_norm TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, link_norm)
        )
        """
    )

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rss_monitor_state (
            source_id INTEGER PRIMARY KEY REFERENCES rss_sources (id) ON DELETE CASCADE,
            last_top_entry_key TEXT,
            last_check_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_error TEXT
        )
        """
    )

    cur_uv = await conn.execute("PRAGMA user_version")
    uv_row = await cur_uv.fetchone()
    user_ver = int(uv_row[0]) if uv_row else 0
    if user_ver < 2:
        await conn.execute(
            """
            UPDATE user_posting_settings
            SET posting_mode = 'manual', posting_enabled = 0
            """
        )
        await conn.execute("PRAGMA user_version = 2")

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_inbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES rss_sources (id) ON DELETE CASCADE,
            entry_key TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '',
            body_text TEXT NOT NULL DEFAULT '',
            image_url TEXT,
            published_at TEXT,
            discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (user_id, source_id, entry_key)
        )
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_news_inbox_user_sort ON news_inbox (
            user_id,
            published_at DESC,
            discovered_at DESC
        )
        """
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
    """Добавляет источник новостей (URL ленты). Возвращает id. Бросает aiosqlite.IntegrityError при дубликате URL."""
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
            SELECT rss.id, rss.url, rss.feed_title, rss.enabled, rss.channel_id, rss.created_at,
                   ch.title AS channel_title
            FROM rss_sources rss
            LEFT JOIN channels ch ON ch.id = rss.channel_id
            WHERE rss.user_id = ?
            ORDER BY rss.id DESC
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
            "channel_title": r[6],
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


async def add_channel(user_id: int, *, chat_id: int, title: str | None = None) -> int:
    """
    Добавляет канал пользователю (или обновляет title у существующего).
    Возвращает id записи channels.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """
            INSERT INTO channels (user_id, chat_id, title)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, chat_id) DO UPDATE SET
                title = excluded.title
            """,
            (user_id, chat_id, title),
        )
        cur = await db.execute(
            "SELECT id FROM channels WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        )
        row = await cur.fetchone()
        await db.commit()
        return int(row[0])


async def list_channels(user_id: int) -> list[dict[str, object]]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            SELECT id, chat_id, title, created_at
            FROM channels
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
    return [
        {
            "id": r[0],
            "chat_id": r[1],
            "title": r[2],
            "created_at": r[3],
        }
        for r in rows
    ]


async def delete_channel(user_id: int, channel_id: int) -> bool:
    """Удаляет канал по внутреннему id, если он принадлежит user_id."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "DELETE FROM channels WHERE id = ? AND user_id = ?",
            (channel_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def set_rss_source_channel(
    user_id: int, *, rss_id: int, channel_id: int
) -> bool:
    """
    Привязывает источник к каналу (оба id — внутренние из списков #).
    Возвращает True, если строка обновлена.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            UPDATE rss_sources
            SET channel_id = ?
            WHERE id = ? AND user_id = ?
              AND EXISTS (
                SELECT 1 FROM channels c
                WHERE c.id = ? AND c.user_id = ?
              )
            """,
            (channel_id, rss_id, user_id, channel_id, user_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def is_entry_posted(source_id: int, entry_key: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "SELECT 1 FROM posted_entries WHERE source_id = ? AND entry_key = ?",
            (source_id, entry_key),
        )
        row = await cur.fetchone()
    return row is not None


async def mark_entry_posted(source_id: int, entry_key: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "INSERT OR IGNORE INTO posted_entries (source_id, entry_key) VALUES (?, ?)",
            (source_id, entry_key),
        )
        await db.commit()


async def add_worker_event(
    *,
    user_id: int | None,
    source_id: int | None,
    level: str,
    kind: str,
    message: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """
            INSERT INTO worker_events (user_id, source_id, level, kind, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, source_id, level, kind, message[:1000]),
        )
        await db.commit()


async def list_feeding_jobs() -> list[dict[str, object]]:
    """
    Фоновая публикация из RSS в канал отключена: канал выбирается вручную при отправке черновика.
    Воркер остаётся в цикле, но задач без ручного сценария нет.
    """
    return []


async def list_rss_sources_for_monitor() -> list[dict[str, object]]:
    """Все включённые источники — для фонового мониторинга лент (в т.ч. без канала и в ручном режиме)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "SELECT id, user_id, url, feed_title FROM rss_sources WHERE enabled = 1",
        )
        rows = await cur.fetchall()
    return [
        {
            "source_id": r[0],
            "user_id": r[1],
            "rss_url": r[2],
            "feed_title": r[3],
        }
        for r in rows
    ]


async def get_rss_monitor_state(source_id: int) -> dict[str, object] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            SELECT last_top_entry_key, last_check_at, last_error
            FROM rss_monitor_state
            WHERE source_id = ?
            """,
            (source_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "last_top_entry_key": row[0],
        "last_check_at": row[1],
        "last_error": row[2],
    }


async def upsert_rss_monitor_state(
    source_id: int,
    *,
    last_top_entry_key: str | None,
    last_error: str | None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """
            INSERT INTO rss_monitor_state (source_id, last_top_entry_key, last_check_at, last_error)
            VALUES (?, ?, datetime('now'), ?)
            ON CONFLICT(source_id) DO UPDATE SET
                last_top_entry_key = excluded.last_top_entry_key,
                last_check_at = datetime('now'),
                last_error = excluded.last_error
            """,
            (source_id, last_top_entry_key, last_error),
        )
        await db.commit()


async def get_feed_job_for_user(user_id: int, source_id: int) -> dict[str, object] | None:
    """Один источник пользователя с привязанным каналом (для авто-поста и совместимости)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            SELECT rss_sources.id, rss_sources.user_id, rss_sources.url, channels.chat_id
            FROM rss_sources
            INNER JOIN channels ON channels.id = rss_sources.channel_id
            WHERE rss_sources.enabled = 1
              AND rss_sources.user_id = ?
              AND rss_sources.id = ?
            """,
            (user_id, source_id),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "source_id": row[0],
        "user_id": row[1],
        "rss_url": row[2],
        "chat_id": row[3],
    }


async def get_manual_publish_job(
    user_id: int, source_id: int, channel_row_id: int
) -> dict[str, object] | None:
    """
    Ручная публикация: включённый источник + любой канал пользователя (внутренний id из таблицы channels).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            SELECT rss.id, rss.user_id, rss.url, ch.chat_id
            FROM rss_sources rss
            INNER JOIN channels ch
              ON ch.id = ? AND ch.user_id = rss.user_id
            WHERE rss.user_id = ?
              AND rss.id = ?
              AND rss.enabled = 1
            """,
            (channel_row_id, user_id, source_id),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "source_id": row[0],
        "user_id": row[1],
        "rss_url": row[2],
        "chat_id": row[3],
    }


async def get_user_stats(user_id: int) -> dict[str, int]:
    """Сводка по пользователю для раздела «Статус»."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "SELECT COUNT(*) FROM channels WHERE user_id = ?", (user_id,)
        )
        n_ch = int((await cur.fetchone())[0])
        cur = await db.execute(
            "SELECT COUNT(*) FROM rss_sources WHERE user_id = ?", (user_id,)
        )
        n_src = int((await cur.fetchone())[0])
        cur = await db.execute(
            """
            SELECT COUNT(*) FROM posted_entries pe
            INNER JOIN rss_sources rs ON rs.id = pe.source_id
            WHERE rs.user_id = ?
            """,
            (user_id,),
        )
        n_posted = int((await cur.fetchone())[0])
    return {
        "channels": n_ch,
        "sources": n_src,
        "posted_entries": n_posted,
    }


async def ensure_posting_settings(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """
            INSERT OR IGNORE INTO user_posting_settings (user_id, posting_enabled, posting_mode)
            VALUES (?, 0, 'manual')
            """,
            (user_id,),
        )
        await db.commit()


async def get_posting_settings(user_id: int) -> dict[str, object]:
    await ensure_posting_settings(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            SELECT posting_enabled, posting_mode, max_posts_per_day, quiet_start_hour, quiet_end_hour, send_images
            FROM user_posting_settings
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        raise RuntimeError("user_posting_settings row missing")
    enabled = bool(row[0])
    raw_mode = row[1]
    if isinstance(raw_mode, str) and raw_mode in ("manual", "auto"):
        mode = raw_mode
    else:
        mode = "auto" if enabled else "manual"
    return {
        "posting_enabled": enabled,
        "posting_mode": mode,
        "max_posts_per_day": int(row[2]),
        "quiet_start_hour": row[3],
        "quiet_end_hour": row[4],
        "send_images": bool(row[5]),
    }


async def update_posting_settings(user_id: int, **kwargs: object) -> None:
    allowed = {
        "posting_enabled",
        "posting_mode",
        "max_posts_per_day",
        "quiet_start_hour",
        "quiet_end_hour",
        "send_images",
    }
    if not kwargs:
        return
    bad = set(kwargs) - allowed
    if bad:
        raise ValueError(f"unknown keys: {bad}")
    if "posting_mode" in kwargs:
        pm = str(kwargs["posting_mode"])
        if pm not in ("manual", "auto"):
            raise ValueError("posting_mode must be 'manual' or 'auto'")
        kwargs["posting_enabled"] = 1 if pm == "auto" else 0
    elif "posting_enabled" in kwargs and "posting_mode" not in kwargs:
        kwargs["posting_mode"] = "auto" if kwargs["posting_enabled"] else "manual"
    await ensure_posting_settings(user_id)
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values())
    vals.append(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            f"""
            UPDATE user_posting_settings
            SET {cols}, updated_at = datetime('now')
            WHERE user_id = ?
            """,
            vals,
        )
        await db.commit()


async def is_duplicate_article_for_user(user_id: int, link: str) -> bool:
    """Проверка по нормализованной ссылке — одна и та же новость с разных источников."""
    norm = normalize_article_link(link)
    if not norm:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "SELECT 1 FROM user_published_links WHERE user_id = ? AND link_norm = ?",
            (user_id, norm),
        )
        return (await cur.fetchone()) is not None


async def remember_published_article_link(user_id: int, link: str) -> None:
    """Запоминаем ссылку после успешной публикации в канал."""
    norm = normalize_article_link(link)
    if not norm:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """
            INSERT OR IGNORE INTO user_published_links (user_id, link_norm)
            VALUES (?, ?)
            """,
            (user_id, norm),
        )
        await db.commit()


async def get_daily_post_count(user_id: int) -> int:
    day = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "SELECT count FROM user_daily_posts WHERE user_id = ? AND day = ?",
            (user_id, day),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def increment_daily_post(user_id: int) -> int:
    day = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """
            INSERT INTO user_daily_posts (user_id, day, count) VALUES (?, ?, 1)
            ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1
            """,
            (user_id, day),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT count FROM user_daily_posts WHERE user_id = ? AND day = ?",
            (user_id, day),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def get_last_event_for_user(user_id: int) -> dict[str, object] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            SELECT level, kind, message, created_at
            FROM worker_events
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "level": row[0],
        "kind": row[1],
        "message": row[2],
        "created_at": row[3],
    }


async def news_inbox_try_add(
    user_id: int,
    source_id: int,
    *,
    entry_key: str,
    title: str,
    link: str,
    body_text: str,
    image_url: str | None,
    published_at: str | None,
) -> int | None:
    """
    Добавляет материал в очередь «новые новости». При дубликате (тот же entry_key у источника)
    возвращает None.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            """
            INSERT INTO news_inbox (
                user_id, source_id, entry_key, title, link, body_text, image_url, published_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, source_id, entry_key) DO NOTHING
            RETURNING id
            """,
            (
                user_id,
                source_id,
                entry_key[:500],
                title[:2000],
                link[:2000],
                body_text[:16000],
                image_url,
                published_at,
            ),
        )
        row = await cur.fetchone()
        await db.commit()
    return int(row[0]) if row else None


async def news_inbox_next_unposted(user_id: int, source_id: int) -> dict[str, object] | None:
    """Самая ранняя запись в очереди для источника, ещё не помеченная как опубликованная."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT
                ni.id,
                ni.source_id,
                ni.title,
                ni.link,
                ni.body_text,
                ni.image_url,
                ni.published_at,
                ni.discovered_at,
                ni.entry_key,
                rs.feed_title AS source_feed_title,
                rs.enabled AS source_enabled
            FROM news_inbox ni
            INNER JOIN rss_sources rs
              ON rs.id = ni.source_id AND rs.user_id = ni.user_id
            WHERE ni.user_id = ? AND ni.source_id = ?
              AND NOT EXISTS (
                SELECT 1 FROM posted_entries pe
                WHERE pe.source_id = ni.source_id AND pe.entry_key = ni.entry_key
              )
            ORDER BY ni.discovered_at ASC, ni.id ASC
            LIMIT 1
            """,
            (user_id, source_id),
        )
        row = await cur.fetchone()
    return dict(row) if row else None


async def news_inbox_delete_by_entry_key(user_id: int, source_id: int, entry_key: str) -> bool:
    ek = (entry_key or "").strip()[:500]
    if not ek:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "DELETE FROM news_inbox WHERE user_id = ? AND source_id = ? AND entry_key = ?",
            (user_id, source_id, ek),
        )
        await db.commit()
        return cur.rowcount > 0


async def news_inbox_list(user_id: int, *, limit: int = 60) -> list[dict[str, object]]:
    """
    Все новости в порядке: старые выше, новые ниже (дата из ленты, затем время в очереди).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT
                ni.id,
                ni.source_id,
                ni.title,
                ni.link,
                ni.body_text,
                ni.image_url,
                ni.published_at,
                ni.discovered_at,
                ni.entry_key,
                rs.feed_title AS source_feed_title,
                rs.url AS source_url
            FROM news_inbox ni
            INNER JOIN rss_sources rs
              ON rs.id = ni.source_id AND rs.user_id = ni.user_id
            WHERE ni.user_id = ?
            ORDER BY
                CASE WHEN ni.published_at IS NULL THEN 1 ELSE 0 END,
                ni.published_at ASC,
                ni.discovered_at ASC,
                ni.id ASC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def news_inbox_newest(user_id: int) -> dict[str, object] | None:
    """Самая свежая запись в очереди (нижняя в списке при сортировке «старые → новые»)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT
                ni.id,
                ni.source_id,
                ni.title,
                ni.link,
                ni.body_text,
                ni.image_url,
                ni.published_at,
                ni.discovered_at,
                ni.entry_key,
                rs.feed_title AS source_feed_title,
                rs.enabled AS source_enabled
            FROM news_inbox ni
            INNER JOIN rss_sources rs
              ON rs.id = ni.source_id AND rs.user_id = ni.user_id
            WHERE ni.user_id = ?
            ORDER BY
                CASE WHEN ni.published_at IS NULL THEN 1 ELSE 0 END,
                ni.published_at DESC,
                ni.discovered_at DESC,
                ni.id DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()
    return dict(row) if row else None


async def news_inbox_ordered_ids(user_id: int, *, limit: int = 60) -> list[int]:
    rows = await news_inbox_list(user_id, limit=limit)
    return [int(r["id"]) for r in rows]


async def news_inbox_get(user_id: int, inbox_id: int) -> dict[str, object] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT
                ni.id,
                ni.source_id,
                ni.title,
                ni.link,
                ni.body_text,
                ni.image_url,
                ni.published_at,
                ni.discovered_at,
                ni.entry_key,
                rs.feed_title AS source_feed_title,
                rs.enabled AS source_enabled
            FROM news_inbox ni
            INNER JOIN rss_sources rs
              ON rs.id = ni.source_id AND rs.user_id = ni.user_id
            WHERE ni.user_id = ? AND ni.id = ?
            """,
            (user_id, inbox_id),
        )
        row = await cur.fetchone()
    return dict(row) if row else None


async def news_inbox_delete(user_id: int, inbox_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "DELETE FROM news_inbox WHERE user_id = ? AND id = ?",
            (user_id, inbox_id),
        )
        await db.commit()
        return cur.rowcount > 0
