from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
    from aiogram import Bot

from .db import Database
from .utils import now_ts, utc_now_iso, user_label

logger = logging.getLogger(__name__)


class SupportService:
    """私聊客服中转系统：用户受限时通过机器人与客服实时聊天。"""

    def __init__(self, db: Database, support_admins: set[int]) -> None:
        self.db = db
        self.support_admins = support_admins

    async def forward_user_message(self, message: "Message", bot: Bot) -> bool:
        """处理用户私聊消息，转发给客服管理员。"""
        from aiogram.types import Message

        if not message.from_user or not message.chat or message.chat.type.value != "private":
            return False

        user_id = message.from_user.id

        # 检查是否被禁止使用客服
        ban = await self.db.fetchone("SELECT banned_until, reason FROM support_forward_bans WHERE user_id=?", (user_id,))
        if ban:
            if now_ts() < ban["banned_until"]:
                await message.answer(f"你已被禁止使用客服系统。原因：{ban['reason'] or '无'}\n\n如需解封请联系其他管理员。")
                return True
            else:
                await self.db.execute("DELETE FROM support_forward_bans WHERE user_id=?", (user_id,))

        # 管理员回复用户消息
        if message.reply_to_message and user_id in self.support_admins:
            return await self._handle_admin_reply(message, bot)

        # 命令由命令处理器处理
        text = (message.text or "").strip()
        if text.startswith("/"):
            return False

        # 转发给所有客服管理员
        forward_count = 0
        user_info = user_label(message.from_user)

        # 消息类型标签
        type_tag = ""
        if message.photo:
            type_tag = " [📷 图片]"
        elif message.document:
            type_tag = " [📄 文件]"
        elif message.sticker:
            type_tag = " [🎨 贴纸]"
        elif message.voice:
            type_tag = " [🎵 语音]"
        elif message.video:
            type_tag = " [🎬 视频]"
        elif message.animation:
            type_tag = " [🎞 GIF]"
        elif message.video_note:
            type_tag = " [🎥 视频消息]"
        elif message.audio:
            type_tag = " [🎶 音频]"

        for admin_id in self.support_admins:
            try:
                fwd_text = (
                    f"📩 用户消息{type_tag}\n"
                    f"👤 用户：{user_info}\n"
                    f"🆔 ID：{user_id}\n"
                    f"⏰ 时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
                    f"{text}"
                )

                sent = await bot.send_message(
                    admin_id,
                    fwd_text,
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(text="💬 回复", callback_data=f"support_reply_{user_id}"),
                                InlineKeyboardButton(text="🚫 封禁客服", callback_data=f"support_ban_{user_id}"),
                                InlineKeyboardButton(text="🔒 结束会话", callback_data=f"support_close_{user_id}"),
                            ]
                        ]
                    ),
                )
                await self.db.execute(
                    "INSERT INTO support_threads(user_id,admin_message_id,user_message_id,admin_id,status,created_at) VALUES(?,?,?,?,'open',?)",
                    (user_id, sent.message_id, message.message_id, admin_id, utc_now_iso()),
                )
                forward_count += 1
            except Exception as e:
                logger.warning("转发给管理员 %s 失败: %s", admin_id, e)

        if forward_count > 0:
            await message.answer("✅ 你的消息已转给客服，请稍候回复。\n\n如需继续发送消息，直接输入即可。")
            return True
        else:
            await message.answer("❌ 客服系统暂时无法使用，请稍后再试。")
            return True

    async def _handle_admin_reply(self, message: "Message", bot: Bot) -> bool:
        """管理员回复转交消息。"""
        from aiogram.types import Message

        admin_id = message.from_user.id
        reply_msg_id = message.reply_to_message.message_id

        thread = await self.db.fetchone(
            "SELECT user_id FROM support_threads WHERE admin_message_id=? AND admin_id=? AND status='open'",
            (reply_msg_id, admin_id),
        )

        if not thread:
            await message.reply("未找到对应的用户会话（可能已关闭）。发送 /support 查看客服帮助。")
            return True

        user_id = thread["user_id"]
        reply_text = (message.text or "").strip()
        if not reply_text:
            await message.reply("请输入回复内容。")
            return True

        try:
            await bot.send_message(
                user_id,
                f"💬 客服回复：\n\n{reply_text}\n\n---\n如需继续咨询请直接回复。",
            )
            await message.reply(f"✅ 已回复用户 {user_id}")
        except Exception as e:
            await message.reply(f"❌ 发送失败：{e}")

        return True

    async def ban_user_from_support(self, user_id: int, reason: str = "", duration_hours: int = 24) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO support_forward_bans(user_id,banned_until,reason) VALUES(?,?,?)",
            (user_id, now_ts() + duration_hours * 3600, reason),
        )

    async def close_thread(self, user_id: int) -> int:
        await self.db.execute(
            "UPDATE support_threads SET status='closed',closed_at=? WHERE user_id=? AND status='open'",
            (utc_now_iso(), user_id),
        )
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS c FROM support_threads WHERE user_id=? AND status='closed'", (user_id,)
        )
        return row["c"] if row else 0


class ChannelManager:
    """频道管理：按钮发帖、定时发帖、置顶。"""

    def __init__(self, db: Database, bot: Bot) -> None:
        self.db = db
        self.bot = bot

    async def create_channel_post(
        self,
        channel_id: int,
        text: str,
        buttons: list[dict[str, str]] | None = None,
        scheduled_at: str | None = None,
        created_by: int = 0,
        pin: bool = False,
    ) -> int:
        buttons_json = json.dumps(buttons, ensure_ascii=False) if buttons else None
        await self.db.execute(
            "INSERT INTO channel_posts(channel_id,text,buttons,scheduled_at,status,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
            (channel_id, text, buttons_json, scheduled_at, "draft" if scheduled_at else "ready", created_by, utc_now_iso()),
        )
        row = await self.db.fetchone("SELECT last_insert_rowid() AS id")
        return row["id"] if row else 0

    async def publish_post(self, post_id: int) -> bool:
        post = await self.db.fetchone("SELECT * FROM channel_posts WHERE id=? AND status IN ('draft','ready')", (post_id,))
        if not post:
            return False
        try:
            keyboard = None
            if post["buttons"]:
                buttons_data = json.loads(post["buttons"])
                if buttons_data:
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text=b["text"], url=b["url"])] for b in buttons_data
                        ]
                    )
            sent = await self.bot.send_message(
                post["channel_id"],
                post["text"],
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            if post.get("pin"):
                try:
                    await self.bot.pin_chat_message(post["channel_id"], sent.message_id)
                except Exception:
                    pass
            await self.db.execute(
                "UPDATE channel_posts SET status='posted',message_id=?,posted_at=? WHERE id=?",
                (sent.message_id, utc_now_iso(), post_id),
            )
            return True
        except Exception as e:
            logger.warning("发布帖子 %d 失败: %s", post_id, e)
            return False

    async def list_scheduled(self, chat_id: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT id,cron,text,pin,enabled FROM scheduled_messages WHERE chat_id=? ORDER BY id",
            (chat_id,),
        )
        return [dict(r) for r in rows]

    async def delete_scheduled(self, schedule_id: int) -> bool:
        await self.db.execute("DELETE FROM scheduled_messages WHERE id=?", (schedule_id,))
        return True

    async def auto_publish_scheduled_posts(self) -> int:
        now = utc_now_iso()
        rows = await self.db.fetchall(
            "SELECT id FROM channel_posts WHERE status='draft' AND scheduled_at IS NOT NULL AND scheduled_at<=?",
            (now,),
        )
        count = 0
        for r in rows:
            if await self.publish_post(r["id"]):
                count += 1
        return count


class ScheduledMessageExecutor:
    """定时消息执行器：根据 cron 表达式发送定时公告。"""

    def __init__(self, db: Database, bot: Bot) -> None:
        self.db = db
        self.bot = bot

    async def execute_due(self) -> int:
        """执行所有到期的定时消息，返回发送条数。"""
        from apscheduler.triggers.cron import CronTrigger

        rows = await self.db.fetchall(
            "SELECT id, chat_id, cron, text, buttons, pin, parse_mode FROM scheduled_messages WHERE enabled=1",
        )
        now = datetime.now(timezone.utc)
        count = 0

        for row in rows:
            try:
                trigger = CronTrigger.from_crontab(row["cron"])
                # 检查当前时间是否匹配 cron 表达式
                # 使用 last_run 判断是否已执行过本轮
                last_run = row["last_run"]
                if last_run:
                    last_dt = datetime.fromisoformat(last_run)
                    # 如果上次执行距离现在不到 1 分钟，跳过
                    if (now - last_dt).total_seconds() < 60:
                        continue

                # 检查当前时间是否匹配
                if not trigger.get_next_fire_time(None, now):
                    continue
                if not trigger.get_next_fire_time(None, now.replace(second=0, microsecond=0)):
                    continue

                # 简单地检查 cron 是否在当前分钟匹配
                next_time = trigger.get_next_fire_time(None, now.replace(second=0, microsecond=0))
                if next_time is None:
                    continue
                # 如果下一个触发时间与当前时间相差超过 1 分钟，说明不是本轮
                if abs((next_time - now).total_seconds()) > 60:
                    continue

                # 发送消息
                keyboard = None
                if row["buttons"]:
                    buttons_data = json.loads(row["buttons"])
                    if buttons_data:
                        keyboard = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [InlineKeyboardButton(text=b["text"], url=b["url"])] for b in buttons_data
                            ]
                        )

                await self.bot.send_message(
                    row["chat_id"],
                    row["text"],
                    reply_markup=keyboard,
                    parse_mode=row["parse_mode"] or "HTML",
                )

                # 更新 last_run
                await self.db.execute(
                    "UPDATE scheduled_messages SET last_run=? WHERE id=?",
                    (utc_now_iso(), row["id"]),
                )
                count += 1
            except Exception as e:
                logger.warning("定时消息执行失败 (id=%d): %s", row["id"], e)

        return count