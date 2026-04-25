#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论引擎回测系统 - 基于 chanClass.py

功能：
- 从 Binance 获取 BTC 1分钟 K线数据
- 通过 Chan_Class 多级别链表进行增量分析（30m → 5m → 1m）
- 基于买卖点信号进行模拟交易
- 复用 backtest_incremental.py 的交易引擎和报告生成

用法：
    python backtest_chanclass.py
    python backtest_chanclass.py -d 10
    python backtest_chanclass.py -e 2026-04-15
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# 复用 backtest_incremental.py 的组件
from backtest_incremental import (
    BacktestEngine,
    TradeRecord,
    BacktestStats,
    generate_report,
    BarAggregator,
    POSITION_SIZING,
    ENTRY_SIGNALS,
    REVERSE_CLOSE_SIGNALS,
    INITIAL_CAPITAL,
    WARMUP_BARS,
    FEE_RATE,
    SLIPPAGE,
    ENABLE_SHORT,
)

from chanlun_local.chanClass import Chan_Class, BarData, Exchange, Interval
from binance import get_klines


# ============================================================
# 常量定义（从 backtest_incremental.py 移除的常量）
# ============================================================

# 信号过滤阈值（缠论原文：买卖点只有有效/无效，无置信度概念）
MIN_CONFIDENCE = 0      # 已废弃，保留向后兼容
MIN_RISK_REWARD = 1.0   # 一类买卖点盈亏比要求（适中）
MIN_RISK_REWARD_2 = 1.0 # 二类买卖点盈亏比要求（放宽）
MIN_RISK_REWARD_3 = 1.0 # 三类买卖点盈亏比要求（与一类相同）
MIN_STOP_PCT = 0.008   # 最小止损百分比（0.8%）
MAX_STOP_PCT = 0.018   # 最大止损百分比（1.8%）


# ============================================================
# 信号类型映射
# ============================================================

CHAN_SIGNAL_MAP = {
    'B1': '1buy',
    'B2': '2buy',
    'B3': '3buy',
    'S1': '1sell',
    'S2': '2sell',
    'S3': '3sell',
}

STRENGTH_TO_CONFIDENCE = {
    '超强': 90,
    '强': 80,
    '中': 70,
    '弱': 55,
    None: 60,
}

# 信号类型的默认置信度（当strength为None时使用）
SIGNAL_TYPE_CONFIDENCE = {
    'B1': 80,  # 一买：趋势转折信号，置信度较高
    'B2': 70,  # 二买：确认信号
    'B3': 55,  # 三买：风险较大
    'S1': 80,  # 一卖：趋势转折信号
    'S2': 70,  # 二卖：确认信号
    'S3': 55,  # 三卖：风险较大
}

# 趋势/盘整类型的置信度调整
TREND_TYPE_ADJUST = {
    '趋势': 0,    # 趋势背驰，置信度不变
    '盘整': -10,  # 盘整背驰，置信度降低10
    None: 0,
}

# 强力平仓信号（只允许一买/一卖/二买/二卖）
# 缠论第44课：平仓应使用同级别或更高级别的确认信号
STRONG_CLOSE_SIGNALS = {
    "long": {"1sell", "2sell"},   # 做多时只允许一卖/二卖平仓
    "short": {"1buy", "2buy"},     # 做空时只允许一买/二买平仓
}

# 信号退出置信度阈值（缠论原则：只有强确认信号才能平仓）
SIGNAL_EXIT_MIN_CONFIDENCE = 60  # 降低阈值，允许更多信号退出


def signal_type_map(chan_type: str) -> str:
    """将 Chan_Class 信号类型转换为 BacktestEngine 格式"""
    return CHAN_SIGNAL_MAP.get(chan_type, chan_type.lower())


def strength_to_confidence(strength: str, signal_type: str = None, trend_type: str = None) -> float:
    """将信号强度转换为置信度

    缠论原则：
    - 一类买卖点是趋势转折信号，置信度最高
    - 二类买卖点是确认信号，次之
    - 三类买卖点风险最大，置信度最低
    - 趋势背驰比盘整背驰更可靠

    Args:
        strength: 信号强度（超强/强/中/弱），买点有此字段
        signal_type: 信号类型（B1/B2/B3/S1/S2/S3）
        trend_type: 趋势类型（趋势/盘整）

    Returns:
        置信度（0-100）
    """
    # 如果有strength字段，优先使用
    if strength and strength in STRENGTH_TO_CONFIDENCE:
        base_conf = STRENGTH_TO_CONFIDENCE[strength]
    elif signal_type and signal_type in SIGNAL_TYPE_CONFIDENCE:
        # 使用信号类型的默认置信度
        base_conf = SIGNAL_TYPE_CONFIDENCE[signal_type]
    else:
        base_conf = 60

    # 根据趋势类型调整
    adjust = TREND_TYPE_ADJUST.get(trend_type, 0)

    confidence = base_conf + adjust
    return max(40, min(95, confidence))  # 限制在40-95之间


def get_last_pivot(chan: Chan_Class) -> Optional[List]:
    """获取最后一个有效中枢"""
    if not chan.pivot_list:
        return None
    return chan.pivot_list[-1]


def get_prev_pivot(chan: Chan_Class) -> Optional[List]:
    """获取倒数第二个中枢（用于三类买卖点止盈计算）"""
    if not chan.pivot_list or len(chan.pivot_list) < 2:
        return None
    return chan.pivot_list[-2]


def check_reason_negated(
    signal_type: str,
    direction: str,
    current_low: float,
    current_high: float,
    signal_price: float,
    pivot: Optional[List] = None,
    chan: Optional[Chan_Class] = None,
) -> Tuple[bool, str]:
    """检查买入/卖出理由是否被否定

    缠论原则（第100-102课）：
    - 1买理由：底分型是转折点，理由被否定 = 价格显著跌破底分型低点
    - 2买理由：一买后回调不破一买低点，理由被否定 = 价格显著跌破一买低点
    - 3买：不使用理由否定（已有ZD止损），让止损逻辑处理
    - 卖出同理

    注意：放宽容忍度，避免加密货币波动导致的过早止损

    Args:
        signal_type: 信号类型 (B1/B2/B3/S1/S2/S3)
        direction: "long" 或 "short"
        current_low: 当前K线最低价
        current_high: 当前K线最高价
        signal_price: 信号价格
        pivot: 当前中枢

    Returns:
        (is_negated: bool, reason: str)
    """
    if direction == "long":
        # 做多理由检测
        if signal_type == 'B1':
            # 一买：价格显著跌破底分型低点（1%以上）则理由被否定
            if current_low < signal_price * 0.99:  # 放宽至1%容忍度
                return True, f"一买理由被否定(价格${current_low:,.0f}跌破底分型${signal_price:,.0f})"
        elif signal_type == 'B2':
            # 二买：价格显著跌破二买价格（0.8%以上）则理由被否定
            if current_low < signal_price * 0.992:
                return True, f"二买理由被否定(价格${current_low:,.0f}跌破二买价${signal_price:,.0f})"
        # B3不使用理由否定，让止损逻辑处理（ZD止损已足够）

    else:  # short
        # 做空理由检测
        if signal_type == 'S1':
            # 一卖：价格显著突破顶分型高点（1%以上）则理由被否定
            if current_high > signal_price * 1.01:  # 放宽至1%容忍度
                return True, f"一卖理由被否定(价格${current_high:,.0f}突破顶分型${signal_price:,.0f})"
        elif signal_type == 'S2':
            # 二卖：价格显著突破二卖价格（0.8%以上）则理由被否定
            if current_high > signal_price * 1.008:
                return True, f"二卖理由被否定(价格${current_high:,.0f}突破二卖价${signal_price:,.0f})"
        # S3不使用理由否定，让止损逻辑处理（ZG止损已足够）

    return False, ""


def calc_stop_take_from_signal(
    signal: List,
    direction: str,
    current_price: float,
    pivot: Optional[List],
    prev_pivot: Optional[List] = None,
    min_stop_pct: float = MIN_STOP_PCT,
    max_stop_pct: float = MAX_STOP_PCT,
    min_rr: float = MIN_RISK_REWARD,
) -> Tuple[float, float, float]:
    """从信号和中枢数据计算止损止盈

    缠论原文（第100-102课）止损止盈原则：
    - 一买止损 = 底分型低点，止盈 = 中枢ZG或GG
    - 二买止损 = 一买低点，止盈 = 中枢ZG
    - 三买止损 = 中枢ZD，止盈 = 上一中枢ZG（趋势延续）
    - 一卖止损 = 顶分型高点，止盈 = 中枢ZD或DD
    - 二卖止损 = 一卖高点，止盈 = 中枢ZD
    - 三卖止损 = 中枢ZG，止盈 = 上一中枢ZD（趋势延续）

    Args:
        signal: Chan_Class 信号 [date, price, type, eval_time, position, valid, invalid_time, type_str, strength, qjt_pivot_list]
        direction: "long" 或 "short"
        current_price: 当前价格
        pivot: 中枢数据 [date1, date2, ZD, ZG, type, enter_seg, exit_seg, form_time, GG, DD, buy_list, sell_list, ts_list]
        prev_pivot: 上一个中枢（用于三类买卖点）

    Returns:
        (stop_loss, take_profit, risk_reward)
    """
    signal_price = signal[1]
    signal_type = signal[2]  # B1, B2, B3, S1, S2, S3

    # 从中枢提取关键价格
    ZD = pivot[2] if pivot and len(pivot) > 2 else None
    ZG = pivot[3] if pivot and len(pivot) > 3 else None
    DD = pivot[9] if pivot and len(pivot) > 9 else ZD
    GG = pivot[8] if pivot and len(pivot) > 8 else ZG

    # 上一个中枢的价格
    prev_ZD = prev_pivot[2] if prev_pivot and len(prev_pivot) > 2 else None
    prev_ZG = prev_pivot[3] if prev_pivot and len(prev_pivot) > 3 else None

    if direction == "long":
        # ===== 做多止损计算 =====
        if signal_type == 'B1':
            # 一买：止损设在底分型低点
            stop_loss = signal_price * (1 - 0.005)  # 底分型低点下方0.5%
        elif signal_type == 'B2':
            # 二买：止损设在一买低点
            stop_loss = signal_price * (1 - 0.003)
        elif signal_type == 'B3':
            # 三买：止损设在中枢ZD
            stop_loss = ZD * 0.995 if ZD else signal_price * (1 - min_stop_pct)
        else:
            stop_loss = signal_price * (1 - min_stop_pct)

        # 限制止损空间
        stop_distance = (current_price - stop_loss) / current_price
        if stop_distance < min_stop_pct:
            stop_loss = current_price * (1 - min_stop_pct)
        elif stop_distance > max_stop_pct:
            stop_loss = current_price * (1 - max_stop_pct)

        # ===== 做多止盈计算 =====
        if signal_type == 'B1':
            # 一买：止盈看向中枢ZG或GG
            if GG and GG > current_price:
                take_profit = GG
            elif ZG and ZG > current_price:
                take_profit = ZG
            else:
                take_profit = current_price + (current_price - stop_loss) * min_rr
        elif signal_type == 'B2':
            # 二买：止盈看向中枢ZG
            if ZG and ZG > current_price:
                take_profit = ZG
            else:
                take_profit = current_price + (current_price - stop_loss) * min_rr
        elif signal_type == 'B3':
            # 三买：止盈看向上一中枢ZG（趋势延续目标）
            if prev_ZG and prev_ZG > current_price:
                take_profit = prev_ZG
            elif ZG and ZG > current_price:
                take_profit = ZG
            else:
                take_profit = current_price + (current_price - stop_loss) * min_rr
        else:
            take_profit = current_price + (current_price - stop_loss) * min_rr

    else:  # short
        # ===== 做空止损计算 =====
        if signal_type == 'S1':
            # 一卖：止损用中枢GG（更宽松）
            stop_loss = GG * 1.01 if GG and GG > 0 else signal_price * (1 + min_stop_pct)
        elif signal_type == 'S2':
            # 二卖：止损用中枢ZG（更宽松）
            stop_loss = ZG * 1.01 if ZG and ZG > 0 else signal_price * (1 + min_stop_pct)
        elif signal_type == 'S3':
            # 三卖：止损设在中枢ZG
            stop_loss = ZG * 1.01 if ZG and ZG > 0 else signal_price * (1 + min_stop_pct)
        else:
            stop_loss = signal_price * (1 + min_stop_pct)

        # 限制止损空间
        stop_distance = (stop_loss - current_price) / current_price
        if stop_distance < min_stop_pct:
            stop_loss = current_price * (1 + min_stop_pct)
        elif stop_distance > max_stop_pct:
            stop_loss = current_price * (1 + max_stop_pct)

        # ===== 做空止盈计算 =====
        if signal_type == 'S1':
            # 一卖：止盈看向中枢ZD
            if ZD and ZD < current_price:
                take_profit = ZD
            elif DD and DD < current_price:
                take_profit = DD
            else:
                take_profit = current_price - (stop_loss - current_price) * min_rr
        elif signal_type == 'S2':
            # 二卖：止盈看向中枢ZD
            if ZD and ZD < current_price:
                take_profit = ZD
            else:
                take_profit = current_price - (stop_loss - current_price) * min_rr
        elif signal_type == 'S3':
            # 三卖：止盈看向上一中枢ZD（趋势延续目标）
            if prev_ZD and prev_ZD < current_price:
                take_profit = prev_ZD
            elif ZD and ZD < current_price:
                take_profit = ZD
            else:
                take_profit = current_price - (stop_loss - current_price) * min_rr
        else:
            take_profit = current_price - (stop_loss - current_price) * min_rr

    # 计算实际盈亏比
    if direction == "long":
        risk = current_price - stop_loss
        reward = take_profit - current_price
    else:
        risk = stop_loss - current_price
        reward = current_price - take_profit

    risk_reward = reward / risk if risk > 0 else min_rr

    return stop_loss, take_profit, risk_reward


def get_price_momentum_trend(k_list: List, lookback: int = 100) -> str:
    """基于价格动量判断趋势（解决缠论趋势判断滞后问题）

    Args:
        k_list: K线列表
        lookback: 回看K线数量

    Returns:
        'up'/'down'/'consolidation'
    """
    if not k_list or len(k_list) < lookback:
        return 'consolidation'

    # 获取最近lookback根K线的收盘价
    recent_closes = [k.close_price for k in k_list[-lookback:]]

    start_price = recent_closes[0]
    end_price = recent_closes[-1]
    change_pct = (end_price - start_price) / start_price

    # 降低阈值到0.8%使趋势判断更敏感（之前1.5%太保守）
    if change_pct > 0.008:
        return 'up'
    elif change_pct < -0.008:
        return 'down'
    return 'consolidation'


def get_trend_direction(chan_30m: Chan_Class) -> str:
    """从30分钟级别获取趋势方向（使用价格动量判断，更快速响应）"""
    if not chan_30m or not chan_30m.k_list:
        return 'consolidation'

    # 使用价格动量趋势判断（响应更快）
    return get_price_momentum_trend(chan_30m.k_list, lookback=100)


def get_5m_trend_direction(chan_5m: Chan_Class) -> str:
    """从5分钟级别获取趋势方向"""
    if not chan_5m or not chan_5m.trend_list:
        return 'consolidation'

    last_trend = chan_5m.trend_list[-1]
    trend_type = last_trend[2]

    if trend_type in ('up', 'pzup'):
        return 'up'
    elif trend_type in ('down', 'pzdown'):
        return 'down'
    return 'consolidation'


def is_strong_trend(chan_30m: Chan_Class, trend_direction: str) -> bool:
    """判断是否为强趋势（连续中枢同向移动）

    缠论原则（第17课、第20课）：
    - 强趋势定义：连续两个以上中枢同向移动
    - 强下降趋势：前中枢ZG > 当前中枢ZG，价格连续走低
    - 强上升趋势：前中枢ZG < 当前中枢ZG，价格连续走高

    Args:
        chan_30m: 30分钟级别 Chan_Class 实例
        trend_direction: 当前趋势方向 ('up'/'down'/'consolidation')

    Returns:
        bool: 是否为强趋势
    """
    if trend_direction == 'consolidation':
        return False

    if not chan_30m or not chan_30m.pivot_list or len(chan_30m.pivot_list) < 2:
        return False

    # 获取最近两个中枢
    prev_pivot = chan_30m.pivot_list[-2]
    cur_pivot = chan_30m.pivot_list[-1]

    if len(prev_pivot) < 4 or len(cur_pivot) < 4:
        return False

    prev_ZG = prev_pivot[3]  # 前中枢上沿
    cur_ZG = cur_pivot[3]    # 当前中枢上沿
    prev_ZD = prev_pivot[2]  # 前中枢下沿
    cur_ZD = cur_pivot[2]    # 当前中枢下沿

    if trend_direction == 'up':
        # 强上升趋势：中枢位置连续抬高
        return cur_ZG > prev_ZG and cur_ZD > prev_ZD
    elif trend_direction == 'down':
        # 强下降趋势：中枢位置连续降低
        return cur_ZG < prev_ZG and cur_ZD < prev_ZD

    return False


def should_trade_signal_chan(signal_name: str, trend_direction: str, strong_trend: bool = False,
                            confidence: float = 50.0, bs_type: str = None) -> Tuple[bool, float]:
    """根据趋势方向过滤信号（V20 - 缠论原文精确版）

    缠论第17课核心要点：
    1. 一买是下跌趋势背驰后的折返点 → 只在下跌趋势末期有效
    2. 一卖是上涨趋势背驰后的折返点 → 只在上涨趋势末期有效
    3. 二买确认上涨趋势，二卖确认下跌趋势

    V20策略核心：
    - 上涨趋势：只做多（2buy核心，3buy辅助）
    - 下跌趋势：只做空（2sell核心，3sell辅助）
    - 一类买卖点：禁止交易（历史数据验证，25%胜率不可接受）

    Args:
        signal_name: 信号名称
        trend_direction: 回测框架判断的趋势方向
        confidence: 信号置信度
        bs_type: 信号背驰类型（'趋势'/'盘整'）

    Returns:
        (allowed, position_multiplier)
    """
    is_sell = 'sell' in signal_name
    is_buy = 'buy' in signal_name

    # 高置信度信号增加仓位
    confidence_multiplier = 1.0
    if confidence >= 85:
        confidence_multiplier = 1.5
    elif confidence >= 75:
        confidence_multiplier = 1.3

    # === 一类买卖点：禁止交易 ===
    # 回测数据验证：1buy胜率25%，亏损严重
    # 即使是趋势背驰信号，实际表现也不佳
    if signal_name in ('1buy', '1sell'):
        return False, 0.0

    # === 二类买卖点：顺势交易核心 ===
    if trend_direction == 'up':
        if is_buy:
            if signal_name == '2buy':
                return True, 1.2 * confidence_multiplier
            elif signal_name == '3buy':
                return True, 0.8 * confidence_multiplier
        return False, 0.0

    if trend_direction == 'down':
        if is_sell:
            if signal_name == '2sell':
                return True, 1.0 * confidence_multiplier
            elif signal_name == '3sell':
                return True, 0.7 * confidence_multiplier
        return False, 0.0

    # 盘整状态：只允许二卖
    if trend_direction == 'consolidation':
        if signal_name == '2sell':
            return True, 0.8 * confidence_multiplier

    return False, 0.0


# ============================================================
# 主回测逻辑
# ============================================================

def parse_end_date(date_str: str) -> datetime:
    """解析结束日期字符串"""
    date_str = date_str.strip()
    formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d"]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {date_str}")


def fetch_btc_1m_klines(days: int = 5, end_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """获取BTC指定时间段的1分钟K线"""
    if end_time is None:
        end_time = datetime.now(timezone.utc)

    start = end_time - timedelta(days=days)
    start_ms = int(start.timestamp() * 1000)
    total_limit = days * 1440 + 100

    print(f"  正在获取 BTCUSDT 1m K线数据...")
    print(f"  时间范围: {start.strftime('%Y-%m-%d %H:%M')} UTC ~ {end_time.strftime('%Y-%m-%d %H:%M')} UTC")

    klines = get_klines("BTCUSDT", "1m", limit=total_limit, start_time=start_ms)
    print(f"  获取到 {len(klines)} 根K线")

    return klines


def create_bar_data(kline: Dict, symbol: str = "BTCUSDT") -> BarData:
    """将 K线数据转换为 BarData"""
    dt = kline["open_time"]
    if isinstance(dt, str):
        dt = pd.to_datetime(dt)

    return BarData(
        datetime=dt,
        symbol=symbol,
        exchange=Exchange.XSHG,
        freq='1m',
        open_price=float(kline["open"]),
        high_price=float(kline["high"]),
        low_price=float(kline["low"]),
        close_price=float(kline["close"]),
        volume=float(kline.get("volume", 0)),
    )


def run_backtest(days: int = 5, end_date: Optional[str] = None) -> None:
    """执行回测"""
    # 解析结束时间
    end_time = None
    if end_date:
        end_time = parse_end_date(end_date)
        print(f"  回测结束时间: {end_time.strftime('%Y-%m-%d %H:%M')} UTC")

    print("=" * 80)
    print("  缠论引擎回测系统 - 基于 chanClass.py")
    print(f"  标的: BTCUSDT | 级别: 30m → 5m → 1m | 本金: ${INITIAL_CAPITAL:,.0f}")
    print(f"  回测天数: {days}")
    print("=" * 80)

    # 1. 获取数据
    print("\n[1/5] 获取BTC 1分钟K线数据...")
    klines = fetch_btc_1m_klines(days=days, end_time=end_time)

    if len(klines) < WARMUP_BARS + 100:
        print(f"  错误: K线数据不足（需要至少 {WARMUP_BARS + 100} 根）")
        return

    start_time_str = str(klines[0]["open_time"])
    end_time_str = str(klines[-1]["open_time"])

    # 2. 初始化多级别 Chan_Class 链表
    print(f"\n[2/5] 初始化 Chan_Class 多级别链表（预热{WARMUP_BARS}根K线）...")

    # 30分钟级别
    chan_30m = Chan_Class(
        freq='30分钟',
        symbol='BTCUSDT',
        sell=None,
        buy=None,
        include=True,
        include_feature=False,
        build_line_pivot=False,  # 使用笔构建中枢
        qjt=True,
        gz=False,
    )

    # 5分钟级别
    chan_5m = Chan_Class(
        freq='5分钟',
        symbol='BTCUSDT',
        sell=None,
        buy=None,
        include=True,
        include_feature=False,
        build_line_pivot=False,
        qjt=True,
        gz=False,
    )

    # 1分钟级别
    chan_1m = Chan_Class(
        freq='1分钟',
        symbol='BTCUSDT',
        sell=None,
        buy=None,
        include=True,
        include_feature=False,
        build_line_pivot=False,
        qjt=True,
        gz=False,
    )

    # 建立链表: 30m → 5m → 1m
    chan_30m.set_next(chan_5m)
    chan_5m.set_prev(chan_30m)
    chan_5m.set_next(chan_1m)
    chan_1m.set_prev(chan_5m)

    print(f"  多级别链表已建立: 30m → 5m → 1m")

    # K线聚合器
    agg_30m = BarAggregator(window=30)
    agg_5m = BarAggregator(window=5)

    # 3. 初始化回测引擎
    print(f"\n[3/5] 启动增量回测...")
    bt = BacktestEngine(
        capital=INITIAL_CAPITAL,
        fee_rate=FEE_RATE,
        slippage=SLIPPAGE,
    )

    # 状态追踪
    processed_signals: set = set()
    last_signal_bi_count: int = -1
    cooldown_bars: int = 5
    last_signal_bar: int = -999

    # 连续信号防护（缠论第17课：走势终完美，一买是趋势转折，连续一买说明未转折）
    last_trade_signal_type: str = ""  # 上笔交易信号类型
    last_trade_was_loss: bool = False  # 上笔交易是否亏损
    consecutive_same_signal_losses: int = 0  # 同类信号连续亏损次数

    position_max_price: float = 0.0
    position_min_price: float = float('inf')

    trend_direction_cache: str = "consolidation"

    # 进度显示
    total = len(klines)
    report_interval = max(1000, total // 20)

    # 信号统计
    signals_received: List[Dict[str, Any]] = []
    signals_by_type: Dict[str, int] = {}

    for i, kline in enumerate(klines):
        bar = create_bar_data(kline)
        current_price = bar.close_price
        bar_time_str = str(bar.datetime)

        # K线聚合
        bar_dict = {
            "date": bar.datetime,
            "open": bar.open_price,
            "high": bar.high_price,
            "low": bar.low_price,
            "close": bar.close_price,
            "volume": bar.volume,
        }

        # 记录喂入前的信号数量
        prev_buy_len = len(chan_5m.buy_list)
        prev_sell_len = len(chan_5m.sell_list)

        # 喂入各级别
        # 1分钟级别（每根都喂）
        chan_1m.on_bar(bar)

        # 5分钟级别（聚合后喂入）
        agg_bar_5m = agg_5m.update(bar_dict)
        if agg_bar_5m:
            agg_bar_5m_bar = BarData(
                datetime=agg_bar_5m["date"],
                symbol="BTCUSDT",
                exchange=Exchange.XSHG,
                freq='5m',
                open_price=agg_bar_5m["open"],
                high_price=agg_bar_5m["high"],
                low_price=agg_bar_5m["low"],
                close_price=agg_bar_5m["close"],
                volume=agg_bar_5m.get("volume", 0),
            )
            chan_5m.on_bar(agg_bar_5m_bar)

        # 30分钟级别（聚合后喂入）
        agg_bar_30m = agg_30m.update(bar_dict)
        if agg_bar_30m:
            agg_bar_30m_bar = BarData(
                datetime=agg_bar_30m["date"],
                symbol="BTCUSDT",
                exchange=Exchange.XSHG,
                freq='30m',
                open_price=agg_bar_30m["open"],
                high_price=agg_bar_30m["high"],
                low_price=agg_bar_30m["low"],
                close_price=agg_bar_30m["close"],
                volume=agg_bar_30m.get("volume", 0),
            )
            chan_30m.on_bar(agg_bar_30m_bar)

        # 合并趋势判断：缠论中枢趋势 + 价格动量（双确认更可靠）
        momentum_trend = get_price_momentum_trend(chan_1m.k_list, lookback=120)
        chanlun_trend = get_trend_direction(chan_30m)

        # 双重趋势确认逻辑：
        # 1. 如果两者一致，使用该趋势
        # 2. 如果不一致，使用价格动量（更实时）
        # 3. 缠论趋势作为额外约束：明确下跌时禁止1buy，明确上涨时禁止1sell
        if momentum_trend == chanlun_trend:
            trend_direction_cache = momentum_trend
        elif chanlun_trend == 'consolidation':
            trend_direction_cache = momentum_trend
        else:
            # 不一致时，使用价格动量但保留缠论方向标记
            trend_direction_cache = momentum_trend

        # 预热期间不交易
        if i < WARMUP_BARS:
            continue

        # ===== 持仓管理 =====
        if bt.position is not None:
            pos = bt.position
            direction = pos.get("direction", "long")
            stop = pos["stop_loss"]
            tp = pos["take_profit"]
            open_price = pos["open_price"]
            signal_ref = pos.get("signal_ref")
            signal_type = pos.get("signal_type", "")
            signal_price = signal_ref[1] if signal_ref else open_price
            last_pivot = get_last_pivot(chan_5m)

            # 更新最高/最低价
            if bar.high_price > position_max_price:
                position_max_price = bar.high_price
            if bar.low_price < position_min_price:
                position_min_price = bar.low_price

            # ===== 止损检查（纯止损逻辑，不再使用理由否定） =====
            if direction == "long" and bar.low_price <= stop:
                max_fav = (position_max_price / open_price - 1) * 100
                max_adv = (position_min_price / open_price - 1) * 100
                # 保存信号类型用于连续信号防护（转换为统一格式）
                closed_signal_raw = bt.position.get("signal_type", "") if bt.position else ""
                closed_signal_type = signal_type_map(closed_signal_raw)  # B1 → 1buy
                trade = bt.close_position(
                    price=stop,
                    bar_time=bar_time_str,
                    reason="stop_loss",
                    bar_idx=i,
                    max_fav=max_fav,
                    max_adv=max_adv,
                )
                position_max_price = 0.0
                position_min_price = float('inf')
                # 更新连续信号追踪（先比较再更新）
                is_loss = trade.pnl < 0 if trade else True
                if is_loss and closed_signal_type == last_trade_signal_type:
                    consecutive_same_signal_losses += 1
                else:
                    consecutive_same_signal_losses = 0
                last_trade_signal_type = closed_signal_type
                last_trade_was_loss = is_loss
                print(f"  [止损] #{trade.trade_id} 做多 @ ${stop:,.0f} PnL=${trade.pnl:,.2f}")
                continue
            elif direction == "short" and bar.high_price >= stop:
                max_fav = (open_price - position_min_price) / open_price * 100
                max_adv = (position_max_price - open_price) / open_price * 100
                # 保存信号类型用于连续信号防护（转换为统一格式）
                closed_signal_raw = bt.position.get("signal_type", "") if bt.position else ""
                closed_signal_type = signal_type_map(closed_signal_raw)  # B1 → 1buy
                trade = bt.close_position(
                    price=stop,
                    bar_time=bar_time_str,
                    reason="stop_loss",
                    bar_idx=i,
                    max_fav=max_fav,
                    max_adv=max_adv,
                )
                position_max_price = 0.0
                position_min_price = float('inf')
                # 更新连续信号追踪（先比较再更新）
                is_loss = trade.pnl < 0 if trade else True
                if is_loss and closed_signal_type == last_trade_signal_type:
                    consecutive_same_signal_losses += 1
                else:
                    consecutive_same_signal_losses = 0
                last_trade_signal_type = closed_signal_type
                last_trade_was_loss = is_loss
                print(f"  [止损] #{trade.trade_id} 做空 @ ${stop:,.0f} PnL=${trade.pnl:,.2f}")
                continue

            # ===== 移动止损（缠论第20课：盈利加仓原则的逆向应用） =====
            if direction == "long":
                unrealized_pct = (bar.high_price - open_price) / open_price
                if unrealized_pct >= 0.02:  # 浮盈超过2%
                    # 追踪止损：锁定0.5%利润
                    trail_stop = open_price * 1.005
                    if stop < trail_stop:
                        bt.position["stop_loss"] = trail_stop
                        stop = trail_stop
                elif unrealized_pct >= 0.01:  # 浮盈超过1%
                    breakeven_stop = open_price  # 保本
                    if stop < breakeven_stop:
                        bt.position["stop_loss"] = breakeven_stop
                        stop = breakeven_stop
            else:  # short
                unrealized_pct = (open_price - bar.low_price) / open_price
                if unrealized_pct >= 0.02:
                    trail_stop = open_price * 0.995
                    if stop > trail_stop or stop <= 0:
                        bt.position["stop_loss"] = trail_stop
                        stop = trail_stop
                elif unrealized_pct >= 0.01:
                    breakeven_stop = open_price  # 保本
                    if stop > breakeven_stop or stop <= 0:
                        bt.position["stop_loss"] = breakeven_stop
                        stop = breakeven_stop

            # ===== 止盈检查 =====
            if direction == "long":
                if tp > 0 and bar.high_price >= tp:
                    closed_signal_raw = bt.position.get("signal_type", "") if bt.position else ""
                    closed_signal_type = signal_type_map(closed_signal_raw)  # B1 → 1buy
                    bt.close_position(
                        price=tp,
                        bar_time=bar_time_str,
                        reason="take_profit",
                        bar_idx=i,
                        max_fav=(position_max_price / open_price - 1) * 100,
                        max_adv=(position_min_price / open_price - 1) * 100,
                    )
                    position_max_price = 0.0
                    position_min_price = float('inf')
                    last_trade_signal_type = closed_signal_type
                    last_trade_was_loss = False  # 止盈是盈利
                    consecutive_same_signal_losses = 0  # 盈利重置连续亏损计数
                    print(f"  [止盈] #{bt.trades[-1].trade_id} 做多 @ ${tp:,.0f} PnL=${bt.trades[-1].pnl:,.2f}")
                    continue
            else:  # short
                if tp > 0 and bar.low_price <= tp:
                    closed_signal_raw = bt.position.get("signal_type", "") if bt.position else ""
                    closed_signal_type = signal_type_map(closed_signal_raw)  # B1 → 1buy
                    bt.close_position(
                        price=tp,
                        bar_time=bar_time_str,
                        reason="take_profit",
                        bar_idx=i,
                        max_fav=(open_price - position_min_price) / open_price * 100,
                        max_adv=(position_max_price - open_price) / open_price * 100,
                    )
                    position_max_price = 0.0
                    position_min_price = float('inf')
                    last_trade_signal_type = closed_signal_type
                    last_trade_was_loss = False  # 止盈是盈利
                    consecutive_same_signal_losses = 0  # 盈利重置连续亏损计数
                    print(f"  [止盈] #{bt.trades[-1].trade_id} 做空 @ ${tp:,.0f} PnL=${bt.trades[-1].pnl:,.2f}")
                    continue

        # ===== 检测新信号 =====
        new_buy_signals = chan_5m.buy_list[prev_buy_len:]
        new_sell_signals = chan_5m.sell_list[prev_sell_len:]

        all_new_signals = []
        for sig in new_buy_signals:
            all_new_signals.append(('buy', sig))
        for sig in new_sell_signals:
            all_new_signals.append(('sell', sig))

        for sig_type, signal in all_new_signals:
            # 检查信号有效性 (signal[5] == 1 表示有效)
            if len(signal) < 6 or signal[5] != 1:
                continue

            # 信号格式: [date, price, type, eval_time, position, valid, invalid_time, type_str, strength, qjt_pivot_list]
            chan_signal_name = signal[2]  # B1, B2, B3, S1, S2, S3
            signal_name = signal_type_map(chan_signal_name)
            signal_price = signal[1]
            signal_time = signal[0]
            strength = signal[8] if len(signal) > 8 else None
            bs_type = signal[7] if len(signal) > 7 else None  # 趋势/盘整（背驰类型）
            trend_type = bs_type  # 兼容旧变量名
            confidence = strength_to_confidence(strength, chan_signal_name, trend_type)

            # 生成唯一键
            sig_key = f"{signal_name}_{signal_time}_{signal_price}"
            if sig_key in processed_signals:
                continue
            processed_signals.add(sig_key)

            # 信号统计
            signals_by_type[signal_name] = signals_by_type.get(signal_name, 0) + 1

            signal_record = {
                "time": bar_time_str,
                "signal": signal_name,
                "confidence": confidence,
                "risk_reward": 0.0,  # 默认值，后续会更新
                "price": signal_price,
                "strength": strength,
                "filtered": False,
            }

            # === 开仓信号处理（无持仓时） ===
            if signal_name in ENTRY_SIGNALS and bt.position is None:
                # 判断是否为强趋势（连续中枢同向）
                strong_trend = is_strong_trend(chan_30m, trend_direction_cache)

                # 趋势过滤（强化版：返回是否允许 + 仓位系数）
                trend_allowed, position_multiplier = should_trade_signal_chan(
                    signal_name, trend_direction_cache, strong_trend, confidence, bs_type
                )
                if not trend_allowed:
                    signal_record["filter_reason"] = f"趋势过滤({trend_direction_cache}不做{signal_name},强趋势={strong_trend})"
                    signal_record["filtered"] = True
                    signals_received.append(signal_record)
                    continue

                # === 连续信号防护（缠论第17课：走势终完美） ===
                # 一买/一卖是趋势转折信号，连续出现说明走势未真正转折
                # 一买连续亏损：禁止下一次一买（等待走势确认）
                if signal_name in ('1buy', '1sell'):
                    if last_trade_signal_type == signal_name and last_trade_was_loss:
                        signal_record["filter_reason"] = f"连续{signal_name}防护(上次{signal_name}亏损)"
                        signal_record["filtered"] = True
                        signals_received.append(signal_record)
                        continue
                    if consecutive_same_signal_losses >= 2 and signal_name == last_trade_signal_type:
                        signal_record["filter_reason"] = f"{signal_name}连续{consecutive_same_signal_losses}次亏损"
                        signal_record["filtered"] = True
                        signals_received.append(signal_record)
                        continue

                # === 多级别趋势确认（仅对二类/三类买卖点） ===
                # 一类买卖点是趋势转折信号，允许30m和5m方向不同
                if signal_name.startswith('2') or signal_name.startswith('3'):
                    trend_5m = get_5m_trend_direction(chan_5m)
                    if trend_direction_cache != 'consolidation' and trend_5m != 'consolidation':
                        # 二类/三类买卖点要求多级别同向
                        if trend_direction_cache != trend_5m:
                            signal_record["filter_reason"] = f"多级别冲突(30m={trend_direction_cache},5m={trend_5m})"
                            signal_record["filtered"] = True
                            signals_received.append(signal_record)
                            continue

                # 置信度检查
                if confidence < MIN_CONFIDENCE:
                    signal_record["filter_reason"] = f"置信度{confidence:.0f}<{MIN_CONFIDENCE}"
                    signal_record["filtered"] = True
                    signals_received.append(signal_record)
                    continue

                # 确定方向
                if 'buy' in signal_name:
                    direction = "long"
                elif 'sell' in signal_name and ENABLE_SHORT:
                    direction = "short"
                else:
                    signals_received.append(signal_record)
                    continue

                # 计算止损止盈
                last_pivot = get_last_pivot(chan_5m)
                prev_pivot = get_prev_pivot(chan_5m)
                stop_loss, take_profit, risk_reward = calc_stop_take_from_signal(
                    signal, direction, current_price, last_pivot, prev_pivot
                )
                signal_record["risk_reward"] = risk_reward

                # 盈亏比检查（根据信号类型使用不同阈值）
                if signal_name.startswith('3'):
                    min_rr = MIN_RISK_REWARD_3  # 三类买卖点要求2.5
                elif signal_name.startswith('2'):
                    min_rr = MIN_RISK_REWARD_2  # 二类买卖点要求2.0
                else:
                    min_rr = MIN_RISK_REWARD    # 一类买卖点要求1.5
                if risk_reward < min_rr:
                    signal_record["filter_reason"] = f"盈亏比{risk_reward:.2f}<{min_rr}"
                    signal_record["filtered"] = True
                    signals_received.append(signal_record)
                    continue

                # 开仓
                trade = bt.open_position(
                    signal_name=signal_name,
                    risk_reward=risk_reward,
                    price=current_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    bar_time=bar_time_str,
                    direction=direction,
                    qjt_verified=False,
                    trend_direction=trend_direction_cache,
                )

                if trade:
                    last_signal_bar = i
                    bt.position["open_bar_idx"] = i
                    bt.position["signal_ref"] = signal  # 保存信号引用，用于失效检测
                    bt.position["signal_type"] = chan_signal_name  # 保存信号类型（B1/S1等）
                    position_max_price = current_price
                    position_min_price = current_price
                    dir_tag = "做多" if direction == "long" else "做空"
                    print(f"  [开仓] #{trade.trade_id} {dir_tag}{signal_name} "
                          f"conf={confidence:.0f} @ ${current_price:,.0f} SL=${stop_loss:,.0f} TP=${take_profit:,.0f}")

                signals_received.append(signal_record)

            # === 反向信号平仓（有持仓时） ===
            elif bt.position is not None:
                pos_dir = bt.position.get("direction", "long")
                close_signals = STRONG_CLOSE_SIGNALS.get(pos_dir, set())

                if signal_name in close_signals and confidence >= SIGNAL_EXIT_MIN_CONFIDENCE:
                    open_bar_idx = bt.position.get("open_bar_idx", 0)
                    if i - open_bar_idx >= 10:  # 最小持仓
                        open_price = bt.position["open_price"]
                        if pos_dir == "long":
                            max_fav = (position_max_price / open_price - 1) * 100
                            max_adv = (position_min_price / open_price - 1) * 100
                        else:
                            max_fav = (open_price - position_min_price) / open_price * 100
                            max_adv = (position_max_price - open_price) / open_price * 100

                        closed_signal_raw = bt.position.get("signal_type", "") if bt.position else ""
                        closed_signal_type = signal_type_map(closed_signal_raw)  # B1 → 1buy
                        trade = bt.close_position(
                            price=current_price,
                            bar_time=bar_time_str,
                            reason=f"signal({signal_name})",
                            bar_idx=i,
                            max_fav=max_fav,
                            max_adv=max_adv,
                        )
                        if trade:
                            position_max_price = 0.0
                            position_min_price = float('inf')
                            # 更新连续信号追踪（先比较再更新）
                            is_loss = trade.pnl < 0
                            if is_loss and closed_signal_type == last_trade_signal_type:
                                consecutive_same_signal_losses += 1
                            else:
                                consecutive_same_signal_losses = 0
                            last_trade_signal_type = closed_signal_type
                            last_trade_was_loss = is_loss
                            dir_tag = "做多" if pos_dir == "long" else "做空"
                            print(f"  [信号平仓] #{trade.trade_id} {dir_tag} → {signal_name} "
                                  f"@ ${current_price:,.0f} PnL=${trade.pnl:,.2f}")

                signals_received.append(signal_record)

        # 记录权益曲线
        if i % 100 == 0:
            eq = bt.get_equity(current_price)
            bt.equity_curve.append((bar_time_str, eq))

        # 进度显示
        if (i + 1) % report_interval == 0 or (i + 1) == total:
            eq = bt.get_equity(current_price)
            pos_info = ""
            if bt.position:
                dir_tag = "多" if bt.position.get("direction") == "long" else "空"
                pos_info = f" 持{dir_tag}@${bt.position['open_price']:,.0f}"
            print(f"  进度: {i+1}/{total} ({(i+1)/total*100:.1f}%) | "
                  f"价格=${current_price:,.0f} | 权益=${eq:,.2f} | "
                  f"交易={len(bt.trades)}笔{pos_info}")

    # 回测结束，平仓
    if bt.position is not None and klines:
        last_price = float(klines[-1]["close"])
        direction = bt.position.get("direction", "long")
        if direction == "long":
            max_fav = (position_max_price / bt.position["open_price"] - 1) * 100
            max_adv = (position_min_price / bt.position["open_price"] - 1) * 100
        else:
            max_fav = (bt.position["open_price"] - position_min_price) / bt.position["open_price"] * 100
            max_adv = (position_max_price - bt.position["open_price"]) / bt.position["open_price"] * 100

        trade = bt.close_position(
            price=last_price,
            bar_time=end_time_str,
            reason="backtest_end",
            bar_idx=len(klines) - 1,
            max_fav=max_fav,
            max_adv=max_adv,
        )
        if trade:
            dir_tag = "做多" if direction == "long" else "做空"
            print(f"  [期末平仓] #{trade.trade_id} {dir_tag} @ ${last_price:,.0f} PnL=${trade.pnl:,.2f}")

    # 5. 生成报告
    print(f"\n[5/5] 生成回测报告...")

    all_prices = [float(k["close"]) for k in klines]
    stats = bt.calculate_stats(all_prices)
    stats.signals_by_type = signals_by_type

    report = generate_report(
        stats=stats,
        trades=bt.trades,
        start_time=start_time_str,
        end_time=end_time_str,
        total_bars=len(klines),
        warmup_bars=WARMUP_BARS,
        signals_received=signals_received,
    )

    # 保存报告
    output_dir = PROJECT_ROOT / "backtest_output"
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_file = output_dir / f"backtest_chanclass_{timestamp}.md"
    report_file.write_text(report, encoding="utf-8")

    json_file = output_dir / f"backtest_chanclass_{timestamp}.json"
    json_data = {
        "stats": stats.to_dict(),
        "trades": [asdict(t) for t in bt.trades],
        "signals": signals_received,
    }
    json_file.write_text(json.dumps(json_data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # 控制台摘要
    long_trades = [t for t in bt.trades if t.direction == "long"]
    short_trades = [t for t in bt.trades if t.direction == "short"]

    print(f"\n{'=' * 80}")
    print(f"  回测完成! (基于 chanClass.py)")
    print(f"{'=' * 80}")
    print(f"  初始本金:   ${INITIAL_CAPITAL:>12,.2f}")
    print(f"  最终权益:   ${stats.final_capital:>12,.2f}")
    print(f"  总盈亏:     ${stats.total_pnl:>+12,.2f} ({stats.total_pnl_pct:+.2f}%)")
    print(f"  最大回撤:   {stats.max_drawdown_pct:>12.2f}%")
    print(f"  交易次数:   {stats.total_trades:>12} (多{len(long_trades)} 空{len(short_trades)})")
    print(f"  胜率:       {stats.win_rate:>12.1f}%")
    print(f"  盈亏比:     {stats.profit_factor:>12.2f}")
    print(f"{'=' * 80}")
    print(f"  报告已保存:")
    print(f"  - {report_file}")
    print(f"  - {json_file}")
    print(f"{'=' * 80}")


def main():
    parser = argparse.ArgumentParser(
        description="缠论引擎回测系统 - 基于 chanClass.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-d", "--days", type=int, default=5, help="回测天数（默认5天）")
    parser.add_argument("-e", "--end-date", type=str, default=None, help="结束日期，格式: YYYY-MM-DD")

    args = parser.parse_args()
    run_backtest(days=args.days, end_date=args.end_date)


if __name__ == "__main__":
    main()
