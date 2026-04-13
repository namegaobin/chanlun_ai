"""黄金（XAUUSD）行情获取模块（gold）

本模块的唯一职责：
- 通过 yfinance 库获取黄金期货（GC=F）历史 K 线数据
- 将返回结果转换为与 Binance/A 股模块兼容的 Python 字典列表结构

约束说明：
- 使用黄金期货代码 "GC=F" 作为数据源（纽约商品交易所 COMEX 黄金期货）
- 仅支持历史数据，不提供实时推送
- 不做任何技术分析或衍生字段计算
- 返回结果不包含成交量（volume 设为 0）
- 所有价格字段统一转换为 float 类型
- 时间字段统一转换为 Python datetime 对象（UTC 时区）
- 实现磁盘缓存以避免 yfinance 速率限制
"""
from __future__ import annotations

import os
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

import yfinance as yf
import pandas as pd

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 缓存目录
CACHE_DIR = Path(__file__).parent / ".cache" / "gold"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 黄金期货代码（yfinance 格式）
GOLD_SYMBOL = "GC=F"

# 前端 interval -> yfinance interval 映射
INTERVAL_MAP = {
    "15m": "15m",
    "1h": "1h", 
    "4h": "4h",
    "1d": "1d",
    "1w": "1wk",
    "1M": "1mo",
}

# 缓存有效期（秒）
CACHE_TTL = {
    "15m": 300,      # 5分钟
    "1h": 1800,      # 30分钟
    "4h": 3600,      # 1小时
    "1d": 86400,     # 1天
    "1w": 604800,    # 1周
    "1M": 2592000,   # 30天
}


def _get_cache_key(symbol: str, interval: str, limit: int) -> str:
    """生成缓存键"""
    return f"{symbol}_{interval}_{limit}"


def _load_from_cache(cache_key: str, ttl: int) -> Optional[List[Dict[str, Any]]]:
    """从缓存加载数据"""
    cache_file = CACHE_DIR / f"{cache_key}.json"
    if not cache_file.exists():
        return None
    
    try:
        stat = cache_file.stat()
        if time.time() - stat.st_mtime > ttl:
            return None
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 将字符串时间转换回 datetime 对象
        results = []
        for item in data:
            item["open_time"] = datetime.fromisoformat(item["open_time"])
            item["close_time"] = datetime.fromisoformat(item["close_time"])
            results.append(item)
        
        logger.info(f"从缓存加载黄金数据: {cache_key}")
        return results
    except Exception as e:
        logger.warning(f"加载缓存失败 {cache_key}: {e}")
        return None


def _save_to_cache(cache_key: str, data: List[Dict[str, Any]]):
    """保存数据到缓存"""
    try:
        # 将 datetime 对象转换为字符串以便 JSON 序列化
        serializable_data = []
        for item in data:
            item_copy = item.copy()
            item_copy["open_time"] = item["open_time"].isoformat()
            item_copy["close_time"] = item["close_time"].isoformat()
            serializable_data.append(item_copy)
        
        cache_file = CACHE_DIR / f"{cache_key}.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(serializable_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"黄金数据已缓存: {cache_key}")
    except Exception as e:
        logger.warning(f"保存缓存失败 {cache_key}: {e}")


def get_klines(
    symbol: str = GOLD_SYMBOL,
    interval: str = "1h",
    limit: int = 500,
    max_retries: int = 3
) -> List[Dict[str, Any]]:
    """获取黄金历史 K 线数据

    参数：
    - symbol:   交易对名称，仅支持 "GC=F"（黄金期货）
    - interval: K 线周期，支持 "15m"、"1h"、"4h"、"1d"、"1w"、"1M"
    - limit:    返回的 K 线数量上限（默认 500）
    - max_retries: 最大重试次数

    返回：
    - List[dict]，每个元素的结构：
      {
        "open_time": datetime,   # 开盘时间（UTC）
        "open": float,           # 开盘价
        "high": float,           # 最高价
        "low": float,            # 最低价
        "close": float,          # 收盘价
        "close_time": datetime,  # 收盘时间（UTC）
      }
    
    注意：
    - 成交量（volume）始终为 0（黄金期货无公开成交量数据）
    - 使用 yfinance 下载数据，可能会遇到速率限制
    - 实现磁盘缓存以避免频繁请求
    """
    # 目前只支持黄金期货
    if symbol != GOLD_SYMBOL:
        raise ValueError(f"不支持的黄金代码: {symbol}，目前只支持 {GOLD_SYMBOL}")
    
    # 映射周期
    yf_interval = INTERVAL_MAP.get(interval)
    if not yf_interval:
        raise ValueError(f"不支持的黄金周期: {interval}，支持: {list(INTERVAL_MAP.keys())}")
    
    # 检查缓存
    cache_key = _get_cache_key(symbol, interval, limit)
    ttl = CACHE_TTL.get(interval, 3600)
    cached = _load_from_cache(cache_key, ttl)
    if cached is not None:
        return cached
    
    # 根据周期确定下载时间段
    # yfinance 的 period 参数
    period_map = {
        "15m": "7d",
        "1h": "1mo",
        "4h": "3mo",
        "1d": "1y",
        "1wk": "5y",
        "1mo": "10y",
    }
    period = period_map.get(yf_interval, "1mo")
    
    # 重试下载
    last_error = None
    for attempt in range(max_retries):
        try:
            logger.info(f"下载黄金数据: {symbol} {interval} (尝试 {attempt + 1}/{max_retries})")
            
            # 避免速率限制，在重试之间等待
            if attempt > 0:
                wait_time = 2 ** attempt  # 指数退避
                logger.info(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
            
            # 下载数据
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=yf_interval)
            
            if df.empty:
                raise RuntimeError(f"yfinance 返回空数据: {symbol} {interval}")
            
            # 转换为所需格式
            results: List[Dict[str, Any]] = []
            for idx, row in df.iterrows():
                # idx 是 pandas Timestamp，转换为 datetime
                dt = idx.to_pydatetime()
                # 确保时区为 UTC
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)
                
                results.append({
                    "open_time": dt,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "close_time": dt,
                })
            
            # 按时间升序排序（yfinance 返回的是降序）
            results.sort(key=lambda x: x["open_time"])
            
            # 限制数量
            if len(results) > limit:
                results = results[-limit:]
            
            # 保存到缓存
            _save_to_cache(cache_key, results)
            
            logger.info(f"成功获取黄金数据: {len(results)} 条K线")
            return results
            
        except Exception as e:
            last_error = e
            logger.warning(f"下载黄金数据失败 (尝试 {attempt + 1}/{max_retries}): {e}")
    
    # 所有重试都失败，尝试返回缓存中的旧数据
    stale_cache = _load_from_cache(cache_key, ttl * 10)  # 放宽TTL
    if stale_cache:
        logger.warning(f"使用过期的缓存数据: {cache_key}")
        return stale_cache
    
    raise RuntimeError(f"获取黄金 K 线数据失败（已重试{max_retries}次）: {last_error}")