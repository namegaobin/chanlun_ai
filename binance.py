"""Binance 行情获取模块（binance）

本模块的唯一职责：
- 通过 Binance 官方 REST API 获取现货历史 K 线数据（/api/v3/klines）
- 将返回结果转换为统一的 Python 字典列表结构，便于后续模块使用

约束说明：
- 仅支持现货（spot）行情，不处理合约等其他市场。
- 仅支持历史数据，不使用 WebSocket，也不做实时推送。
- 不做任何技术分析或衍生字段计算，只做字段映射与类型转换。
- 不做任何数据裁剪：返回 Binance 接口返回的全部记录。
- 返回结果按时间升序排列（如上游已升序，排序不会改变顺序）。
- 所有价格字段统一转换为 float 类型。
- 时间字段统一转换为 Python datetime 对象（UTC 时区）。
- 不依赖项目内其他模块，仅依赖标准库与 requests。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List
import time

import requests

# Binance REST API 基础地址
_BASE_URL = "https://api.binance.com"

# 现货 K 线接口路径（官方文档：/api/v3/klines）
_KLINES_PATH = "/api/v3/klines"

# 代理配置（从环境变量读取，支持国内访问）
_PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

# 代理设置
_PROXIES = {"http": _PROXY, "https": _PROXY} if _PROXY else None


def get_klines(symbol: str, interval: str, limit: int, start_time: int = None, max_retries: int = 3) -> List[Dict[str, Any]]:
    """从 Binance 获取指定交易对与周期的历史 K 线数据

    参数：
    - symbol:     交易对名称，例如 "BTCUSDT"（注意：现货不带斜杠）。
    - interval:   K 线周期，例如 "1m"、"5m"、"15m"、"1h"、"4h"、"1d" 等。
    - limit:      返回的 K 线数量上限（支持超过1000，自动分批获取）。
    - start_time: 开始时间（毫秒时间戳），可选。如果提供，将从该时间开始获取 K 线。
    - max_retries: 最大重试次数，默认 3 次。

    返回：
    - List[dict]，每个元素的结构严格为：
      {
        "open_time": datetime,   # 开盘时间（UTC）
        "open": float,           # 开盘价
        "high": float,           # 最高价
        "low": float,            # 最低价
        "close": float,          # 收盘价
        "close_time": datetime,  # 收盘时间（UTC）
      }

    行为约束：
    - 使用 requests 访问 Binance REST API；
    - 自动重试网络错误（最多 max_retries 次）；
    - 不做任何技术分析；
    - 不做任何数据裁剪（完全返回接口数据）；
    - 返回结果按时间升序排列；
    - 所有数值字段转换为 float，时间字段转换为 datetime；
    - 如接口返回异常或格式不符合预期，将抛出 RuntimeError 或 requests 相关异常。
    """

    # Binance 单次最多返回1000根，超过时需分批获取
    BATCH_SIZE = 1000
    all_results: List[Dict[str, Any]] = []
    remaining = limit
    current_start_time = start_time

    while remaining > 0:
        batch_limit = min(remaining, BATCH_SIZE)
        batch = _fetch_klines_batch(symbol, interval, batch_limit, current_start_time, max_retries)
        if not batch:
            break
        all_results.extend(batch)
        remaining -= len(batch)
        # 下一批从最后一根K线的 open_time 之后开始
        current_start_time = int(batch[-1]["open_time"].timestamp() * 1000) + 1
        if len(batch) < batch_limit:
            break  # 已无更多数据

    # 按时间升序排序
    all_results.sort(key=lambda x: x["open_time"])
    return all_results


def _fetch_klines_batch(symbol: str, interval: str, limit: int, 
                         start_time: int = None, max_retries: int = 3) -> List[Dict[str, Any]]:
    """单次从 Binance 获取最多1000根K线"""
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": min(limit, 1000),
    }
    
    if start_time is not None:
        params["startTime"] = int(start_time)

    # 重试机制
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                _BASE_URL + _KLINES_PATH,
                params=params,
                timeout=15,
                proxies=_PROXIES,
            )
            
            if not resp.ok:
                raise RuntimeError(
                    f"请求 Binance K 线数据失败，HTTP 状态码 {resp.status_code}，响应内容：{resp.text}"
                )

            try:
                data = resp.json()
            except ValueError as exc:
                raise RuntimeError(f"Binance K 线接口返回的不是合法 JSON：{resp.text}") from exc

            if not isinstance(data, list):
                raise RuntimeError(f"Binance K 线接口返回格式异常，预期为列表，实际为：{data}")

            # 成功获取数据，跳出重试循环
            break
            
        except requests.exceptions.SSLError as exc:
            last_error = exc
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            else:
                raise RuntimeError(f"请求 Binance K 线数据失败（SSL错误，已重试{max_retries}次）：{exc}") from exc
                
        except requests.RequestException as exc:
            last_error = exc
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            else:
                raise RuntimeError(f"请求 Binance K 线数据失败（网络错误，已重试{max_retries}次）：{exc}") from exc
    else:
        raise RuntimeError(f"请求 Binance K 线数据失败（已重试{max_retries}次）")

    results: List[Dict[str, Any]] = []
    for item in data:
        if not (isinstance(item, (list, tuple)) and len(item) >= 7):
            raise RuntimeError(f"Binance 返回的 K 线子项格式异常：{item}")

        open_time_ms = int(item[0])
        open_price = float(item[1])
        high_price = float(item[2])
        low_price = float(item[3])
        close_price = float(item[4])
        close_time_ms = int(item[6])

        open_dt = datetime.fromtimestamp(open_time_ms / 1000.0, tz=timezone.utc)
        close_dt = datetime.fromtimestamp(close_time_ms / 1000.0, tz=timezone.utc)

        results.append({
            "open_time": open_dt,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "close_time": close_dt,
        })

    results.sort(key=lambda x: x["open_time"])
    return results
