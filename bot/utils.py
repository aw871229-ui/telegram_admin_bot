from __future__ import annotations

import ast
import operator
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram.types import Message, User


TIME_RE = re.compile(r"^(\d+)([mhd])?$", re.I)
EXPR_RE = re.compile(r"^\s*-?\d+(\.\d+)?\s*[+\-*/]\s*-?\d+(\.\d+)?\s*$")


def now_ts() -> int:
    return int(time.time())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_duration(text: str | None, default_seconds: int | None = None) -> int | None:
    if not text:
        return default_seconds
    text = text.strip().lower()
    if text in {"永久", "forever", "permanent", "perm", "0"}:
        return None
    match = TIME_RE.match(text)
    if not match:
        return default_seconds
    value = int(match.group(1))
    unit = match.group(2) or "m"
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    if unit == "d":
        return value * 86400
    return default_seconds


def until_date_from_seconds(seconds: int | None) -> datetime | None:
    if seconds is None:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def user_label(user: User | None) -> str:
    if not user:
        return "未知用户"
    name = user.full_name or user.username or str(user.id)
    if user.username:
        return f"{name} (@{user.username}, {user.id})"
    return f"{name} ({user.id})"


async def resolve_target_user_id(message: Message) -> int | None:
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    parts = (message.text or "").split()
    if len(parts) >= 2:
        raw = parts[1].strip()
        if raw.startswith("@"):
            return None
        if raw.lstrip("-").isdigit():
            return int(raw)
    return None


def command_args(message: Message) -> list[str]:
    text = message.text or ""
    parts = text.split()
    return parts[1:]


def safe_calculate(expr: str) -> float | None:
    if not EXPR_RE.match(expr):
        return None
    allowed: dict[type[Any], Any] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
            return allowed[type(node.op)](eval_node(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in allowed:
            right = eval_node(node.right)
            if isinstance(node.op, ast.Div) and right == 0:
                raise ZeroDivisionError
            return allowed[type(node.op)](eval_node(node.left), right)
        raise ValueError("不支持的表达式")

    try:
        return round(eval_node(ast.parse(expr, mode="eval")), 8)
    except Exception:
        return None


def contains_link(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("http://", "https://", "t.me/", "telegram.me/", "www."))


def normalize_domain(text: str) -> str:
    return text.lower().replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
