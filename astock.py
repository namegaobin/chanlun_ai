"""A 股行情获取模块（astock）

本模块的唯一职责：
- 通过腾讯财经 API（日/周/月K线）和新浪财经 API（分钟K线）获取 A 股历史 K 线数据
- 将返回结果转换为与 Binance 模块兼容的 Python 字典列表结构

数据源：
- 日线/周线/月线：腾讯财经 (web.ifzq.gtimg.cn)
- 分钟线：新浪财经 (money.finance.sina.com.cn)

约束说明：
- 仅支持 A 股（沪深北交易所）
- 仅支持历史数据，不做实时推送
- 不做任何技术分析或衍生字段计算
- 返回结果包含真实的成交量（volume）
- 所有价格字段统一转换为 float 类型
- 时间字段统一转换为 Python datetime 对象
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx


# 简单的内存缓存
_cache: dict = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry is None:
        return None
    data, timestamp, ttl = entry
    if datetime.now().timestamp() - timestamp < ttl:
        return data
    if key in _cache:
        del _cache[key]
    return None


def _cache_set(key: str, data, ttl: int = 60):
    _cache[key] = (data, datetime.now().timestamp(), ttl)


# HTTP 客户端单例
_http_client: Optional[httpx.Client] = None


def _get_client() -> httpx.Client:
    """获取或创建 HTTP 客户端（支持代理）"""
    global _http_client
    # 每次都重新创建客户端，确保使用最新的代理设置
    import os
    proxy = os.environ.get('http_proxy') or os.environ.get('https_proxy')
    _http_client = httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        trust_env=True,
        proxies=proxy if proxy else None,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.qq.com/',
            'Accept': '*/*',
        }
    )
    return _http_client


def normalize_stock_code(code: str) -> tuple:
    """规范化股票代码，返回 (code, exchange)
       sz=深圳, sh=上海, bj=北交所
    """
    code = code.strip().zfill(6)
    if code.startswith(('00', '30', '002', '003')):
        return code, "sz"
    elif code.startswith(('60', '68', '500', '501')):
        return code, "sh"
    elif code.startswith('8') or code.startswith('4'):
        return code, "bj"
    return code, "sz"


def _get_qq_market_code(code: str) -> str:
    """获取腾讯 API 的市场前缀"""
    code = code.strip().zfill(6)
    if code.startswith(('00', '30', '002', '003')):
        return "sz"
    elif code.startswith(('60', '68', '500', '501')):
        return "sh"
    elif code.startswith('8') or code.startswith('4'):
        return "bj"
    return "sz"


# 前端 interval -> A 股 period 映射
INTERVAL_PERIOD_MAP = {
    "15m": "15",
    "60m": "60",
    "1d": "daily",
    "1w": "weekly",
    "1M": "monthly",
}

# A 股 period -> 缠论频率映射
PERIOD_FREQUENCY_MAP = {
    "15": "15m",
    "60": "60m",
    "daily": "1440m",
    "weekly": "1440m",
    "monthly": "1440m",
}


def _get_daily_kline_qq(sym: str, mkt: str, period_qq: str, adjust: str, limit: int) -> List[Dict]:
    """通过腾讯 API 获取日/周/月 K 线"""
    adjust_suffix = adjust if adjust else ""
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?_var=kline_{period_qq}{adjust_suffix}"
        f"&param={mkt}{sym},{period_qq},,,{limit},{adjust_suffix}"
    )
    client = _get_client()
    resp = client.get(url)
    text = resp.text

    json_match = re.search(r'=({.+})', text)
    if not json_match:
        return []

    data = __import__('json').loads(json_match.group(1))
    key = f"{mkt}{sym}"

    if key not in data.get("data", {}):
        return []

    data_key = f"{period_qq}{adjust_suffix}" if adjust_suffix else period_qq
    klines = data["data"][key].get(data_key, [])

    if not klines:
        for k in [f"qfq{period_qq}", f"{period_qq}qfq", period_qq, "day", "qfqday"]:
            if k in data["data"][key]:
                klines = data["data"][key][k]
                break

    if not klines:
        return []

    records = []
    for kl in klines:
        if len(kl) >= 6:
            try:
                records.append({
                    "date_str": kl[0],
                    "open": float(kl[1]),
                    "close": float(kl[2]),
                    "high": float(kl[3]),
                    "low": float(kl[4]),
                    "volume": float(kl[5]),
                })
            except (ValueError, IndexError):
                continue
    return records


def _get_minute_kline_sina(sym: str, mkt: str, period: str, limit: int) -> List[Dict]:
    """通过新浪 API 获取分钟 K 线"""
    sina_code = f"{mkt}{sym}"
    scale_map = {"5": 5, "15": 15, "30": 30, "60": 60}
    scale = scale_map.get(period, 30)

    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
        f"/CN_MarketData.getKLineData"
        f"?symbol={sina_code}&scale={scale}&ma=no&datalen={limit}"
    )

    client = _get_client()
    resp = client.get(url)
    data = resp.json()

    if not data or not isinstance(data, list):
        return []

    records = []
    for kl in data:
        try:
            records.append({
                "date_str": kl.get("day", ""),
                "open": float(kl.get("open", 0)),
                "close": float(kl.get("close", 0)),
                "high": float(kl.get("high", 0)),
                "low": float(kl.get("low", 0)),
                "volume": float(kl.get("volume", 0)),
            })
        except (ValueError, TypeError):
            continue
    return records


def get_klines(
    symbol: str,
    interval: str,
    limit: int = 500,
    adjust: str = "qfq",
    max_retries: int = 3
) -> List[Dict[str, Any]]:
    """获取 A 股历史 K 线数据

    参数：
    - symbol:   股票代码，如 "000001"、"600519" 或 "sz000001"
    - interval: K 线周期，支持 "15m"、"60m"、"1d"、"1w"、"1M"
    - limit:    返回的 K 线数量上限（默认 500）
    - adjust:   复权方式，"qfq"（前复权）、"hfq"（后复权）、""（不复权）
    - max_retries: 最大重试次数

    返回：
    - List[dict]，每个元素的结构：
      {
        "open_time": datetime,   # 开盘时间
        "open": float,           # 开盘价
        "high": float,           # 最高价
        "low": float,            # 最低价
        "close": float,          # 收盘价
        "close_time": datetime,  # 收盘时间（同 open_time）
        "volume": float,         # 成交量（股）
      }
    """
    # 缓存
    cache_key = f"astock:{symbol}:{interval}:{adjust}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # 规范化代码
    if '_' in symbol or '.' in symbol:
        # 支持 "sz000001" 或 "000001.SZ" 格式
        # 提取纯代码部分
        if '.' in symbol:
            # "000001.SZ" → "000001"
            sym = symbol.split('.')[0]
            mkt = symbol.split('.')[1].lower()
        elif '_' in symbol:
            # "sz_000001" → "000001"
            parts = symbol.split('_')
            sym = parts[1] if len(parts) > 1 else parts[0]
            mkt = parts[0].lower()
        sym, mkt = normalize_stock_code(sym)
    else:
        sym, mkt = normalize_stock_code(symbol)

    # 映射周期
    period = INTERVAL_PERIOD_MAP.get(interval)
    if not period:
        raise RuntimeError(f"不支持的 A 股周期: {interval}，支持: {list(INTERVAL_PERIOD_MAP.keys())}")

    # 获取数据
    records = []
    minute_periods = ["5", "15", "30", "60"]

    if period in minute_periods:
        records = _get_minute_kline_sina(sym, mkt, period, limit)
    else:
        period_qq_map = {"daily": "day", "weekly": "week", "monthly": "month"}
        period_qq = period_qq_map.get(period, "day")
        records = _get_daily_kline_qq(sym, mkt, period_qq, adjust, limit)

    if not records:
        raise RuntimeError(f"获取 A 股 K 线数据失败: {symbol} {interval}")

    # 转换为统一格式
    results: List[Dict[str, Any]] = []
    for rec in records:
        try:
            date_str = rec["date_str"]
            if period in minute_periods:
                # 分钟数据格式: "2024-01-15 09:35:00"
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            else:
                # 日/周/月数据格式: "2024-01-15"
                dt = datetime.strptime(date_str, "%Y-%m-%d")

            results.append({
                "open_time": dt,
                "open": rec["open"],
                "high": rec["high"],
                "low": rec["low"],
                "close": rec["close"],
                "close_time": dt,
                "volume": rec["volume"],
            })
        except (ValueError, KeyError):
            continue

    # 按 open_time 升序排序
    results.sort(key=lambda x: x["open_time"])

    # 缓存
    ttl = 60 if period in minute_periods else 300
    _cache_set(cache_key, results, ttl=ttl)

    return results
