from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from .utils import now_ts, utc_now_iso


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.migrate()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    @property
    def db(self) -> aiosqlite.Connection:
        if not self.conn:
            raise RuntimeError("数据库尚未连接")
        return self.conn

    async def migrate(self) -> None:
        """创建表结构，使用 IF NOT EXISTS 保证幂等。"""
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                settings TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                first_seen_at INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memberships (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at INTEGER,
                left_at INTEGER,
                warns INTEGER NOT NULL DEFAULT 0,
                message_count INTEGER NOT NULL DEFAULT 0,
                last_message_at INTEGER,
                silent_left INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS roles (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS word_filters (
                chat_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'keyword',
                PRIMARY KEY (chat_id, word, kind)
            );

            CREATE TABLE IF NOT EXISTS whitelist (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                note TEXT,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS blocked_operators (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                note TEXT,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS global_blacklist (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS moderation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                actor_id INTEGER,
                target_id INTEGER,
                action TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ledger_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                amount REAL NOT NULL,
                rate REAL,
                fee_rate REAL,
                final_amount REAL,
                note TEXT,
                archive_no INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS support_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                admin_message_id INTEGER NOT NULL,
                user_message_id INTEGER NOT NULL,
                admin_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                closed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS support_forward_bans (
                user_id INTEGER PRIMARY KEY,
                banned_until INTEGER NOT NULL,
                reason TEXT
            );

            CREATE TABLE IF NOT EXISTS scheduled_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                cron TEXT NOT NULL,
                text TEXT NOT NULL,
                parse_mode TEXT DEFAULT 'HTML',
                buttons TEXT,
                pin INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run TEXT,
                created_by INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS channel_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                text TEXT NOT NULL,
                buttons TEXT,
                scheduled_at TEXT,
                posted_at TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                created_by INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS captcha_store (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                answer INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS restricted_members (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                restricted_at INTEGER NOT NULL,
                reason TEXT,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS upload_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL DEFAULT 'photo',
                caption TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        await self.db.commit()

    async def ensure_chat(self, chat_id: int, title: str | None = None, defaults: dict[str, Any] | None = None) -> None:
        row = await self.fetchone("SELECT chat_id FROM chats WHERE chat_id=?", (chat_id,))
        if row:
            if title:
                await self.execute("UPDATE chats SET title=? WHERE chat_id=?", (title, chat_id))
            return
        await self.execute(
            "INSERT INTO chats(chat_id,title,settings,created_at) VALUES(?,?,?,?)",
            (chat_id, title, json.dumps(defaults or {}, ensure_ascii=False), utc_now_iso()),
        )

    async def upsert_user(self, user_id: int, username: str | None, full_name: str | None) -> None:
        """更新用户信息，首次出现时记录 first_seen_at。"""
        existing = await self.fetchone("SELECT first_seen_at FROM users WHERE user_id=?", (user_id,))
        if existing:
            await self.execute(
                "UPDATE users SET username=?, full_name=? WHERE user_id=?",
                (username, full_name, user_id),
            )
        else:
            await self.execute(
                "INSERT INTO users(user_id,username,full_name,first_seen_at,created_at) VALUES(?,?,?,?,?)",
                (user_id, username, full_name, now_ts(), utc_now_iso()),
            )

    async def get_first_seen(self, user_id: int) -> int | None:
        """获取用户首次被机器人看到的时间戳。"""
        row = await self.fetchone("SELECT first_seen_at FROM users WHERE user_id=?", (user_id,))
        if row:
            return row["first_seen_at"]
        return None

    async def member_joined(self, chat_id: int, user_id: int, silent_left: int = 0) -> None:
        await self.execute(
            """
            INSERT INTO memberships(chat_id,user_id,joined_at,left_at,silent_left)
            VALUES(?,?,?,?,?)
            ON CONFLICT(chat_id,user_id) DO UPDATE SET joined_at=excluded.joined_at,left_at=NULL,silent_left=excluded.silent_left
            """,
            (chat_id, user_id, now_ts(), None, silent_left),
        )

    async def member_left(self, chat_id: int, user_id: int) -> None:
        await self.execute("UPDATE memberships SET left_at=? WHERE chat_id=? AND user_id=?", (now_ts(), chat_id, user_id))

    async def incr_message(self, chat_id: int, user_id: int) -> None:
        await self.execute(
            """
            INSERT INTO memberships(chat_id,user_id,message_count,last_message_at)
            VALUES(?,?,1,?)
            ON CONFLICT(chat_id,user_id) DO UPDATE
            SET message_count=message_count+1,last_message_at=excluded.last_message_at
            """,
            (chat_id, user_id, now_ts()),
        )

    async def save_media(self, chat_id: int, file_id: str, file_type: str = "photo", caption: str | None = None) -> int:
        """保存上传的媒体文件用于欢迎消息等。"""
        await self.execute(
            "INSERT INTO upload_media(chat_id,file_id,file_type,caption,created_at) VALUES(?,?,?,?,?)",
            (chat_id, file_id, file_type, caption, utc_now_iso()),
        )
        row = await self.fetchone("SELECT last_insert_rowid() AS id")
        return row["id"] if row else 0

    async def get_media(self, media_id: int) -> dict[str, Any] | None:
        row = await self.fetchone("SELECT * FROM upload_media WHERE id=?", (media_id,))
        return dict(row) if row else None

    async def add_log(self, chat_id: int | None, actor_id: int | None, target_id: int | None, action: str, detail: str = "") -> None:
        await self.execute(
            "INSERT INTO moderation_logs(chat_id,actor_id,target_id,action,detail,created_at) VALUES(?,?,?,?,?,?)",
            (chat_id, actor_id, target_id, action, detail, utc_now_iso()),
        )

    async def get_settings(self, chat_id: int) -> dict[str, Any]:
        row = await self.fetchone("SELECT settings FROM chats WHERE chat_id=?", (chat_id,))
        if not row:
            return {}
        try:
            return json.loads(row["settings"] or "{}")
        except json.JSONDecodeError:
            return {}

    async def set_setting(self, chat_id: int, key: str, value: Any) -> None:
        settings = await self.get_settings(chat_id)
        settings[key] = value
        await self.execute("UPDATE chats SET settings=? WHERE chat_id=?", (json.dumps(settings, ensure_ascii=False), chat_id))

    async def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        async with self.db.execute(query, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        async with self.db.execute(query, params) as cursor:
            return await cursor.fetchall()

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        await self.db.execute(query, params)
        await self.db.commit()