"""A 股缠论适配模块（astock_adapter）

本模块的目标：
- 将来自 astock 模块的 A 股 K 线数据，转换为缠论引擎可直接使用的 Bar/Kline 结构
- 与 chanlun_adapter 的区别：利用 A 股数据自带的 volume 字段填充真实成交量

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
class AstockBar:
    """A 股 K 线中间表示"""
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    close_time: datetime
    volume: float


def convert_to_chanlun_bars(klines: List[Dict[str, Any]]) -> List[Bar]:
    """将 A 股 K 线数据转换为缠论引擎可用的 Bar 列表

    参数：
    - klines: 来自 astock 模块的 K 线列表，每个元素包含：
      {
        "open_time": datetime,
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "close_time": datetime,
        "volume": float,
      }

    返回：
    - List[Bar]，每个 Bar 的字段定义：
      {
        "date": datetime,
        "o": float,
        "h": float,
        "l": float,
        "c": float,
        "a": float,  # 真实成交量
      }
    """
    if not klines:
        return []

    if not isinstance(klines, list):
        raise TypeError(f"klines 必须是列表类型，当前为: {type(klines)}")

    # 1. 解析并排序
    bars: List[AstockBar] = []
    for item in klines:
        if not isinstance(item, dict):
            raise TypeError(f"klines 中的元素必须是 dict，当前为: {type(item)}")
        bars.append(AstockBar(
            open_time=item["open_time"] if isinstance(item["open_time"], datetime)
                else datetime.strptime(str(item["open_time"])[:19], "%Y-%m-%d %H:%M:%S"),
            open=float(item["open"]),
            high=float(item["high"]),
            low=float(item["low"]),
            close=float(item["close"]),
            close_time=item["close_time"] if isinstance(item["close_time"], datetime)
                else datetime.strptime(str(item["close_time"])[:19], "%Y-%m-%d %H:%M:%S"),
            volume=float(item.get("volume", 0)),
        ))

    bars.sort(key=lambda b: b.open_time)

    # 2. 映射为缠论 Bar（使用真实 volume）
    result: List[Bar] = []
    for b in bars:
        bar: Bar = {
            "date": b.open_time,
            "o": b.open,
            "h": b.high,
            "l": b.low,
            "c": b.close,
            "a": b.volume,  # 使用真实成交量
        }
        result.append(bar)

    return result
