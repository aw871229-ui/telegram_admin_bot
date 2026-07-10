from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def parse_ids(value: str | None) -> set[int]:
    if not value:
        return set()
    result: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            continue
    return result


@dataclass(frozen=True)
class Settings:
    bot_token: str
    super_admins: set[int]
    database_path: Path
    log_chat_id: int | None
    support_admins: set[int]
    private_mode: bool
    default_warn_limit: int
    default_mute_seconds: int
    default_slow_seconds: int
    default_silent_messages: int
    default_exchange_rate: float
    default_fee_rate: float


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    log_chat = os.getenv("LOG_CHAT_ID", "").strip()
    super_admins = parse_ids(os.getenv("SUPER_ADMINS"))
    support_admins = parse_ids(os.getenv("SUPPORT_ADMINS")) or super_admins
    private_mode = os.getenv("PRIVATE_MODE", "true").strip().lower() in {"true", "1", "yes"}
    database_path = Path(os.getenv("DATABASE_PATH", "data/bot.sqlite3"))
    if not database_path.is_absolute():
        database_path = ROOT_DIR / database_path
    return Settings(
        bot_token=token,
        super_admins=super_admins,
        database_path=database_path,
        log_chat_id=int(log_chat) if log_chat.lstrip("-").isdigit() else None,
        support_admins=support_admins,
        private_mode=private_mode,
        default_warn_limit=int(os.getenv("DEFAULT_WARN_LIMIT", "3")),
        default_mute_seconds=int(os.getenv("DEFAULT_MUTE_SECONDS", "3600")),
        default_slow_seconds=int(os.getenv("DEFAULT_SLOW_SECONDS", "5")),
        default_silent_messages=int(os.getenv("DEFAULT_SILENT_MESSAGES", "3")),
        default_exchange_rate=float(os.getenv("DEFAULT_EXCHANGE_RATE", "7.2")),
        default_fee_rate=float(os.getenv("DEFAULT_FEE_RATE", "0.05")),
    )


def ids_to_text(ids: Iterable[int]) -> str:
    return ",".join(str(i) for i in sorted(ids))
