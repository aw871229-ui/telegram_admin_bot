from __future__ import annotations

import asyncio
import io
import random
import re
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.filters import Command
from aiogram.types import (
    BotCommand, CallbackQuery, ChatPermissions,
    InlineKeyboardButton, InlineKeyboardMarkup, Message,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

from .config import Settings, load_settings
from .db import Database
from .utils import (
    command_args, contains_link, normalize_domain,
    now_ts, parse_duration, resolve_target_user_id,
    safe_calculate, until_date_from_seconds,
    user_label, utc_now_iso,
)
from .services import SupportService, ChannelManager, ScheduledMessageExecutor
from .exchange import fetch_live_rates, get_cached_rate

logger = logging.getLogger(__name__)

settings: Settings = load_settings()
db = Database(settings.database_path)
dp = Dispatcher()
router = Router()
dp.include_router(router)

scheduler = AsyncIOScheduler(timezone="UTC")

message_windows: dict[tuple[int, int], deque[tuple[int, str]]] = defaultdict(lambda: deque(maxlen=8))

support_service: SupportService | None = None
channel_manager: ChannelManager | None = None
msg_executor: ScheduledMessageExecutor | None = None

DEFAULT_CHAT_SETTINGS: dict[str, Any] = {
    "welcome_text": "欢迎 {name} 加入本群，请先阅读 /rules。",
    "welcome_media_id": 0,
    "rules": "1. 禁止广告、诈骗、色情、刷屏。\n2. 禁止未经允许发送外链。\n3. 尊重他人，违规将被警告、禁言或封禁。",
    "warn_limit": settings.default_warn_limit,
    "mute_seconds": settings.default_mute_seconds,
    "slow_seconds": settings.default_slow_seconds,
    "silent_messages": settings.default_silent_messages,
    "captcha_enabled": True,
    "captcha_timeout": 60,
    "filter_enabled": True,
    "ledger_enabled": True,
    "ledger_reply_enabled": True,
    "exchange_rate": settings.default_exchange_rate,
    "fee_rate": settings.default_fee_rate,
    "rate_offset": 0.0,
    "rate_live": False,
    "rate_base": "USD",
    "display_mode": 1,
    "archive_no": 0,
    "locked": False,
    "block_forward_channels": [],
    "inactive_days": 30,
    "new_account_min_days": 0,
}


def is_group(message: Message) -> bool:
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}


async def ensure_context(message: Message) -> None:
    if message.chat:
        await db.ensure_chat(message.chat.id, message.chat.title, DEFAULT_CHAT_SETTINGS)
    if message.from_user:
        await db.upsert_user(message.from_user.id, message.from_user.username, message.from_user.full_name)


async def send_log(bot: Bot, chat_id: int | None, actor_id: int | None, target_id: int | None, action: str, detail: str = "") -> None:
    await db.add_log(chat_id, actor_id, target_id, action, detail)
    if settings.log_chat_id:
        text = (
            f"📝 操作日志\n"
            f"群组：{chat_id}\n"
            f"操作者：{actor_id}\n"
            f"目标：{target_id}\n"
            f"动作：{action}\n"
            f"详情：{detail}"
        )
        try:
            await bot.send_message(settings.log_chat_id, text)
        except Exception:
            pass


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    # 主人（SUPER_ADMINS）永远是管理员
    if user_id in settings.super_admins:
        return True
    # 数据库自定义角色
    role = await db.fetchone("SELECT role FROM roles WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    if role and role["role"] in {"super_admin", "admin"}:
        return True
    # 私有模式：只有主人和其授权的人可以管理，不认 Telegram 群管理员
    if settings.private_mode:
        return False
    # 非私有模式：Telegram 群管理员也算管理员
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    except Exception:
        return False


async def is_owner(user_id: int) -> bool:
    """判断是否是机器人的主人（SUPER_ADMINS 中的人）。"""
    return user_id in settings.super_admins


async def is_super_admin(chat_id: int, user_id: int) -> bool:
    if user_id in settings.super_admins:
        return True
    role = await db.fetchone("SELECT role FROM roles WHERE chat_id=? AND user_id=? AND role='super_admin'", (chat_id, user_id))
    return bool(role)


async def is_whitelisted(chat_id: int, user_id: int) -> bool:
    row = await db.fetchone("SELECT 1 FROM whitelist WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    return bool(row)


async def require_admin(message: Message, bot: Bot) -> bool:
    await ensure_context(message)
    if not message.from_user:
        return False
    if not is_group(message):
        await message.reply("这个命令需要在群组里使用。")
        return False
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        if settings.private_mode:
            await message.reply(
                "⚠️ 你没有管理员权限。\n"
                "本机器人处于私有模式，只有主人（/owner）和主人授权的人可以管理。\n"
                "如需授权请联系主人。"
            )
        else:
            await message.reply("你没有管理员权限。")
        return False
    return True


async def restrict_user(bot: Bot, chat_id: int, user_id: int, seconds: int | None, can_send: bool = False) -> None:
    permissions = ChatPermissions(
        can_send_messages=can_send,
        can_send_audios=can_send,
        can_send_documents=can_send,
        can_send_photos=can_send,
        can_send_videos=can_send,
        can_send_video_notes=can_send,
        can_send_voice_notes=can_send,
        can_send_polls=can_send,
        can_send_other_messages=can_send,
        can_add_web_page_previews=can_send,
    )
    await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=until_date_from_seconds(seconds))


def target_hint() -> str:
    return "请回复目标用户的消息使用，或使用数字 user_id。"


# ==================== 基础命令 ====================


@router.message(F.text == "开始")
async def start_cn(message: Message) -> None:
    await start_cmd(message)
async def start_cmd(message: Message) -> None:
    await ensure_context(message)
    if message.chat.type == ChatType.PRIVATE:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 联系客服", callback_data="support_start")],
        ])
        owner_id = next(iter(settings.super_admins)) if settings.super_admins else "未设置"
        await message.answer(
            f"👋 你好！我是群组管理机器人。\n\n"
            f"👑 主人：`{owner_id}`\n"
            f"🔒 私有模式：{'已开启' if settings.private_mode else '已关闭'}\n\n"
            f"功能：\n"
            f"• 私聊我可以联系客服\n"
            f"• 把我拉进群并设为管理员后，可使用 /help 查看命令\n\n"
            f"如果群聊中你被限制发言，可以在这里私聊我，我会把消息转给客服。",
            reply_markup=keyboard,
        )
    else:
        owner_id = next(iter(settings.super_admins)) if settings.super_admins else "未设置"
        await message.answer(
            f"管理员机器人已在本群启用。\n\n"
            f"👑 主人：`{owner_id}`\n"
            f"🔒 私有模式：{'已开启（仅主人和授权管理员可管理）' if settings.private_mode else '已关闭'}\n\n"
            f"使用 /help 查看命令。"
        )


@router.message(Command(["help", "帮助"]))
async def help_cmd(message: Message) -> None:
    await ensure_context(message)
    if message.chat.type == ChatType.PRIVATE:
        await message.answer(
            "🤖 私聊帮助\n\n"
            "直接发消息给我即可联系客服。\n"
            "如果你的消息包含文字以外的内容（图片、文件等），我会提示客服。\n\n"
            "群组命令请在群中使用 /help。"
        )
        return
    await message.answer(
        "📋 管理员命令（支持中文/英文）\n\n"
        "【基础】\n"
        "/rules /规则 - 查看群规\n"
        "/adminlist /管理员列表 - 查看管理员\n"
        "/me /我的 - 查看自己的数据\n"
        "/rank /活跃榜 - 活跃榜\n"
        "/quietest /最安静 - 最安静用户\n"
        "/report /举报 - 回复用户举报\n\n"
        "【禁言封禁】\n"
        "/warn /警告 - 回复用户警告\n"
        "/mute /禁言 [时间] - 禁言（1m/1h/1d/永久）\n"
        "/unmute /解禁 - 回复用户解禁\n"
        "/ban /封禁 - 回复用户封禁\n"
        "/unban /解封 - 回复用户解封\n"
        "/kick /踢出 - 回复用户踢出\n\n"
        "【消息管理】\n"
        "/del /删除 - 回复消息删除\n"
        "/clean /清理 [数量] - 清理消息\n"
        "/lock /锁群 - 锁群\n"
        "/unlock /解锁 - 解锁\n"
        "/slow /慢速 [秒] - 慢速模式\n\n"
        "【过滤设置】\n"
        "/addword /添加关键词 - 关键词过滤\n"
        "/delword /删除关键词 - 删除关键词\n"
        "/adddomain /添加域名 - 域名过滤\n"
        "/deldomain /删除域名 - 删除域名\n"
        "/whitelist /白名单 - 白名单\n"
        "/unwhitelist /移除白名单 - 移除白名单\n"
        "/setwelcome /设置欢迎 - 设置欢迎消息\n"
        "/setwelcomeimg /设置欢迎图片 - 回复图片设置欢迎图\n"
        "/setnewaccount /新号限制 [天数] - 新号限制\n\n"
        "【频道管理】\n"
        "/post /发帖 [频道ID] 文字 - 发送到频道\n"
        "/postbtn /发帖按钮 [频道ID] 标题|按钮名=URL - 带按钮发帖\n"
        "/schedule /定时 列表 - 查看定时公告\n"
        "/schedule /定时 删除 ID - 删除定时公告\n\n"
        "【记账】\n"
        "+100、-100、+100/0.05、下发100、100*7.2\n"
        "显示账单、保存账单、清理当日账单、删除历史账单\n"
        "设置汇率 7.2、设置费率 0.05\n"
        "设置汇率上浮/下浮、设置实时汇率\n\n"
        "【管理】\n"
        "/broadcast /广播 文字 - 全群广播\n"
        "/stats /统计 - 统计面板\n"
        "/logs /日志 - 操作日志\n"
        "/export /导出 - 导出日志和账单 CSV\n"
        "/owner /主人 - 查看机器人主人\n"
        "/setadmin /授权管理员 - 主人授权管理员\n"
        "/deladmin /撤销管理员 - 主人撤销管理员\n"
        "/updategroup /同步管理员 - 同步管理员权限\n"
        "/cleaninactive /清理不活跃 [天数] - 清理不活跃成员\n"
    )


@router.message(Command(["owner", "主人"]))
async def owner_cmd(message: Message) -> None:
    """查看机器人的主人信息。"""
    await ensure_context(message)
    owners = settings.super_admins
    if not owners:
        await message.reply("❌ 未设置主人。请在 .env 中配置 SUPER_ADMINS。")
        return
    owner_ids = "\n".join(f"  • `{uid}`" for uid in sorted(owners))
    await message.answer(
        f"👑 **机器人主人**\n\n"
        f"主人的 ID：\n{owner_ids}\n\n"
        f"🔒 私有模式：{'已开启' if settings.private_mode else '已关闭'}\n"
        f"私有模式开启时，只有主人和主人通过 /setadmin 授权的人可以管理本机器人。\n\n"
        f"💡 如需授权他人管理，主人可使用：\n"
        f"`/setadmin`（回复目标用户）"
    )


@router.message(Command(["rules", "规则"]))
async def rules_cmd(message: Message) -> None:
    await ensure_context(message)
    cfg = await db.get_settings(message.chat.id)
    await message.answer(cfg.get("rules", DEFAULT_CHAT_SETTINGS["rules"]))


@router.message(Command(["adminlist", "管理员列表"]))
async def adminlist_cmd(message: Message, bot: Bot) -> None:
    await ensure_context(message)
    if not is_group(message):
        await message.answer("请在群组里使用。")
        return
    custom = await db.fetchall("SELECT user_id,role FROM roles WHERE chat_id=? ORDER BY role DESC", (message.chat.id,))
    owner_ids = sorted(settings.super_admins)
    lines = ["👑 **主人（主人）**："]
    for uid in owner_ids:
        lines.append(f"  • `{uid}`")
    lines.append("")
    lines.append("📋 **授权管理员**：")
    if custom:
        for row in custom:
            label = "超级管理员" if row["role"] == "super_admin" else "管理员"
            lines.append(f"  • `{row['user_id']}` — {label}")
    else:
        lines.append("  暂无（主人可使用 /setadmin 授权）")
    lines.append(f"\n🔒 私有模式：{'已开启' if settings.private_mode else '已关闭'}")
    await message.answer("\n".join(lines))


@router.message(Command(["setadmin", "授权管理员"]))
async def setadmin_cmd(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return
    if not await is_owner(message.from_user.id):
        await message.reply("⚠️ 只有机器人的主人可以设置管理员。\n你的 ID 不在主人列表中，如需授权请联系主人。")
        return
    if not is_group(message):
        await message.reply("这个命令需要在群组里使用。")
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply(target_hint())
        return
    role = "admin"
    args = command_args(message)
    if len(args) >= 2 and args[1] in {"admin", "super_admin"}:
        role = args[1]
    await db.execute(
        "INSERT INTO roles(chat_id,user_id,role) VALUES(?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET role=excluded.role",
        (message.chat.id, target_id, role),
    )
    await send_log(bot, message.chat.id, message.from_user.id, target_id, "setadmin", role)
    await message.reply(f"✅ 已授权 {target_id} 为 {'超级管理员' if role == 'super_admin' else '管理员'}。")


@router.message(Command(["deladmin", "撤销管理员"]))
async def deladmin_cmd(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return
    if not await is_owner(message.from_user.id):
        await message.reply("⚠️ 只有机器人的主人可以删除管理员。")
        return
    if not is_group(message):
        await message.reply("这个命令需要在群组里使用。")
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply(target_hint())
        return
    await db.execute("DELETE FROM roles WHERE chat_id=? AND user_id=?", (message.chat.id, target_id))
    await send_log(bot, message.chat.id, message.from_user.id, target_id, "deladmin")
    await message.reply(f"✅ 已撤销 {target_id} 的管理员权限。")


@router.message(Command(["updategroup", "同步管理员"]))
async def update_group_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        for admin in admins:
            if admin.user:
                role = "super_admin" if admin.status == ChatMemberStatus.CREATOR else "admin"
                await db.execute(
                    "INSERT OR IGNORE INTO roles(chat_id,user_id,role) VALUES(?,?,?)",
                    (message.chat.id, admin.user.id, role),
                )
        await message.answer(f"已同步 {len(admins)} 位管理员权限。")
    except Exception as e:
        await message.reply(f"同步失败：{e}")


# ==================== 禁言/封禁/踢出 ====================


@router.message(Command(["mute", "禁言"]))
async def mute_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply(target_hint())
        return
    args = command_args(message)
    duration_text = args[1] if len(args) >= 2 and args[0].lstrip("-").isdigit() else (args[0] if args else None)
    seconds = parse_duration(duration_text, settings.default_mute_seconds)
    await restrict_user(bot, message.chat.id, target_id, seconds, can_send=False)
    await send_log(bot, message.chat.id, message.from_user.id, target_id, "mute", duration_text or "默认")
    label = duration_text or f"{settings.default_mute_seconds // 60}分钟"
    await message.reply(f"🔇 已禁言 {target_id}，时长：{label}。")


@router.message(Command(["unmute", "解禁"]))
async def unmute_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply(target_hint())
        return
    await restrict_user(bot, message.chat.id, target_id, 30, can_send=True)
    await send_log(bot, message.chat.id, message.from_user.id, target_id, "unmute")
    await message.reply(f"✅ 已解除 {target_id} 的禁言。")


@router.message(Command(["ban", "封禁"]))
async def ban_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply(target_hint())
        return
    await bot.ban_chat_member(message.chat.id, target_id)
    await db.execute(
        "INSERT INTO global_blacklist(user_id,reason,created_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET reason=excluded.reason",
        (target_id, "管理员封禁", utc_now_iso()),
    )
    await send_log(bot, message.chat.id, message.from_user.id, target_id, "ban", "已加入全局黑名单")
    await message.reply(f"🚫 已封禁 {target_id}，并加入全局黑名单。")


@router.message(Command(["unban", "解封"]))
async def unban_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply(target_hint())
        return
    await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
    await db.execute("DELETE FROM global_blacklist WHERE user_id=?", (target_id,))
    await send_log(bot, message.chat.id, message.from_user.id, target_id, "unban")
    await message.reply(f"✅ 已解封 {target_id}。")


@router.message(Command(["kick", "踢出"]))
async def kick_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply(target_hint())
        return
    await bot.ban_chat_member(message.chat.id, target_id)
    await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
    await send_log(bot, message.chat.id, message.from_user.id, target_id, "kick")
    await message.reply(f"🦶 已踢出 {target_id}。")


@router.message(Command(["warn", "警告"]))
async def warn_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply(target_hint())
        return
    cfg = await db.get_settings(message.chat.id)
    await db.execute(
        "INSERT INTO memberships(chat_id,user_id,warns) VALUES(?,?,1) ON CONFLICT(chat_id,user_id) DO UPDATE SET warns=warns+1",
        (message.chat.id, target_id),
    )
    row = await db.fetchone("SELECT warns FROM memberships WHERE chat_id=? AND user_id=?", (message.chat.id, target_id))
    warns = int(row["warns"]) if row else 1
    limit = int(cfg.get("warn_limit", settings.default_warn_limit))
    await send_log(bot, message.chat.id, message.from_user.id, target_id, "warn", f"{warns}/{limit}")
    if warns >= limit:
        await bot.ban_chat_member(message.chat.id, target_id)
        await message.reply(f"⛔ {target_id} 已累计 {warns} 次警告，达到上限，已自动封禁。")
    else:
        await message.reply(f"⚠️ 已警告 {target_id}，当前 {warns}/{limit}。")


# ==================== 消息管理 ====================


@router.message(Command(["del", "删除"]))
async def del_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    if not message.reply_to_message:
        await message.reply("请回复要删除的消息。")
        return
    await bot.delete_message(message.chat.id, message.reply_to_message.message_id)
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    await send_log(bot, message.chat.id, message.from_user.id, None, "delete_message")


@router.message(Command(["clean", "清理"]))
async def clean_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    args = command_args(message)
    count = min(int(args[0]), 100) if args and args[0].isdigit() else 20
    deleted = 0
    for mid in range(message.message_id, max(message.message_id - count, 0), -1):
        try:
            await bot.delete_message(message.chat.id, mid)
            deleted += 1
        except Exception:
            continue
    await send_log(bot, message.chat.id, message.from_user.id, None, "clean", str(deleted))
    note = await message.answer(f"🗑 已尝试清理，成功删除 {deleted} 条。")
    await asyncio.sleep(3)
    try:
        await note.delete()
    except Exception:
        pass


@router.message(Command(["lock", "锁群"]))
async def lock_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    await bot.set_chat_permissions(message.chat.id, ChatPermissions(can_send_messages=False))
    await db.set_setting(message.chat.id, "locked", True)
    await send_log(bot, message.chat.id, message.from_user.id, None, "lock")
    await message.reply("🔒 已锁定群聊，仅管理员可发言。")


@router.message(Command(["unlock", "解锁"]))
async def unlock_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    await bot.set_chat_permissions(message.chat.id, ChatPermissions(can_send_messages=True))
    await db.set_setting(message.chat.id, "locked", False)
    await send_log(bot, message.chat.id, message.from_user.id, None, "unlock")
    await message.reply("🔓 已解除群聊锁定。")


@router.message(Command(["slow", "慢速"]))
async def slow_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    args = command_args(message)
    seconds = int(args[0]) if args and args[0].isdigit() else settings.default_slow_seconds
    await db.set_setting(message.chat.id, "slow_seconds", seconds)
    await send_log(bot, message.chat.id, message.from_user.id, None, "slow", str(seconds))
    await message.reply(f"⏱ 已设置慢速检测：{seconds} 秒。")


# ==================== 过滤设置 ====================


@router.message(Command(["addword", "添加关键词"]))
async def addword_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    word = " ".join(command_args(message)).strip()
    if not word:
        await message.reply("用法：/addword 关键词")
        return
    await db.execute("INSERT OR IGNORE INTO word_filters(chat_id,word,kind) VALUES(?,?,?)", (message.chat.id, word.lower(), "keyword"))
    await message.reply(f"已添加关键词：{word}")


@router.message(Command(["delword", "删除关键词"]))
async def delword_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    word = " ".join(command_args(message)).strip()
    await db.execute("DELETE FROM word_filters WHERE chat_id=? AND word=? AND kind='keyword'", (message.chat.id, word.lower()))
    await message.reply(f"已删除关键词：{word}")


@router.message(Command("adddomain"))
async def adddomain_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    domain = normalize_domain(" ".join(command_args(message)).strip())
    if not domain:
        await message.reply("用法：/adddomain example.com")
        return
    await db.execute("INSERT OR IGNORE INTO word_filters(chat_id,word,kind) VALUES(?,?,?)", (message.chat.id, domain, "domain"))
    await message.reply(f"已添加黑名单域名：{domain}")


@router.message(Command(["deldomain", "删除域名"]))
async def deldomain_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    domain = normalize_domain(" ".join(command_args(message)).strip())
    await db.execute("DELETE FROM word_filters WHERE chat_id=? AND word=? AND kind='domain'", (message.chat.id, domain))
    await message.reply(f"已删除黑名单域名：{domain}")


@router.message(Command(["whitelist", "白名单"]))
async def whitelist_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply(target_hint())
        return
    await db.execute("INSERT OR IGNORE INTO whitelist(chat_id,user_id,note) VALUES(?,?,?)", (message.chat.id, target_id, "管理员添加"))
    await message.reply(f"✅ 已加入白名单：{target_id}")


@router.message(Command(["unwhitelist", "移除白名单"]))
async def unwhitelist_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply(target_hint())
        return
    await db.execute("DELETE FROM whitelist WHERE chat_id=? AND user_id=?", (message.chat.id, target_id))
    await message.reply(f"已移出白名单：{target_id}")


@router.message(Command(["setwelcome", "设置欢迎"]))
async def setwelcome_cmd(message: Message, bot: Bot) -> None:
    """设置欢迎文字，支持 {name} 占位符。"""
    if not await require_admin(message, bot):
        return
    text = " ".join(command_args(message)).strip()
    if not text:
        await message.reply("用法：/setwelcome 欢迎文字，用 {name} 代表新人名字")
        return
    await db.set_setting(message.chat.id, "welcome_text", text)
    await message.reply(f"✅ 欢迎消息已设置。\n当前：{text}")


@router.message(Command(["setwelcomeimg", "设置欢迎图片"]))
async def setwelcomeimg_cmd(message: Message, bot: Bot) -> None:
    """回复一张图片，设为入群欢迎图片。"""
    if not await require_admin(message, bot):
        return
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply("请回复一张图片消息来设置欢迎图片。用法：回复图片，然后发送 /setwelcomeimg")
        return
    photo = message.reply_to_message.photo[-1]
    media_id = await db.save_media(message.chat.id, photo.file_id, "photo", None)
    await db.set_setting(message.chat.id, "welcome_media_id", media_id)
    await message.reply("✅ 欢迎图片已设置。新人入群时会自动发送这张图片 + 欢迎文字。")


@router.message(Command(["setnewaccount", "新号限制"]))
async def setnewaccount_cmd(message: Message, bot: Bot) -> None:
    """设置新号限制天数。"""
    if not await require_admin(message, bot):
        return
    args = command_args(message)
    if not args or not args[0].isdigit():
        await message.reply("用法：/setnewaccount 天数  （设为 0 关闭新号限制）")
        return
    days = int(args[0])
    await db.set_setting(message.chat.id, "new_account_min_days", days)
    if days > 0:
        await message.reply(f"✅ 已设置新号限制：注册或首次出现不满 {days} 天的用户将被限制发言。")
    else:
        await message.reply("✅ 已关闭新号限制。")


@router.message(Command(["report", "举报"]))
async def report_cmd(message: Message, bot: Bot) -> None:
    await ensure_context(message)
    if not is_group(message) or not message.from_user:
        return
    target_id = await resolve_target_user_id(message)
    if not target_id:
        await message.reply("请回复要举报的用户。")
        return
    reason = " ".join(command_args(message)[1:]) or "未填写原因"
    await send_log(bot, message.chat.id, message.from_user.id, target_id, "report", reason)
    await message.reply("✅ 举报已提交给管理员。")


@router.message(Command(["me", "我的"]))
async def me_cmd(message: Message) -> None:
    await ensure_context(message)
    if not message.from_user:
        return
    row = await db.fetchone(
        "SELECT joined_at,warns,message_count,silent_left FROM memberships WHERE chat_id=? AND user_id=?",
        (message.chat.id, message.from_user.id),
    )
    if not row:
        await message.reply("暂无你的群内数据。")
        return
    joined = datetime.fromtimestamp(row["joined_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if row["joined_at"] else "未知"
    await message.reply(
        f"📊 你的数据\n"
        f"入群时间：{joined}\n"
        f"警告次数：{row['warns']}\n"
        f"发言数：{row['message_count']}\n"
        f"待审核消息：{row['silent_left']}"
    )


@router.message(Command(["rank", "活跃榜"]))
async def rank_cmd(message: Message) -> None:
    await ensure_context(message)
    rows = await db.fetchall(
        "SELECT user_id,message_count FROM memberships WHERE chat_id=? ORDER BY message_count DESC LIMIT 10",
        (message.chat.id,),
    )
    if not rows:
        await message.reply("暂无排行数据。")
        return
    lines = ["🏆 活跃度排名（话痨榜）"]
    for i, r in enumerate(rows, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "  ")
        lines.append(f"{medal} {i}. {r['user_id']} — {r['message_count']} 条")
    await message.answer("\n".join(lines))


@router.message(Command(["quietest", "最安静"]))
async def quietest_cmd(message: Message) -> None:
    """最安静用户排名。"""
    await ensure_context(message)
    rows = await db.fetchall(
        "SELECT user_id,message_count,joined_at FROM memberships WHERE chat_id=? AND left_at IS NULL ORDER BY message_count ASC LIMIT 10",
        (message.chat.id,),
    )
    if not rows:
        await message.reply("暂无排行数据。")
        return
    lines = ["🐌 最安静成员"]
    for i, r in enumerate(rows, 1):
        days = max(1, (now_ts() - (r["joined_at"] or now_ts())) // 86400) if r["joined_at"] else 1
        lines.append(f"  {i}. {r['user_id']} — {r['message_count']} 条（约 {days} 天）")
    await message.answer("\n".join(lines))


# ==================== 频道管理 ====================


@router.message(Command(["post", "发帖"]))
async def post_cmd(message: Message, bot: Bot) -> None:
    if not message.from_user or message.from_user.id not in settings.super_admins:
        await message.reply("只有全局超级管理员可以发帖。")
        return
    args = command_args(message)
    if len(args) < 2 or not args[0].lstrip("-").isdigit():
        await message.reply("用法：/post 频道ID 文字内容")
        return
    channel_id = int(args[0])
    text = " ".join(args[1:])
    try:
        await bot.send_message(channel_id, text, parse_mode=ParseMode.HTML)
        await message.reply(f"✅ 已发送到频道 {channel_id}。")
    except Exception as e:
        await message.reply(f"发送失败：{e}")


@router.message(Command(["postbtn", "发帖按钮"]))
async def postbtn_cmd(message: Message, bot: Bot) -> None:
    if not message.from_user or message.from_user.id not in settings.super_admins:
        await message.reply("只有全局超级管理员可以发帖。")
        return
    args = command_args(message)
    if len(args) < 2 or not args[0].lstrip("-").isdigit():
        await message.reply("用法：/postbtn 频道ID 标题|按钮名1=URL1|按钮名2=URL2")
        return
    channel_id = int(args[0])
    parts_text = " ".join(args[1:])
    segments = parts_text.split("|")
    if not segments:
        await message.reply("格式不正确。")
        return
    text = segments[0].strip()
    buttons = []
    for seg in segments[1:]:
        seg = seg.strip()
        if "=" in seg:
            btn_text, btn_url = seg.split("=", 1)
            buttons.append({"text": btn_text.strip(), "url": btn_url.strip()})
    try:
        keyboard = None
        if buttons:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=b["text"], url=b["url"])] for b in buttons]
            )
        await bot.send_message(channel_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        await message.reply(f"✅ 带按钮帖子已发送到频道 {channel_id}。")
    except Exception as e:
        await message.reply(f"发送失败：{e}")


@router.message(Command(["schedule", "定时"]))
async def schedule_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    args = command_args(message)
    if not args:
        await message.reply("用法：/schedule 列表/删除")
        return
    action = args[0].lower()
    if action == "列表":
        items = await channel_manager.list_scheduled(message.chat.id)
        if not items:
            await message.reply("暂无定时公告。")
            return
        lines = ["📋 定时公告列表："]
        for item in items:
            status = "✅ 启用" if item["enabled"] else "❌ 停用"
            lines.append(f"  ID:{item['id']} [{status}] {item['cron']} - {item['text'][:30]}...")
        await message.answer("\n".join(lines))
    elif action == "删除":
        if len(args) < 2 or not args[1].isdigit():
            await message.reply("用法：/schedule 删除 ID")
            return
        await channel_manager.delete_scheduled(int(args[1]))
        await message.reply(f"已删除定时公告 {args[1]}。")
    else:
        await message.reply("用法：/schedule 列表/删除")


# ==================== 广播和统计 ====================


@router.message(Command(["broadcast", "广播"]))
async def broadcast_cmd(message: Message, bot: Bot) -> None:
    if not message.from_user or message.from_user.id not in settings.super_admins:
        await message.reply("只有全局超级管理员可以广播。")
        return
    text = " ".join(command_args(message)).strip()
    if not text:
        await message.reply("用法：/broadcast 要广播的内容")
        return
    rows = await db.fetchall("SELECT chat_id FROM chats")
    ok = 0
    for row in rows:
        try:
            await bot.send_message(row["chat_id"], f"📢 广播\n\n{text}")
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            continue
    await message.reply(f"广播完成，成功发送到 {ok} 个群/频道。")


@router.message(Command(["stats", "统计"]))
async def stats_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    chat_id = message.chat.id
    logs = await db.fetchone("SELECT COUNT(*) AS c FROM moderation_logs WHERE chat_id=?", (chat_id,))
    users = await db.fetchone("SELECT COUNT(*) AS c FROM memberships WHERE chat_id=? AND left_at IS NULL", (chat_id,))
    msgs = await db.fetchone("SELECT SUM(message_count) AS c FROM memberships WHERE chat_id=?", (chat_id,))
    today_logs = await db.fetchone(
        "SELECT COUNT(*) AS c FROM moderation_logs WHERE chat_id=? AND created_at>=?",
        (chat_id, datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")),
    )
    top5 = await db.fetchall(
        "SELECT user_id,message_count FROM memberships WHERE chat_id=? ORDER BY message_count DESC LIMIT 5",
        (chat_id,),
    )
    top_lines = "\n".join(f"  {r['user_id']}：{r['message_count']} 条" for r in top5) or "暂无"
    bottom5 = await db.fetchall(
        "SELECT user_id,message_count FROM memberships WHERE chat_id=? AND left_at IS NULL AND message_count>0 ORDER BY message_count ASC LIMIT 5",
        (chat_id,),
    )
    bottom_lines = "\n".join(f"  {r['user_id']}：{r['message_count']} 条" for r in bottom5) or "暂无"
    await message.reply(
        f"📊 统计面板\n\n"
        f"👥 当前成员：{users['c'] or 0}\n"
        f"💬 累计消息：{msgs['c'] or 0}\n"
        f"🔧 管理操作：{logs['c'] or 0}\n"
        f"📅 今日操作：{today_logs['c'] or 0}\n\n"
        f"🏆 话痨 TOP 5：\n{top_lines}\n\n"
        f"🐌 安静 TOP 5：\n{bottom_lines}"
    )


@router.message(Command(["logs", "日志"]))
async def logs_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    rows = await db.fetchall(
        "SELECT actor_id,target_id,action,detail,created_at FROM moderation_logs WHERE chat_id=? ORDER BY id DESC LIMIT 20",
        (message.chat.id,),
    )
    if not rows:
        await message.reply("暂无日志。")
        return
    lines = ["📋 最近 20 条日志："]
    for r in rows:
        lines.append(f"  {r['created_at']} | {r['action']} | 操作:{r['actor_id']} | 目标:{r['target_id']} | {r['detail'] or ''}")
    await message.answer("\n".join(lines))


@router.message(Command(["export", "导出"]))
async def export_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot):
        return
    chat_id = message.chat.id
    from .export import export_logs_to_csv, export_ledger_to_csv

    log_rows = await db.fetchall("SELECT * FROM moderation_logs WHERE chat_id=? ORDER BY id DESC LIMIT 5000", (chat_id,))
    log_csv = export_logs_to_csv([dict(r) for r in log_rows])
    if log_csv:
        log_file = io.BytesIO(log_csv.encode("utf-8-sig"))
        log_file.name = f"logs_{chat_id}.csv"
        await message.reply_document(log_file, caption=f"操作日志导出（{len(log_rows)} 条）")
    else:
        await message.reply("暂无日志可导出。")

    ledger_rows = await db.fetchall("SELECT * FROM ledger_entries WHERE chat_id=? ORDER BY id DESC LIMIT 5000", (chat_id,))
    ledger_csv = export_ledger_to_csv([dict(r) for r in ledger_rows])
    if ledger_csv:
        ledger_file = io.BytesIO(ledger_csv.encode("utf-8-sig"))
        ledger_file.name = f"ledger_{chat_id}.csv"
        await message.reply_document(ledger_file, caption=f"记账明细导出（{len(ledger_rows)} 条）")


@router.message(Command(["cleaninactive", "清理不活跃"]))
async def clean_inactive_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(message, bot) or not message.from_user:
        return
    args = command_args(message)
    cfg = await db.get_settings(message.chat.id)
    days = int(args[0]) if args and args[0].isdigit() else int(cfg.get("inactive_days", 30))
    threshold = now_ts() - days * 86400
    rows = await db.fetchall(
        "SELECT user_id FROM memberships WHERE chat_id=? AND left_at IS NULL AND last_message_at IS NOT NULL AND last_message_at<?",
        (message.chat.id, threshold),
    )
    kicked = 0
    for r in rows:
        try:
            await bot.ban_chat_member(message.chat.id, r["user_id"])
            await bot.unban_chat_member(message.chat.id, r["user_id"], only_if_banned=True)
            await db.member_left(message.chat.id, r["user_id"])
            kicked += 1
        except Exception:
            continue
        await asyncio.sleep(0.1)
    await send_log(bot, message.chat.id, message.from_user.id, None, "clean_inactive", f"{days}天/{kicked}人")
    await message.reply(f"已清理 {kicked} 位超过 {days} 天不活跃的成员。")


# ==================== 记账功能 ====================


async def ledger_add(message: Message, kind: str, amount: float, fee_rate: float | None = None) -> None:
    if not message.from_user:
        return
    cfg = await db.get_settings(message.chat.id)
    if cfg.get("rate_live", False):
        rate = get_cached_rate(cfg.get("rate_base", "USD"), cfg.get("exchange_rate", settings.default_exchange_rate))
        rate += float(cfg.get("rate_offset", 0))
    else:
        rate = float(cfg.get("exchange_rate", settings.default_exchange_rate)) + float(cfg.get("rate_offset", 0))
    fee = float(fee_rate if fee_rate is not None else cfg.get("fee_rate", settings.default_fee_rate))
    final_amount = amount * rate * (1 - fee) if kind == "deposit" else amount
    archive_no = int(cfg.get("archive_no", 0))
    await db.execute(
        "INSERT INTO ledger_entries(chat_id,user_id,kind,amount,rate,fee_rate,final_amount,note,archive_no,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (message.chat.id, message.from_user.id, kind, amount, rate, fee, final_amount, "", archive_no, utc_now_iso()),
    )
    if cfg.get("ledger_reply_enabled", True):
        title = "💰 入款" if kind == "deposit" else "💸 下发"
        await message.reply(f"{title}已记录\n金额：{amount:g}\n汇率：{rate:g}\n费率：{fee:g}\n折算：{final_amount:g}")


async def show_ledger(message: Message, target_user_id: int | None = None) -> None:
    """显示账单，支持回复查他人。"""
    cfg = await db.get_settings(message.chat.id)
    archive_no = int(cfg.get("archive_no", 0))
    if target_user_id:
        rows = await db.fetchall(
            "SELECT kind,amount,rate,fee_rate,final_amount,user_id,created_at FROM ledger_entries WHERE chat_id=? AND archive_no=? AND user_id=? ORDER BY id DESC LIMIT 20",
            (message.chat.id, archive_no, target_user_id),
        )
        deposits = sum(float(r["amount"]) for r in rows if r["kind"] == "deposit")
        payouts = sum(float(r["amount"]) for r in rows if r["kind"] == "payout")
        final_total = sum(float(r["final_amount"] or 0) for r in rows if r["kind"] == "deposit") - payouts
        detail_lines = [f"  {r['kind']} {r['amount']:g} ({r['created_at'][:16]})" for r in rows[:10]]
        await message.reply(
            f"📊 {target_user_id} 的今日账单 / 档案号 {archive_no}\n"
            f"入款合计：{deposits:g}\n"
            f"下发合计：{payouts:g}\n"
            f"折算余额：{final_total:g}\n\n"
            f"最近明细：\n" + ("\n".join(detail_lines) if detail_lines else "  暂无")
        )
    else:
        rows = await db.fetchall(
            "SELECT kind,amount,rate,fee_rate,final_amount,user_id,created_at FROM ledger_entries WHERE chat_id=? AND archive_no=? ORDER BY id DESC",
            (message.chat.id, archive_no),
        )
        deposits = sum(float(r["amount"]) for r in rows if r["kind"] == "deposit")
        payouts = sum(float(r["amount"]) for r in rows if r["kind"] == "payout")
        final_total = sum(float(r["final_amount"] or 0) for r in rows if r["kind"] == "deposit") - payouts
        mode = int(cfg.get("display_mode", 1))
        detail_lines = []
        for r in rows[:20]:
            if mode == 1:
                detail_lines.append(f"  {r['kind']} {r['amount']:g} 操作:{r['user_id']}")
            elif mode == 2:
                detail_lines.append(f"  [{r['kind']}] {r['amount']:g} → {r['final_amount']:g} ({r['user_id']})")
            else:
                detail_lines.append(f"  {r['created_at']} {r['kind']} {r['amount']:g} 汇率:{r['rate']} 费率:{r['fee_rate']}")
        await message.reply(
            f"📊 今日账单 / 档案号 {archive_no}\n"
            f"入款合计：{deposits:g}\n"
            f"下发合计：{payouts:g}\n"
            f"折算余额：{final_total:g}\n\n"
            f"最近明细：\n" + ("\n".join(detail_lines) if detail_lines else "  暂无")
        )


async def handle_ledger_text(message: Message, bot: Bot) -> bool:
    text = (message.text or "").strip()
    if not is_group(message) or not message.from_user:
        return False
    cfg = await db.get_settings(message.chat.id)
    blocked = await db.fetchone("SELECT 1 FROM blocked_operators WHERE chat_id=? AND user_id=?", (message.chat.id, message.from_user.id))
    if blocked:
        return False

    if text in {"开始", "开始记账"}:
        await db.set_setting(message.chat.id, "ledger_enabled", True)
        await message.reply("✅ 记账功能已开启。")
        return True
    if text in {"关闭记账"}:
        await db.set_setting(message.chat.id, "ledger_reply_enabled", False)
        await message.reply("🔇 已开启静默记账。")
        return True
    if text in {"打开记账"}:
        await db.set_setting(message.chat.id, "ledger_reply_enabled", True)
        await message.reply("🔔 已恢复记账提醒。")
        return True
    if text in {"+0", "显示账单", "账单"}:
        # 检查是否回复查他人
        target_id = await resolve_target_user_id(message)
        if target_id and target_id != message.from_user.id:
            await show_ledger(message, target_user_id=target_id)
        else:
            await show_ledger(message)
        return True
    if text == "保存账单":
        archive_no = int(cfg.get("archive_no", 0)) + 1
        await db.set_setting(message.chat.id, "archive_no", archive_no)
        await message.reply(f"📁 账单已存档，新档案号：{archive_no}")
        return True
    if text == "清理当日账单":
        await db.execute("DELETE FROM ledger_entries WHERE chat_id=? AND archive_no=?", (message.chat.id, int(cfg.get("archive_no", 0))))
        await message.reply("🗑 今日账单已清理。")
        return True
    if text == "删除历史账单":
        await db.execute("DELETE FROM ledger_entries WHERE chat_id=?", (message.chat.id,))
        await message.reply("🗑 历史账单已彻底删除。")
        return True
    if text in {"本群记账"}:
        live = "实时" if cfg.get("rate_live") else "固定"
        await message.reply(
            f"📊 本群记账状态\n"
            f"记账：{'开启' if cfg.get('ledger_enabled', True) else '关闭'}\n"
            f"提醒：{'开启' if cfg.get('ledger_reply_enabled', True) else '关闭'}\n"
            f"汇率模式：{live}\n"
            f"汇率：{cfg.get('exchange_rate')}\n"
            f"费率：{cfg.get('fee_rate')}\n"
            f"上/下浮：{cfg.get('rate_offset', 0)}\n"
            f"显示模式：{cfg.get('display_mode', 1)}"
        )
        return True

    # 实时汇率查询
    if text.lower() in {"z0"} or text == "Z0":
        await message.reply("⏳ 正在获取实时汇率...")
        try:
            rates = await fetch_live_rates()
            cny = rates.get("CNY", 0)
            await message.reply(
                f"💱 实时汇率（USD 基准）\n\n"
                f"USD → CNY：{cny:.4f}\n"
                f"USD → EUR：{rates.get('EUR', 0):.4f}\n"
                f"USD → GBP：{rates.get('GBP', 0):.4f}\n"
                f"USD → JPY：{rates.get('JPY', 0):.4f}\n"
                f"USD → KRW：{rates.get('KRW', 0):.2f}\n"
                f"USD → RUB：{rates.get('RUB', 0):.4f}\n"
                f"USD → THB：{rates.get('THB', 0):.4f}\n"
                f"\n缓存时间：5分钟"
            )
        except Exception as e:
            await message.reply(f"获取汇率失败：{e}")
        return True

    if text == "设置实时汇率":
        await db.set_setting(message.chat.id, "rate_live", True)
        await message.reply("✅ 已切换为实时汇率模式。使用 z0 查看当前汇率。")
        return True

    for prefix, key in [
        ("设置汇率上浮", "rate_offset"),
        ("设置汇率下浮", "rate_offset"),
        ("设置汇率", "exchange_rate"),
        ("设置费率", "fee_rate"),
        ("显示模式", "display_mode"),
        ("设置更新时间", "update_hour"),
    ]:
        if text.startswith(prefix):
            value_text = text.replace(prefix, "", 1).strip()
            try:
                value: float | int = float(value_text)
                if prefix == "设置汇率下浮":
                    value = -abs(value)
                if prefix in ("显示模式", "设置更新时间"):
                    value = int(value)
                await db.set_setting(message.chat.id, key, value)
                await message.reply(f"✅ 已设置：{prefix} {value}")
            except ValueError:
                await message.reply("❌ 数值格式不正确。")
            return True

    if text.startswith("设置不允许操作人"):
        target_id = await resolve_target_user_id(message)
        if not target_id:
            await message.reply("请回复目标用户。")
            return True
        await db.execute("INSERT OR IGNORE INTO blocked_operators(chat_id,user_id,note) VALUES(?,?,?)", (message.chat.id, target_id, "禁止记账"))
        await message.reply(f"🚫 已禁止 {target_id} 记账。")
        return True
    if text.startswith("删除不允许操作人"):
        target_id = await resolve_target_user_id(message)
        if not target_id:
            await message.reply("请回复目标用户。")
            return True
        await db.execute("DELETE FROM blocked_operators WHERE chat_id=? AND user_id=?", (message.chat.id, target_id))
        await message.reply(f"✅ 已恢复 {target_id} 记账权限。")
        return True
    if text == "显示不允许操作人":
        rows = await db.fetchall("SELECT user_id FROM blocked_operators WHERE chat_id=?", (message.chat.id,))
        await message.answer("🚫 不允许操作人：\n" + ("\n".join(str(r["user_id"]) for r in rows) or "暂无"))
        return True

    if not cfg.get("ledger_enabled", True):
        return False

    calc = safe_calculate(text)
    if calc is not None:
        await message.reply(f"🔢 {text} = {calc:g}")
        return True

    m = re.match(r"^(?:入款)?([+-]\d+(?:\.\d+)?)(?:/(\d+(?:\.\d+)?))?$", text)
    if m:
        await ledger_add(message, "deposit", float(m.group(1)), float(m.group(2)) if m.group(2) else None)
        return True
    m = re.match(r"^下发([+-]?\d+(?:\.\d+)?)$", text)
    if m:
        await ledger_add(message, "payout", float(m.group(1)), None)
        return True
    return False


# ==================== 过滤系统 ====================


async def check_new_account_restriction(message: Message, bot: Bot) -> bool:
    """检查新号限制：如果用户首次出现时间 < 设定天数，则限制发言。"""
    if not message.from_user:
        return False
    cfg = await db.get_settings(message.chat.id)
    min_days = int(cfg.get("new_account_min_days", 0))
    if min_days <= 0:
        return False
    first_seen = await db.get_first_seen(message.from_user.id)
    if first_seen is None:
        return False
    age_days = (now_ts() - first_seen) / 86400
    if age_days < min_days:
        await message.delete()
        try:
            await bot.restrict_chat_member(
                message.chat.id,
                message.from_user.id,
                ChatPermissions(can_send_messages=False),
                until_date=until_date_from_seconds(300),
            )
            await send_log(bot, message.chat.id, None, message.from_user.id, "new_account_restrict",
                           f"age={age_days:.1f}d, min={min_days}d")
            note = await message.answer(
                f"⚠️ 检测到新号（首次出现 {age_days:.1f} 天，要求 {min_days} 天）。"
                f"已限制发言，请联系管理员验证。"
            )
            await asyncio.sleep(10)
            try:
                await note.delete()
            except Exception:
                pass
        except Exception as e:
            logger.warning("新号限制失败: %s", e)
        return True
    return False


async def handle_filters(message: Message, bot: Bot) -> bool:
    if not is_group(message) or not message.from_user or not message.text:
        return False
    cfg = await db.get_settings(message.chat.id)
    if not cfg.get("filter_enabled", True):
        return False
    if await is_admin(bot, message.chat.id, message.from_user.id) or await is_whitelisted(message.chat.id, message.from_user.id):
        return False
    blacklist = await db.fetchone("SELECT 1 FROM global_blacklist WHERE user_id=?", (message.from_user.id,))
    if blacklist:
        await bot.ban_chat_member(message.chat.id, message.from_user.id)
        await send_log(bot, message.chat.id, None, message.from_user.id, "global_blacklist_ban")
        return True

    # 新号限制
    if await check_new_account_restriction(message, bot):
        return True

    # 验证码检查
    captcha = await db.fetchone(
        "SELECT answer,created_at FROM captcha_store WHERE chat_id=? AND user_id=?",
        (message.chat.id, message.from_user.id),
    )
    if captcha:
        elapsed = now_ts() - int(captcha["created_at"])
        timeout = int(cfg.get("captcha_timeout", 60))
        if elapsed > timeout:
            await db.execute("DELETE FROM captcha_store WHERE chat_id=? AND user_id=?", (message.chat.id, message.from_user.id))
            try:
                await bot.ban_chat_member(message.chat.id, message.from_user.id)
                await bot.unban_chat_member(message.chat.id, message.from_user.id, only_if_banned=True)
            except Exception:
                pass
            await send_log(bot, message.chat.id, None, message.from_user.id, "captcha_timeout_kick")
            return True
        if message.text.strip() == str(captcha["answer"]):
            await db.execute("DELETE FROM captcha_store WHERE chat_id=? AND user_id=?", (message.chat.id, message.from_user.id))
            await message.reply("✅ 验证通过，可以正常发言。")
            return False
        try:
            await message.delete()
        except Exception:
            pass
        return True

    lower = message.text.lower()
    words = await db.fetchall("SELECT word,kind FROM word_filters WHERE chat_id=?", (message.chat.id,))
    for row in words:
        word = row["word"].lower()
        if row["kind"] == "keyword" and word and word in lower:
            await message.delete()
            await db.execute(
                "INSERT INTO memberships(chat_id,user_id,warns) VALUES(?,?,1) ON CONFLICT(chat_id,user_id) DO UPDATE SET warns=warns+1",
                (message.chat.id, message.from_user.id),
            )
            await send_log(bot, message.chat.id, None, message.from_user.id, "keyword_delete", word)
            return True
        if row["kind"] == "domain" and word and word in normalize_domain(lower):
            await message.delete()
            await send_log(bot, message.chat.id, None, message.from_user.id, "domain_delete", word)
            return True

    # 禁止转发特定频道消息
    is_forwarded = bool(
        getattr(message, "forward_origin", None)
        or getattr(message, "forward_from_chat", None)
        or getattr(message, "forward_from", None)
    )
    block_channels: list[int] = cfg.get("block_forward_channels", [])
    if is_forwarded and block_channels:
        fwd_chat_id = None
        if getattr(message, "forward_from_chat", None):
            fwd_chat_id = message.forward_from_chat.id
        elif getattr(message, "forward_origin", None):
            origin = message.forward_origin
            if hasattr(origin, "chat") and origin.chat:
                fwd_chat_id = origin.chat.id
        if fwd_chat_id and fwd_chat_id in block_channels:
            await message.delete()
            await send_log(bot, message.chat.id, None, message.from_user.id, "blocked_forward", str(fwd_chat_id))
            return True

    # Silent 模式审核
    member = await db.fetchone("SELECT silent_left FROM memberships WHERE chat_id=? AND user_id=?", (message.chat.id, message.from_user.id))
    if member and int(member["silent_left"] or 0) > 0:
        await db.execute(
            "UPDATE memberships SET silent_left=MAX(silent_left-1,0) WHERE chat_id=? AND user_id=?",
            (message.chat.id, message.from_user.id),
        )
        if contains_link(message.text) or is_forwarded:
            await message.delete()
            await send_log(bot, message.chat.id, None, message.from_user.id, "silent_review_delete")
            return True

    # 刷屏检测
    window = message_windows[(message.chat.id, message.from_user.id)]
    current = now_ts()
    window.append((current, lower))
    slow = int(cfg.get("slow_seconds", settings.default_slow_seconds))
    recent = [item for item in window if current - item[0] <= max(slow, 3)]
    repeated = len([item for item in recent if item[1] == lower]) >= 3
    too_fast = len(recent) >= 5
    if repeated or too_fast:
        await restrict_user(bot, message.chat.id, message.from_user.id, int(cfg.get("mute_seconds", settings.default_mute_seconds)), False)
        await send_log(bot, message.chat.id, None, message.from_user.id, "spam_mute", "重复消息或刷屏")
        await message.reply(f"⚠️ {user_label(message.from_user)} 疑似刷屏，已自动禁言。")
        return True
    return False


# ==================== 入群/离群 ====================


@router.message(F.new_chat_members)
async def new_member_handler(message: Message, bot: Bot) -> None:
    await ensure_context(message)
    cfg = await db.get_settings(message.chat.id)
    for user in message.new_chat_members or []:
        if user.id == bot.id:
            await message.answer("🤖 管理员机器人已加入本群。\n使用 /help 查看可用命令。")
            continue
        await db.upsert_user(user.id, user.username, user.full_name)
        await db.member_joined(message.chat.id, user.id, int(cfg.get("silent_messages", settings.default_silent_messages)))
        blacklist = await db.fetchone("SELECT 1 FROM global_blacklist WHERE user_id=?", (user.id,))
        if blacklist:
            await bot.ban_chat_member(message.chat.id, user.id)
            await send_log(bot, message.chat.id, None, user.id, "join_global_blacklist_ban")
            continue

        welcome = str(cfg.get("welcome_text", DEFAULT_CHAT_SETTINGS["welcome_text"])).format(name=user.mention_html())

        # 入群验证码
        if cfg.get("captcha_enabled", True):
            a, b = random.randint(1, 9), random.randint(1, 9)
            answer = a + b
            await db.execute(
                "INSERT OR REPLACE INTO captcha_store(chat_id,user_id,answer,created_at) VALUES(?,?,?,?)",
                (message.chat.id, user.id, answer, now_ts()),
            )
            welcome += f"\n\n🔐 入群验证：请在 60 秒内回复数字：{a}+{b}=?"

        # 新号限制检查
        min_days = int(cfg.get("new_account_min_days", 0))
        if min_days > 0:
            first_seen = await db.get_first_seen(user.id)
            if first_seen:
                age_days = (now_ts() - first_seen) / 86400
                if age_days < min_days:
                    await restrict_user(bot, message.chat.id, user.id, None, can_send=False)
                    welcome += f"\n\n⚠️ 检测到新号（首次出现 {age_days:.1f} 天，要求 {min_days} 天），已限制发言。"
                    await send_log(bot, message.chat.id, None, user.id, "new_account_restrict",
                                   f"age={age_days:.1f}d, min={min_days}d")

        # 检查是否有限制标记
        restricted = await db.fetchone(
            "SELECT reason FROM restricted_members WHERE chat_id=? AND user_id=?",
            (message.chat.id, user.id),
        )
        if restricted:
            welcome += f"\n\n⚠️ 你在群内被限制发言（原因：{restricted['reason'] or '无'}）。如有疑问请私聊机器人联系客服。"
            await restrict_user(bot, message.chat.id, user.id, None, can_send=False)

        # 发送欢迎消息（支持图片）
        media_id = int(cfg.get("welcome_media_id", 0))
        if media_id > 0:
            media = await db.get_media(media_id)
            if media:
                try:
                    await bot.send_photo(message.chat.id, media["file_id"], caption=welcome, parse_mode=ParseMode.HTML)
                except Exception:
                    await message.answer(welcome, parse_mode=ParseMode.HTML)
            else:
                await message.answer(welcome, parse_mode=ParseMode.HTML)
        else:
            await message.answer(welcome, parse_mode=ParseMode.HTML)

        await send_log(bot, message.chat.id, None, user.id, "join")


@router.message(F.left_chat_member)
async def left_member_handler(message: Message, bot: Bot) -> None:
    await ensure_context(message)
    user = message.left_chat_member
    if user:
        await db.member_left(message.chat.id, user.id)
        await db.execute("DELETE FROM captcha_store WHERE chat_id=? AND user_id=?", (message.chat.id, user.id))
        await send_log(bot, message.chat.id, None, user.id, "left")


# ==================== 私聊客服中转 ====================


@router.message(F.chat.type == ChatType.PRIVATE)
async def private_message_handler(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    if support_service:
        handled = await support_service.forward_user_message(message, bot)
        if handled:
            return
    await message.answer("你好，可以直接发消息联系客服。")


@router.callback_query()
async def callback_handler(callback: CallbackQuery, bot: Bot) -> None:
    if not callback.data or not callback.from_user:
        return
    if callback.from_user.id not in settings.support_admins and callback.from_user.id not in settings.super_admins:
        await callback.answer("无权限操作。", show_alert=True)
        return

    data = callback.data
    if data.startswith("support_ban_"):
        user_id = int(data.split("_")[-1])
        if support_service:
            await support_service.ban_user_from_support(user_id, "管理员封禁客服", 24)
            await callback.answer(f"已封禁用户 {user_id} 的客服权限 24 小时。")
        else:
            await callback.answer("客服服务未初始化。")
        return
    if data.startswith("support_close_"):
        user_id = int(data.split("_")[-1])
        if support_service:
            count = await support_service.close_thread(user_id)
            await callback.answer(f"已关闭用户 {user_id} 的 {count} 个会话。")
            try:
                await bot.send_message(user_id, "🔒 客服会话已结束。如需继续咨询请再次发送消息。")
            except Exception:
                pass
        else:
            await callback.answer("客服服务未初始化。")
        return
    if data.startswith("support_start"):
        await callback.answer("请直接发送消息。")
        return
    await callback.answer()


# ==================== 消息总入口 ====================


@router.message()
async def all_messages_handler(message: Message, bot: Bot) -> None:
    await ensure_context(message)
    if message.from_user and is_group(message):
        await db.incr_message(message.chat.id, message.from_user.id)
    if message.text:
        if await handle_ledger_text(message, bot):
            return
        if await handle_filters(message, bot):
            return


# ==================== 定时任务 ====================


async def scheduled_auto_publish() -> None:
    if channel_manager:
        count = await channel_manager.auto_publish_scheduled_posts()
        if count:
            logger.info("自动发布了 %d 条定时帖子。", count)


async def scheduled_execute_msgs() -> None:
    if msg_executor:
        count = await msg_executor.execute_due()
        if count:
            logger.info("执行了 %d 条定时消息。", count)


async def scheduled_auto_clean_inactive() -> None:
    """自动清理不活跃成员。"""
    global bot_instance
    if not bot_instance:
        return
    chats = await db.fetchall("SELECT chat_id, settings FROM chats")
    count_total = 0
    for chat in chats:
        try:
            settings_json = chat["settings"]
            import json
            try:
                cfg = json.loads(settings_json or "{}")
            except json.JSONDecodeError:
                cfg = {}
            auto_clean_days = int(cfg.get("auto_clean_inactive_days", 0))
            inactive_days = int(cfg.get("inactive_days", 30))
            days = auto_clean_days or inactive_days
            if days <= 0:
                continue
            threshold = now_ts() - days * 86400
            rows = await db.fetchall(
                "SELECT user_id FROM memberships WHERE chat_id=? AND left_at IS NULL AND last_message_at IS NOT NULL AND last_message_at<?",
                (chat["chat_id"], threshold),
            )
            for r in rows:
                try:
                    await bot_instance.ban_chat_member(chat["chat_id"], r["user_id"])
                    await bot_instance.unban_chat_member(chat["chat_id"], r["user_id"], only_if_banned=True)
                    await db.member_left(chat["chat_id"], r["user_id"])
                    count_total += 1
                except Exception:
                    continue
                await asyncio.sleep(0.1)
        except Exception:
            continue
    if count_total:
        logger.info("自动清理了 %d 位不活跃成员。", count_total)


async def scheduled_expire_captcha() -> None:
    threshold = now_ts() - 120
    await db.execute("DELETE FROM captcha_store WHERE created_at<?", (threshold,))
    await db.execute("DELETE FROM support_forward_bans WHERE banned_until<?", (now_ts(),))


async def setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="启动"),
            BotCommand(command="help", description="查看帮助"),
            BotCommand(command="rules", description="查看群规"),
            BotCommand(command="adminlist", description="查看管理员"),
            BotCommand(command="warn", description="警告用户"),
            BotCommand(command="mute", description="禁言用户"),
            BotCommand(command="ban", description="封禁用户"),
            BotCommand(command="kick", description="踢出用户"),
            BotCommand(command="clean", description="清理消息"),
            BotCommand(command="stats", description="统计面板"),
            BotCommand(command="export", description="导出CSV"),
            BotCommand(command="rank", description="活跃榜"),
            BotCommand(command="quietest", description="最安静用户"),
        ]
    )


# ==================== 入口 ====================


async def main() -> None:
    global support_service, channel_manager, msg_executor, bot_instance

    if not settings.bot_token:
        raise RuntimeError("请先复制 .env.example 为 .env，并填写 BOT_TOKEN。")

    await db.connect()
    bot = Bot(settings.bot_token)
    bot_instance = bot  # 用于 APScheduler 定时任务
    await setup_commands(bot)

    support_service = SupportService(db, settings.support_admins or settings.super_admins)
    channel_manager = ChannelManager(db, bot)
    msg_executor = ScheduledMessageExecutor(db, bot)

    scheduler.add_job(scheduled_auto_publish, "interval", minutes=1, id="auto_publish")
    scheduler.add_job(scheduled_execute_msgs, "interval", minutes=1, id="execute_msgs")
    scheduler.add_job(scheduled_auto_clean_inactive, "interval", hours=6, id="auto_clean_inactive")
    scheduler.add_job(scheduled_expire_captcha, "interval", minutes=5, id="expire_cleanup")
    scheduler.start()

    import os
    # Serv00 等环境不支持外网访问 Web 后台，可通过 DISABLE_WEB=1 关闭
    if not os.getenv("DISABLE_WEB"):
        from .web import create_web_app
        web_app = create_web_app(db, settings.super_admins)
        web_port = int(os.getenv("WEB_PORT", "8080"))
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", web_port)
        await site.start()
        logger.info("Web 管理后台已启动：http://0.0.0.0:%d", web_port)
    else:
        logger.info("Web 管理后台已关闭（DISABLE_WEB=1）")
        runner = None

    try:
        await dp.start_polling(bot)
    finally:
        if runner:
            await runner.cleanup()
        await db.close()
        await bot.session.close()


# 全局 bot 引用，供 APScheduler 使用
bot_instance: Bot | None = None

if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    asyncio.run(main())