"""黄金实时价格获取模块（gold_realtime）

本模块的唯一职责：
- 通过多个数据源获取 XAUUSD（黄金现货）的实时价格
- 将返回结果统一为 Python 字典格式，包含价格、时间戳、数据源等信息

约束说明：
- 支持多种数据源，按优先级顺序尝试，直到获取成功
- 实现磁盘缓存以避免频繁请求和数据源速率限制
- 不依赖项目内其他模块，仅依赖标准库与 requests、yfinance（可选）
"""

from __future__ import annotations

import os
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import logging
import hashlib

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 缓存目录
CACHE_DIR = Path(__file__).parent / ".cache" / "gold_realtime"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 缓存有效期（秒）
PRICE_CACHE_TTL = 60  # 1分钟，避免频繁请求

# 数据源配置
SOURCES = [
    {
        "name": "yfinance",
        "symbol": "GC=F",  # COMEX 黄金期货
        "enabled": YFINANCE_AVAILABLE,
        "description": "Yahoo Finance 黄金期货价格（美元/盎司）"
    },
    {
        "name": "xxapi_gold",
        "url": "https://v2.xxapi.cn/api/goldprice",
        "enabled": REQUESTS_AVAILABLE,
        "description": "xxapi.cn 国内金价（人民币/克），需转换为美元/盎司"
    }
]


def _get_cache_key(source_name: str, symbol_or_url: str) -> str:
    """生成缓存键"""
    key_str = f"{source_name}_{symbol_or_url}"
    return hashlib.md5(key_str.encode()).hexdigest()[:16]


def _load_from_cache(cache_key: str, ttl: int) -> Optional[Dict[str, Any]]:
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
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        
        logger.debug(f"从缓存加载黄金价格数据: {cache_key}")
        return data
    except Exception as e:
        logger.warning(f"加载缓存失败 {cache_key}: {e}")
        return None


def _save_to_cache(cache_key: str, data: Dict[str, Any]):
    """保存数据到缓存"""
    try:
        # 将 datetime 对象转换为字符串以便 JSON 序列化
        serializable_data = data.copy()
        if "timestamp" in serializable_data and isinstance(serializable_data["timestamp"], datetime):
            serializable_data["timestamp"] = serializable_data["timestamp"].isoformat()
        
        cache_file = CACHE_DIR / f"{cache_key}.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(serializable_data, f, ensure_ascii=False, indent=2)
        
        logger.debug(f"黄金价格数据已缓存: {cache_key}")
    except Exception as e:
        logger.warning(f"保存缓存失败 {cache_key}: {e}")


def _fetch_yfinance_price(symbol: str, max_retries: int = 3) -> Optional[Dict[str, Any]]:
    """通过 yfinance 获取黄金价格（带重试机制）"""
    if not YFINANCE_AVAILABLE:
        logger.warning("yfinance 不可用，跳过")
        return None
    
    last_error = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                wait_time = 2 ** attempt  # 指数退避：2秒, 4秒, 8秒
                logger.info(f"yfinance 重试 {attempt}/{max_retries}，等待 {wait_time} 秒")
                time.sleep(wait_time)
            
            ticker = yf.Ticker(symbol)
            
            # 方法1：尝试从 info 获取实时价格
            info = ticker.info
            price = info.get('regularMarketPrice') or info.get('currentPrice')
            if price is not None:
                timestamp = datetime.fromtimestamp(
                    info.get('regularMarketTime', time.time()),
                    tz=timezone.utc
                )
                return {
                    "price": float(price),
                    "currency": "USD",
                    "unit": "ounce",
                    "timestamp": timestamp,
                    "source": "yfinance",
                    "symbol": symbol
                }
            
            # 方法2：获取最新历史数据
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                latest = hist.iloc[-1]
                price = float(latest['Close'])
                timestamp = latest.name.to_pydatetime()
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                else:
                    timestamp = timestamp.astimezone(timezone.utc)
                
                return {
                    "price": price,
                    "currency": "USD",
                    "unit": "ounce",
                    "timestamp": timestamp,
                    "source": "yfinance_history",
                    "symbol": symbol
                }
            
            logger.warning(f"yfinance 未返回有效价格数据: {symbol}")
            # 如果没有数据但也没有异常，则跳出重试循环
            break
                
        except Exception as e:
            last_error = e
            logger.warning(f"yfinance 获取价格失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            # 继续重试
    
    logger.error(f"yfinance 所有重试均失败: {last_error}")
    return None


def _fetch_xxapi_gold_price() -> Optional[Dict[str, Any]]:
    """通过 xxapi.cn 获取国内金价并转换为美元/盎司"""
    if not REQUESTS_AVAILABLE:
        logger.warning("requests 不可用，跳过")
        return None
    
    try:
        response = requests.get("https://v2.xxapi.cn/api/goldprice", timeout=10)
        if response.status_code != 200:
            logger.warning(f"xxapi.cn 请求失败，状态码: {response.status_code}")
            return None
        
        data = response.json()
        if data.get("code") != 200:
            logger.warning(f"xxapi.cn 返回错误: {data.get('msg')}")
            return None
        
        # 提取黄金回收价格（人民币/克）
        gold_recycle_items = data.get("data", {}).get("gold_recycle_price", [])
        gold_price_rmb_per_g = None
        
        for item in gold_recycle_items:
            if item.get("gold_type") == "黄金回收":
                price_str = item.get("recycle_price", "")
                try:
                    gold_price_rmb_per_g = float(price_str)
                    break
                except ValueError:
                    continue
        
        if gold_price_rmb_per_g is None:
            logger.warning("xxapi.cn 未找到黄金回收价格")
            return None
        
        # 转换为美元/盎司
        # 1. 获取美元兑人民币汇率（使用 yfinance 或固定汇率）
        usdcny_rate = _get_usd_cny_rate()
        if usdcny_rate is None:
            usdcny_rate = 7.0  # 默认汇率
        
        # 2. 转换：人民币/克 -> 美元/盎司
        # 1盎司 = 31.1035克
        gold_price_usd_per_ounce = gold_price_rmb_per_g * 31.1035 / usdcny_rate
        
        return {
            "price": gold_price_usd_per_ounce,
            "currency": "USD",
            "unit": "ounce",
            "timestamp": datetime.now(timezone.utc),
            "source": "xxapi_gold",
            "original_price_rmb_per_g": gold_price_rmb_per_g,
            "exchange_rate": usdcny_rate
        }
        
    except Exception as e:
        logger.warning(f"xxapi.cn 获取价格失败: {e}")
        return None


def _get_usd_cny_rate() -> Optional[float]:
    """获取美元兑人民币汇率"""
    if not YFINANCE_AVAILABLE:
        return None
    
    try:
        ticker = yf.Ticker("USDCNY=X")
        info = ticker.info
        rate = info.get('regularMarketPrice') or info.get('currentPrice')
        if rate is not None:
            return float(rate)
        
        # 尝试历史数据
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist.iloc[-1]['Close'])
        
        return None
    except Exception as e:
        logger.warning(f"获取汇率失败: {e}")
        return None


def get_realtime_price(
    preferred_source: str = None,
    max_retries: int = 2
) -> Dict[str, Any]:
    """获取黄金实时价格
    
    参数：
    - preferred_source: 优先使用的数据源名称，如 "yfinance"、"xxapi_gold"
    - max_retries: 每个数据源的最大重试次数
    
    返回：
    - Dict[str, Any]，结构：
      {
        "success": bool,           # 是否成功获取价格
        "price": float | None,     # 价格（美元/盎司）
        "currency": str | None,    # 货币（"USD"）
        "unit": str | None,        # 单位（"ounce"）
        "timestamp": datetime | None,  # 时间戳（UTC）
        "source": str | None,      # 数据源名称
        "error": str | None,       # 错误信息（如果 success=False）
        "cached": bool,            # 是否为缓存数据
      }
    """
    
    # 确定要尝试的数据源顺序
    sources_to_try = []
    if preferred_source:
        for source in SOURCES:
            if source["name"] == preferred_source and source["enabled"]:
                sources_to_try.append(source)
                break
    
    # 添加其他可用的数据源
    for source in SOURCES:
        if source["enabled"] and source not in sources_to_try:
            sources_to_try.append(source)
    
    if not sources_to_try:
        return {
            "success": False,
            "error": "没有可用的数据源",
            "price": None,
            "currency": None,
            "unit": None,
            "timestamp": None,
            "source": None,
            "cached": False
        }
    
    # 按顺序尝试数据源
    last_error = None
    for source_config in sources_to_try:
        source_name = source_config["name"]
        
        # 检查缓存
        cache_key = _get_cache_key(source_name, source_config.get("symbol", source_config.get("url", "")))
        cached = _load_from_cache(cache_key, PRICE_CACHE_TTL)
        if cached is not None:
            logger.info(f"使用缓存数据: {source_name}")
            cached["cached"] = True
            cached["success"] = True
            return cached
        
        logger.info(f"尝试从 {source_name} 获取黄金实时价格")
        
        # 根据数据源类型调用相应的获取函数
        result = None
        if source_name == "yfinance":
            result = _fetch_yfinance_price(source_config["symbol"], max_retries=2)
        elif source_name == "xxapi_gold":
            result = _fetch_xxapi_gold_price()
        
        if result is not None:
            # 保存到缓存
            _save_to_cache(cache_key, result)
            
            # 返回成功结果
            result.update({
                "success": True,
                "cached": False
            })
            return result
        
        # 当前数据源失败，记录错误
        error_msg = f"数据源 {source_name} 未返回有效数据"
        logger.warning(error_msg)
        last_error = error_msg
        
        # 重试前等待
        if max_retries > 0:
            time.sleep(1)
    
    # 所有数据源都失败，尝试返回缓存中的旧数据（放宽TTL）
    for source_config in sources_to_try:
        source_name = source_config["name"]
        cache_key = _get_cache_key(source_name, source_config.get("symbol", source_config.get("url", "")))
        stale_cache = _load_from_cache(cache_key, PRICE_CACHE_TTL * 10)  # 放宽TTL为10倍
        if stale_cache:
            logger.warning(f"使用过期的缓存数据: {source_name}")
            stale_cache["cached"] = True
            stale_cache["success"] = True
            return stale_cache
    
    # 完全失败
    return {
        "success": False,
        "error": f"所有数据源都失败，最后错误: {last_error}",
        "price": None,
        "currency": None,
        "unit": None,
        "timestamp": None,
        "source": None,
        "cached": False
    }


# 测试代码
if __name__ == "__main__":
    print("测试黄金实时价格获取...")
    
    # 测试 yfinance
    print("\n1. 使用 yfinance:")
    result = get_realtime_price("yfinance")
    print(json.dumps(result, indent=2, default=str))
    
    # 测试 xxapi_gold
    print("\n2. 使用 xxapi_gold:")
    result = get_realtime_price("xxapi_gold")
    print(json.dumps(result, indent=2, default=str))
    
    # 测试自动选择
    print("\n3. 自动选择数据源:")
    result = get_realtime_price()
    print(json.dumps(result, indent=2, default=str))