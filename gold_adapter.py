"""黄金缠论适配模块（gold_adapter）

本模块的目标：
- 将来自 gold 模块的黄金 K 线数据，转换为缠论引擎可直接使用的 Bar/Kline 结构
- 与 binance_adapter 类似，成交量（a）字段始终设为 0

说明：
- 不进行任何缠论计算，仅做数据形状转换
- 不实现策略，仅返回 Bar 列表供后续缠论计算使用
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

Bar = Dict[str, Any]


@dataclass
class GoldBar:
    """黄金 K 线中间表示"""
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    close_time: datetime


def convert_to_chanlun_bars(klines: List[Dict[str, Any]]) -> List[Bar]:
    """将黄金 K 线数据转换为缠论引擎可用的 Bar 列表

    参数：
    - klines: 来自 gold 模块的 K 线列表，每个元素包含：
      {
        "open_time": datetime,
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "close_time": datetime,
      }

    返回：
    - List[Bar]，每个 Bar 的字段定义：
      {
        "date": datetime,
        "o": float,
        "h": float,
        "l": float,
        "c": float,
        "a": float,  # 成交量（黄金数据中始终为 0）
      }
    """
    if not klines:
        return []

    if not isinstance(klines, list):
        raise TypeError(f"klines 必须是列表类型，当前为: {type(klines)}")

    # 1. 解析并排序
    bars: List[GoldBar] = []
    for item in klines:
        if not isinstance(item, dict):
            raise TypeError(f"klines 中的元素必须是 dict，当前为: {type(item)}")
        
        # 提取字段
        open_time = item["open_time"]
        if not isinstance(open_time, datetime):
            try:
                open_time = datetime.strptime(str(open_time)[:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                open_time = datetime.fromisoformat(str(open_time).replace("Z", "+00:00"))
        
        close_time = item.get("close_time", open_time)
        if not isinstance(close_time, datetime):
            try:
                close_time = datetime.strptime(str(close_time)[:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                close_time = datetime.fromisoformat(str(close_time).replace("Z", "+00:00"))
        
        bars.append(GoldBar(
            open_time=open_time,
            open=float(item["open"]),
            high=float(item["high"]),
            low=float(item["low"]),
            close=float(item["close"]),
            close_time=close_time,
        ))

    # 2. 按时间升序排序
    bars.sort(key=lambda x: x.open_time)

    # 3. 转换为前端格式
    results: List[Bar] = []
    for bar in bars:
        results.append({
            "date": bar.open_time,
            "o": bar.open,
            "h": bar.high,
            "l": bar.low,
            "c": bar.close,
            "a": 0.0,  # 黄金数据无成交量
        })

    return results