from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# 免费汇率 API，无需 key
_EXCHANGE_API_URLS = [
    "https://api.exchangerate-api.com/v4/latest/{base}",
    "https://open.er-api.com/v6/latest/{base}",
]

_rate_cache: dict[str, dict[str, float]] = {}
_cache_ttl: int = 0


async def fetch_live_rates(base: str = "USD", timeout: float = 10.0) -> dict[str, float]:
    """从外部 API 获取实时汇率，带简单内存缓存（5 分钟）。"""
    import time
    global _rate_cache, _cache_ttl

    now = int(time.time())
    if _rate_cache.get(base) and now < _cache_ttl:
        return _rate_cache[base]

    for url_tpl in _EXCHANGE_API_URLS:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(url_tpl.format(base=base.upper())) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        rates = data.get("rates", {})
                        if rates:
                            _rate_cache[base] = rates
                            _cache_ttl = now + 300  # 5 分钟缓存
                            return rates
        except Exception as e:
            logger.warning("汇率 API 请求失败 (%s): %s", url_tpl, e)
            continue

    return {}


async def get_rate(pair: str, fallback: float = 7.2) -> float:
    """获取指定货币对的汇率，例如 'CNY' 返回 USD→CNY。"""
    rates = await fetch_live_rates()
    if not rates:
        return fallback
    return rates.get(pair.upper(), fallback)


def get_cached_rate(pair: str, fallback: float = 7.2) -> float:
    """同步获取缓存汇率，用于快速响应。"""
    base_rates = _rate_cache.get("USD", {})
    return base_rates.get(pair.upper(), fallback)
