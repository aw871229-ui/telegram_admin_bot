from __future__ import annotations

import csv
import io
import logging
from typing import Any

logger = logging.getLogger(__name__)


def export_logs_to_csv(rows: list[dict[str, Any]]) -> str:
    """将日志记录导出为 CSV 字符串。"""
    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "群ID", "操作者ID", "目标ID", "动作", "详情", "时间"])
    for r in rows:
        writer.writerow([
            r.get("id", ""),
            r.get("chat_id", ""),
            r.get("actor_id", ""),
            r.get("target_id", ""),
            r.get("action", ""),
            r.get("detail", ""),
            r.get("created_at", ""),
        ])
    return output.getvalue()


def export_ledger_to_csv(rows: list[dict[str, Any]]) -> str:
    """将记账记录导出为 CSV 字符串。"""
    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "群ID", "操作人ID", "类型", "金额", "汇率", "费率", "折算金额", "档案号", "备注", "时间"])
    for r in rows:
        writer.writerow([
            r.get("id", ""),
            r.get("chat_id", ""),
            r.get("user_id", ""),
            r.get("kind", ""),
            r.get("amount", ""),
            r.get("rate", ""),
            r.get("fee_rate", ""),
            r.get("final_amount", ""),
            r.get("archive_no", ""),
            r.get("note", ""),
            r.get("created_at", ""),
        ])
    return output.getvalue()
