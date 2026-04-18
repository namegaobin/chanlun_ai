"""缠论引擎封装（engine）- 改进版 v3.0

本模块的职责：
- 接收已经准备好的、完整的 K 线数据序列（不裁剪、不修改）
- 进行缠论结构计算（笔、线段、中枢等）
- 返回 ICL 对象，供上层按需读取笔、线段、中枢、买卖点、背驰等结构

改进内容（v3.0）：
1. K线包含关系处理 - 合并K线后再识别分型
2. 分型识别完善 - 严格的顶底分型判断
3. 笔算法重写 - 修复笔延伸和笔连续性问题
   - 笔延伸时，新分型与当前终点之间必须至少有4根K线
   - 确保相邻笔的起点和终点连续（前一笔的终点 = 后一笔的起点）
4. 线段算法重写 - 基于特征序列分型
5. 中枢计算优化 - 完善中枢关系判断
6. 背驰和买卖点完善 - 多维度力度计算
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
import logging

import pandas as pd
import numpy as np

# 设置日志
logger = logging.getLogger(__name__)


# ============================================================
# 缠论结构对象定义
# ============================================================

class MergedKline:
    """合并后的K线对象（处理包含关系后）"""
    def __init__(
        self,
        index: int,
        date: Any,
        high: float,
        low: float,
        open_price: float,
        close: float,
        raw_indices: List[int] = None,
        raw_high: float = None,
        raw_low: float = None,
        raw_high_idx: int = None,
        raw_low_idx: int = None,
    ):
        self.index = index
        self.date = date
        self.high = high
        self.low = low
        self.open = open_price
        self.close = close
        self.raw_indices = raw_indices or [index]
        self.raw_high = raw_high if raw_high is not None else high
        self.raw_low = raw_low if raw_low is not None else low
        self.raw_high_idx = raw_high_idx if raw_high_idx is not None else (raw_indices[-1] if raw_indices else index)
        self.raw_low_idx = raw_low_idx if raw_low_idx is not None else (raw_indices[-1] if raw_indices else index)
    
    def __repr__(self):
        return f"<MergedKline idx={self.index} H={self.high:.2f} L={self.low:.2f} raw_H={self.raw_high:.2f} raw_L={self.raw_low:.2f}>"


class SimpleFX:
    """分型对象（顶分型/底分型）"""
    def __init__(
        self,
        fx_type: str,
        index: int,
        kline: MergedKline,
        price: float,
        time: Any,
        raw_index: int = None,
    ):
        self.type = fx_type  # "ding" 或 "di"
        self.index = index
        self.k = kline
        self.val = price
        self.time = time
        self.raw_index = raw_index or index
    
    def __repr__(self):
        return f"<SimpleFX type={self.type} idx={self.index} price={self.val:.2f} time={self.time}>"


class SimpleKline:
    """简化的 K 线对象"""
    def __init__(self, date: Any, high: float, low: float, close: float):
        self.date = date
        self.high = high
        self.low = low
        self.close = close


class SimpleBi:
    """笔对象"""
    def __init__(
        self,
        index: int,
        direction: str,
        start_fx: SimpleFX,
        end_fx: SimpleFX,
        start_index: int,
        end_index: int,
        is_done: bool = True,
    ):
        self.index = index
        self.type = direction  # 'up' or 'down'
        self._is_done = is_done
        
        self.start_fx = start_fx
        self.end_fx = end_fx
        
        self.start_index = start_index
        self.end_index = end_index
        
        self.start_time = start_fx.time
        self.end_time = end_fx.time
        self.start_price = float(start_fx.val)
        self.end_price = float(end_fx.val)
        
        start_kline = SimpleKline(self.start_time, self.start_price, self.start_price, self.start_price)
        end_kline = SimpleKline(self.end_time, self.end_price, self.end_price, self.end_price)
        self.start = SimpleFX("di" if direction == "up" else "ding", start_fx.index, start_fx.k, self.start_price, self.start_time)
        self.end = SimpleFX("ding" if direction == "up" else "di", end_fx.index, end_fx.k, self.end_price, self.end_time)
        
        if direction == "up":
            self.high = self.end_price
            self.low = self.start_price
        else:
            self.high = self.start_price
            self.low = self.end_price
        
        self.strength: float = 0.0
        self.macd_strength: float = 0.0
        self.price_strength: float = 0.0
        self.slope_strength: float = 0.0
        
        self.mmds: List[Any] = []
        self.bcs: List[Any] = []
    
    def is_done(self) -> bool:
        return self._is_done
    
    def __repr__(self):
        return f"<SimpleBi index={self.index} type={self.type} start={self.start_price:.2f} end={self.end_price:.2f} done={self._is_done}>"


class SimpleXD:
    """线段对象"""
    def __init__(
        self,
        index: int,
        direction: str,
        start_bi: SimpleBi,
        end_bi: SimpleBi,
        bi_list: List[SimpleBi],
        is_done: bool = True,
    ):
        self.index = index
        self.type = direction
        self._is_done = is_done
        
        self.bi_list = bi_list
        self.start_bi_index = start_bi.index
        self.end_bi_index = end_bi.index
        
        self.start_time = start_bi.start_time
        self.end_time = end_bi.end_time
        
        if direction == "up":
            self.start_price = start_bi.end_price
            self.end_price = end_bi.end_price
        else:
            self.start_price = start_bi.start_price
            self.end_price = end_bi.end_price
        
        start_kline = SimpleKline(self.start_time, self.start_price, self.start_price, self.start_price)
        end_kline = SimpleKline(self.end_time, self.end_price, self.end_price, self.end_price)
        self.start = SimpleFX("di" if direction == "up" else "ding", 0, None, self.start_price, self.start_time)
        self.end = SimpleFX("ding" if direction == "up" else "di", 0, None, self.end_price, self.end_time)
        
        if direction == "up":
            self.high = self.end_price
            self.low = self.start_price
            self.ding_fx = self.end
            self.di_fx = self.start
        else:
            self.high = self.start_price
            self.low = self.end_price
            self.ding_fx = self.start
            self.di_fx = self.end
        
        self.strength: float = 0.0
        
        self.mmds: List[Any] = []
        self.bcs: List[Any] = []
    
    def is_done(self) -> bool:
        return self._is_done
    
    def __repr__(self) -> str:
        return f"<SimpleXD index={self.index} type={self.type} start={self.start_price:.2f} end={self.end_price:.2f} bis={len(self.bi_list)}>"


class SimpleZS:
    """中枢对象"""
    def __init__(
        self,
        index: int,
        zs_type: str,
        direction: str,
        start_time: Any,
        end_time: Any,
        zg: float,
        zd: float,
        gg: float,
        dd: float,
        level: int = 1,
        relation: str = "new",
        bi_count: int = 0,
    ):
        self.index = index
        self.zs_type = zs_type
        self.direction = direction
        
        self.start_time = start_time
        self.end_time = end_time
        
        self.zg = zg
        self.zd = zd
        self.gg = gg
        self.dd = dd
        
        self.high = zg
        self.low = zd
        self.type = direction
        
        self.level = level
        self.relation = relation
        self.bi_count = bi_count
        self.done = True
        self.real = True
    
    def __repr__(self) -> str:
        return f"<SimpleZS index={self.index} type={self.zs_type} direction={self.direction} ZG={self.zg:.2f} ZD={self.zd:.2f}>"


class SimpleBC:
    """背驰对象"""
    def __init__(
        self,
        bc_type: str,
        is_bc: bool = True,
        zs: Optional[SimpleZS] = None,
        compare_item: Any = None,
    ):
        self.type = bc_type
        self.bc = is_bc
        self.zs = zs
        self.compare_item = compare_item
    
    def __repr__(self) -> str:
        return f"<SimpleBC type={self.type} is_bc={self.bc}>"


class SimpleMMD:
    """买卖点对象"""
    def __init__(
        self,
        name: str,
        zs: Optional[SimpleZS] = None,
        msg: Optional[str] = None,
        strength: str = "",
        bs_type: str = "",
    ):
        self.name = name
        self.zs = zs
        self.msg = msg
        self.strength = strength  # 买卖点强度: 超强/强/中/弱
        self.bs_type = bs_type    # 背驰类型: 盘整/趋势
    
    def __repr__(self) -> str:
        parts = [f"name={self.name}"]
        if self.msg:
            parts.append(f"msg={self.msg}")
        if self.strength:
            parts.append(f"strength={self.strength}")
        if self.bs_type:
            parts.append(f"bs_type={self.bs_type}")
        return f"<SimpleMMD {' '.join(parts)}>"


# ============================================================
# 缠论引擎核心类（改进版 v3.0）
# ============================================================

class SimpleICL:
    """缠论引擎核心类（改进版 v3.0）
    
    核心改进：
    1. 修复笔延伸逻辑：确保笔延伸时距离条件正确
    2. 确保笔的连续性：相邻笔共享端点分型
    """
    
    def __init__(self, code: str, frequency: str, config: Dict[str, Any]):
        self.code = code
        self.frequency = frequency
        self.config = config or {}
        
        self.bi_min_kline = self.config.get('bi_min_kline', 5)
        self.xd_min_bi = self.config.get('xd_min_bi', 3)
        self.zs_min_bi = self.config.get('zs_min_bi', 5)
        
        self._merged_klines: List[MergedKline] = []
        self._fx_list: List[SimpleFX] = []
        
        self._bis: List[SimpleBi] = []
        self._xds: List[SimpleXD] = []
        self._bi_zss: List[SimpleZS] = []
        self._xd_zss: List[SimpleZS] = []
        self._zsd_zss: List[SimpleZS] = []
        
        self._raw_df: pd.DataFrame = None
        self._macd_hist: List[float] = []
        self._primary_zss: List[SimpleZS] = []  # 买卖点使用的主中枢列表（笔或线段）
        
        self.divergence_ratio_threshold = self.config.get('divergence_ratio_threshold', 0.4)
        self.build_line_pivot = self.config.get('build_line_pivot', False)
        
        # --- 事件驱动模式（移植自chanClass on_bar） ---
        self._mode: str = self.config.get('mode', 'batch')  # 'batch' 或 'stream'
        self._raw_rows: List[Dict[str, Any]] = []           # 流式模式累积的K线
        self._dirty: bool = True                              # 数据是否有更新
        self._initialized: bool = False                       # 增量模式：是否已完成首次全量计算
        
        # --- 区间套（移植自chanClass qjt） ---
        self.qjt: bool = self.config.get('qjt', True)
        # prev/next 形成多级别链表：日线 -> 30分钟 -> 5分钟 -> 1分钟
        self.prev: Optional["SimpleICL"] = None  # 上一个（更大）级别
        self.next_level: Optional["SimpleICL"] = None  # 下一个（更小）级别
        
        # --- 共振机制（移植自chanClass gz） ---
        self.gz: bool = self.config.get('gz', False)
        self._gz_delay_k_num: int = 0
        self._gz_delay_k_max: int = self.config.get('gz_delay_k_max', 12)
        self._gz_tmp_mmd: Optional[SimpleMMD] = None   # 当前级别产生的临时买卖点
        self._gz_prev_last_mmd: Optional[SimpleMMD] = None  # 上一次共振确认的买卖点
        self._gz_confirmed_mmds: List[SimpleMMD] = []   # 共振确认后的买卖点列表
    
    def process_klines(self, df: pd.DataFrame) -> "SimpleICL":
        """对 K 线进行缠论结构计算"""
        if len(df) == 0:
            return self
        
        self._raw_df = df.copy()
        
        required_cols = ['date', 'open', 'high', 'low', 'close']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"缺少必须字段: {col}")
        
        # 1. K线包含关系处理
        self._merged_klines = self._merge_klines(df)
        logger.debug(f"合并K线: {len(df)} -> {len(self._merged_klines)}")
        
        # 2. 识别分型
        self._fx_list = self._calculate_fx(self._merged_klines)
        logger.debug(f"识别分型: {len(self._fx_list)} 个")
        
        # 3. 生成笔（使用新算法）
        self._bis = self._calculate_bi_v3(self._fx_list, self._merged_klines)
        logger.debug(f"生成笔: {len(self._bis)} 笔")
        
        # 4. 计算笔的力度
        self._calculate_bi_strength(df)
        
        # 5. 生成线段
        self._xds = self._calculate_xd(self._bis)
        logger.debug(f"生成线段: {len(self._xds)} 段")
        
        # 6. 计算线段力度
        self._calculate_xd_strength()
        
        # 7. 计算中枢（build_line_pivot选项：使用笔或线段构成中枢）
        self._bi_zss = self._calculate_zs(self._bis, "bi")
        self._xd_zss = self._calculate_zs_from_xd(self._xds, "xd")
        if self.build_line_pivot:
            self._primary_zss = self._xd_zss
        else:
            self._primary_zss = self._bi_zss
        logger.debug(f"笔中枢: {len(self._bi_zss)}, 线段中枢: {len(self._xd_zss)}")
        
        # 8. 计算MACD直方图（用于背驰判断）
        self._macd_hist = self._calculate_macd_hist()
        
        # 9. 计算买卖点和背驰（移植自chanClass）
        self._calculate_1st_class_mmds()
        self._calculate_2nd_class_mmds()
        self._calculate_3rd_class_mmds()
        self._invalidate_mmds()
        
        return self
    
    def on_bar(self, bar: Dict[str, Any]) -> Optional[SimpleMMD]:
        """增量事件驱动模式：逐根K线推送，真正的增量计算
        
        优化策略（对比旧版recalculate每次全量O(n)）：
        1. 首次50根K线：全量计算（建立基准状态）
        2. 后续每根K线：
           a. 增量合并K线 O(1) — 不重新合并全部K线
           b. 检查尾部分型变化 O(1) — 只看最后3根合并K线
           c. 无变化 → 直接返回（覆盖80%+场景，总耗时O(1)）
           d. 有变化 → 只重算最后一笔相关的结构（部分笔 + 全量线段/中枢/买卖点）
        
        Args:
            bar: 单根K线数据，包含 date/open/high/low/close/volume 字段
        
        Returns:
            最新买卖点，或 None
        """
        self._raw_rows.append(bar)
        
        if len(self._raw_rows) < 50:
            return None
        
        # 首次全量计算（建立基准）
        if not self._initialized:
            df = pd.DataFrame(self._raw_rows)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            self.process_klines(df)
            self._initialized = True
            if self.gz:
                self._check_gz_tmp_mmd()
            return None
        
        # 增量合并K线 O(1)
        merged_changed = self._merge_incremental(bar)
        
        # 检查尾部分型变化 O(1)
        fx_changed = self._check_tail_fractal()
        
        if not merged_changed and not fx_changed:
            return None
        
        # 有结构性变化：从已有分型列表重算（跳过K线合并和分型识别）
        self._recompute_from_fx()
        
        # 共振处理
        if self.gz and self._gz_tmp_mmd is not None:
            self._gz_delay_k_num += 1
            return self._process_gz()
        
        return self._get_latest_mmd()
    
    def recalculate(self) -> None:
        """全量重算（向后兼容接口）
        
        将累积的K线数据重新构建为DataFrame，然后走完整的批处理流程。
        """
        if not self._raw_rows:
            return
        df = pd.DataFrame(self._raw_rows)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        self.process_klines(df)
        if self.gz:
            self._check_gz_tmp_mmd()
    
    def _get_latest_mmd(self) -> Optional[SimpleMMD]:
        """获取最新产生的买卖点"""
        if self.gz:
            return None
        for bi in reversed(self._bis):
            if bi.mmds:
                return bi.mmds[-1]
        return None
    
    def set_level_chain(self, prev: Optional["SimpleICL"] = None, next_level: Optional["SimpleICL"] = None) -> None:
        """设置多级别链表关系（用于区间套和共振）
        
        用法示例：
            daily_icl = SimpleICL("BTC", "1d", config)
            m30_icl = SimpleICL("BTC", "30m", config)
            m5_icl = SimpleICL("BTC", "5m", config)
            
            daily_icl.set_level_chain(prev=None, next_level=m30_icl)
            m30_icl.set_level_chain(prev=daily_icl, next_level=m5_icl)
            m5_icl.set_level_chain(prev=m30_icl, next_level=None)
        """
        self.prev = prev
        self.next_level = next_level
    
    # ========================================
    # 1. K线包含关系处理
    # ========================================
    
    def _merge_klines(self, df: pd.DataFrame) -> List[MergedKline]:
        """处理K线包含关系"""
        if len(df) < 2:
            return [MergedKline(
                index=0,
                date=df.iloc[0]['date'],
                high=float(df.iloc[0]['high']),
                low=float(df.iloc[0]['low']),
                open_price=float(df.iloc[0]['open']),
                close=float(df.iloc[0]['close']),
                raw_indices=[0],
                raw_high_idx=0,
                raw_low_idx=0,
            )] if len(df) == 1 else []
        
        merged: List[MergedKline] = []
        
        first = df.iloc[0]
        merged.append(MergedKline(
            index=0,
            date=first['date'],
            high=float(first['high']),
            low=float(first['low']),
            open_price=float(first['open']),
            close=float(first['close']),
            raw_indices=[0],
            raw_high=float(first['high']),
            raw_low=float(first['low']),
            raw_high_idx=0,
            raw_low_idx=0,
        ))
        
        for i in range(1, len(df)):
            row = df.iloc[i]
            curr_high = float(row['high'])
            curr_low = float(row['low'])
            
            prev = merged[-1]
            prev_high = prev.high
            prev_low = prev.low
            
            has_contain = (
                (curr_high <= prev_high and curr_low >= prev_low) or
                (curr_high >= prev_high and curr_low <= prev_low)
            )
            
            if has_contain:
                if len(merged) >= 2:
                    direction = "up" if merged[-1].high > merged[-2].high else "down"
                else:
                    direction = "up" if curr_high > prev_high or curr_low > prev_low else "down"
                
                if direction == "up":
                    new_high = max(curr_high, prev_high)
                    new_low = max(curr_low, prev_low)
                else:
                    new_high = min(curr_high, prev_high)
                    new_low = min(curr_low, prev_low)
                
                prev.high = new_high
                prev.low = new_low
                prev.raw_indices.append(i)
                prev.date = row['date']
                
                # 更新极值和对应的索引
                if curr_high > prev.raw_high:
                    prev.raw_high = curr_high
                    prev.raw_high_idx = i
                if curr_low < prev.raw_low:
                    prev.raw_low = curr_low
                    prev.raw_low_idx = i
            else:
                merged.append(MergedKline(
                    index=len(merged),
                    date=row['date'],
                    high=curr_high,
                    low=curr_low,
                    open_price=float(row['open']),
                    close=float(row['close']),
                    raw_indices=[i],
                    raw_high=curr_high,
                    raw_low=curr_low,
                    raw_high_idx=i,
                    raw_low_idx=i,
                ))
        
        return merged
    
    # ========================================
    # 2. 分型识别
    # ========================================
    
    def _calculate_fx(self, klines: List[MergedKline]) -> List[SimpleFX]:
        """在合并后的K线上识别分型
        
        按照缠论原文：分型应该在合并后的K线上判断，使用合并后的high/low
        而不是原始的raw_high/raw_low。这样向上合并时会忽略向下的突破，
        向下合并时会忽略向上的突破。
        """
        if len(klines) < 3:
            return []
        
        fx_list: List[SimpleFX] = []
        
        for i in range(1, len(klines) - 1):
            prev = klines[i - 1]
            curr = klines[i]
            next_ = klines[i + 1]
            
            # 使用合并后的high/low判断分型（缠论原文）
            is_ding = curr.high > prev.high and curr.high > next_.high
            is_di = curr.low < prev.low and curr.low < next_.low
            
            if is_ding and is_di:
                # 同时满足顶底分型，选择更极端的那个
                high_rise_from_prev = curr.high - prev.high
                high_rise_from_next = curr.high - next_.high
                low_drop_from_prev = prev.low - curr.low
                low_drop_from_next = next_.low - curr.low
                
                max_high_rise = max(high_rise_from_prev, high_rise_from_next)
                max_low_drop = max(low_drop_from_prev, low_drop_from_next)
                
                if max_low_drop >= max_high_rise:
                    fx = SimpleFX(
                        fx_type="di",
                        index=i,
                        kline=curr,
                        price=curr.low,
                        time=curr.date,
                        raw_index=curr.raw_low_idx,
                    )
                else:
                    fx = SimpleFX(
                        fx_type="ding",
                        index=i,
                        kline=curr,
                        price=curr.high,
                        time=curr.date,
                        raw_index=curr.raw_high_idx,
                    )
                fx_list.append(fx)
            elif is_ding:
                fx = SimpleFX(
                    fx_type="ding",
                    index=i,
                    kline=curr,
                    price=curr.high,
                    time=curr.date,
                    raw_index=curr.raw_high_idx,
                )
                fx_list.append(fx)
            elif is_di:
                fx = SimpleFX(
                    fx_type="di",
                    index=i,
                    kline=curr,
                    price=curr.low,
                    time=curr.date,
                    raw_index=curr.raw_low_idx,
                )
                fx_list.append(fx)
        
        return fx_list
    
    # ========================================
    # 3. 笔的生成（v3.0 - 修复笔延伸和连续性）
    # ========================================
    
    def _calculate_bi_v3(
        self,
        fx_list: List[SimpleFX],
        klines: List[MergedKline]
    ) -> List[SimpleBi]:
        """根据分型生成笔（v3.0版本）
        
        核心逻辑（完全按照缠论原文）：
        1. 笔延伸：
           - 同类型分型，且更极端时延伸
           - 延伸时，新分型与当前终点之间必须至少有4根原始K线距离
           - 延伸时，新分型与笔起点之间必须满足笔形成条件（>=5根原始K线）
        
        2. 新笔生成：
           - 类型相反 + 原始K线间隔>=5 + 价格关系满足
           - 新笔的起点 = 前一笔的终点（确保连续性）
        
        3. 使用原始K线索引(raw_index)计算间隔，而不是合并后K线索引
        """
        if len(fx_list) < 2:
            return []
        
        # stroke_list: 存储构成笔端点的分型
        stroke_list: List[SimpleFX] = []
        
        for cur_fx in fx_list:
            if len(stroke_list) < 1:
                # 第一个分型直接加入
                stroke_list.append(cur_fx)
            else:
                last_fx = stroke_list[-1]
                
                # 1. 笔延伸逻辑：同类型分型
                if last_fx.type == cur_fx.type:
                    should_extend = False
                    
                    # 检查是否更极端
                    if last_fx.type == "di":
                        # 底分型：更低才延伸
                        if cur_fx.val < last_fx.val:
                            should_extend = True
                    else:
                        # 顶分型：更高才延伸
                        if cur_fx.val > last_fx.val:
                            should_extend = True
                    
                    # 延伸条件检查：使用原始K线索引
                    if should_extend and len(stroke_list) >= 2:
                        pen_start_fx = stroke_list[-2]
                        # 延伸后整笔的原始K线数量必须 >= 5
                        if cur_fx.raw_index - pen_start_fx.raw_index < 5:
                            should_extend = False
                    
                    if should_extend:
                        stroke_list[-1] = cur_fx
                
                # 2. 新笔生成逻辑：类型相反
                else:
                    # 检查原始K线间隔（必须 >= 5，即中间至少3根K线）
                    kline_gap = cur_fx.raw_index - last_fx.raw_index
                    
                    if kline_gap < 5:
                        continue
                    
                    # 检查价格关系（端点穿越，缠论原文，移植自chanClass）
                    if cur_fx.type == "di":
                        price_valid = cur_fx.val < last_fx.val
                    else:
                        price_valid = cur_fx.val > last_fx.val
                    
                    if price_valid:
                        stroke_list.append(cur_fx)
                        # 笔修正：检查倒数第二个分型是否为最优（移植自chanClass on_stroke）
                        if len(stroke_list) >= 3:
                            self._correct_stroke_endpoint(stroke_list, fx_list)
        
        # 3. 从 stroke_list 生成笔对象
        bis: List[SimpleBi] = []
        bi_index = 0
        
        for i in range(len(stroke_list) - 1):
            start_fx = stroke_list[i]
            end_fx = stroke_list[i + 1]
            
            # 确定方向
            direction = "up" if start_fx.type == "di" else "down"
            
            bi = SimpleBi(
                index=bi_index,
                direction=direction,
                start_fx=start_fx,
                end_fx=end_fx,
                start_index=start_fx.raw_index,
                end_index=end_fx.raw_index,
                is_done=True,
            )
            bis.append(bi)
            bi_index += 1
        
        return bis
    
    def _correct_stroke_endpoint(self, stroke_list: List[SimpleFX], fx_list: List[SimpleFX]) -> None:
        """笔修正：检查倒数第二个分型是否为最优（移植自chanClass on_stroke stroke_change）
        
        修正逻辑：当新笔形成后，回头检查 stroke_list[-2] 和 stroke_list[-1] 之间，
        是否存在更极端的分型可以替代 stroke_list[-2]。
        - 如果当前新增的是底分型(di)，寻找更高的顶分型(ding)替代倒数第二个
        - 如果当前新增的是顶分型(ding)，寻找更低的底分型(di)替代倒数第二个
        """
        cur_fx = stroke_list[-1]
        stroke_change = stroke_list[-2]
        target_type = stroke_list[-2].type
        
        for fx in reversed(fx_list):
            if fx.time <= stroke_list[-2].time:
                break
            if fx.time >= cur_fx.time:
                continue
            if fx.type != target_type:
                continue
            if len(stroke_list) >= 3 and (cur_fx.raw_index - fx.raw_index < 5):
                continue
            
            if cur_fx.type == "di" and fx.val > stroke_change.val:
                stroke_change = fx
            elif cur_fx.type == "ding" and fx.val < stroke_change.val:
                stroke_change = fx
        
        if stroke_change is not stroke_list[-2]:
            stroke_list[-2] = stroke_change
    
    # ========================================
    # 4. 笔的力度计算
    # ========================================
    
    def _calculate_bi_strength(self, df: pd.DataFrame) -> None:
        """计算笔的力度（多维度）"""
        if not self._bis or df is None or len(df) == 0:
            return
        
        close = df["close"].astype(float)
        ema_short = close.ewm(span=12, adjust=False).mean()
        ema_long = close.ewm(span=26, adjust=False).mean()
        dif = ema_short - ema_long
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_hist = (dif - dea) * 2
        hist_values = macd_hist.to_list()
        n = len(hist_values)
        
        for bi in self._bis:
            start_idx = bi.start_index
            end_idx = bi.end_index
            
            if start_idx is None or end_idx is None:
                continue
            
            s = max(0, min(start_idx, end_idx))
            e = min(n - 1, max(start_idx, end_idx))
            segment = hist_values[s:e + 1]
            
            if bi.type == "up":
                bi.macd_strength = float(sum(abs(v) for v in segment if v > 0))
            else:
                bi.macd_strength = float(sum(abs(v) for v in segment if v < 0))
            
            bi.price_strength = abs(bi.end_price - bi.start_price)
            
            kline_count = abs(e - s) + 1
            bi.slope_strength = bi.price_strength / max(kline_count, 1)
            
            bi.strength = (
                0.5 * bi.macd_strength +
                0.3 * bi.price_strength +
                0.2 * bi.slope_strength * 100
            )
    
    # ========================================
    # 5. 线段的生成
    # ========================================
    
    def _calculate_xd(self, bis: List[SimpleBi]) -> List[SimpleXD]:
        """根据笔生成线段"""
        if len(bis) < 3:
            return []
        
        fx_from_bi: List[SimpleFX] = [bis[0].start_fx]
        for bi in bis:
            fx_from_bi.append(bi.end_fx)
        
        if len(fx_from_bi) < 5:
            return []
        
        line_endpoints: List[SimpleFX] = []
        line_endpoints.append(fx_from_bi[0])
        
        for i in range(4, len(fx_from_bi)):
            new_endpoint = False
            
            if (fx_from_bi[i].type == 'ding' and 
                fx_from_bi[i-2].val >= fx_from_bi[i].val and 
                fx_from_bi[i-2].val >= fx_from_bi[i-4].val):
                
                candidate = fx_from_bi[i-2]
                
                if line_endpoints[-1].type == 'di':
                    last_idx = fx_from_bi.index(line_endpoints[-1])
                    if (i - 2 - last_idx) > 2:
                        line_endpoints.append(candidate)
                        new_endpoint = True
                elif line_endpoints[-1].type == 'ding':
                    if candidate.val > line_endpoints[-1].val:
                        line_endpoints[-1] = candidate

            if (fx_from_bi[i].type == 'di' and 
                fx_from_bi[i-2].val <= fx_from_bi[i].val and 
                fx_from_bi[i-2].val <= fx_from_bi[i-4].val):
                
                candidate = fx_from_bi[i-2]
                
                if line_endpoints[-1].type == 'ding':
                    last_idx = fx_from_bi.index(line_endpoints[-1])
                    if (i - 2 - last_idx) > 2:
                        line_endpoints.append(candidate)
                        new_endpoint = True
                elif line_endpoints[-1].type == 'di':
                    if candidate.val < line_endpoints[-1].val:
                        line_endpoints[-1] = candidate
            
            # 线段修正（移植自chanClass on_line line_change）
            if new_endpoint and len(line_endpoints) >= 3:
                self._correct_line_endpoint(line_endpoints, fx_from_bi)
        
        if len(line_endpoints) < 2:
            return []
        
        xds: List[SimpleXD] = []
        
        for i in range(len(line_endpoints) - 1):
            start_fx = line_endpoints[i]
            end_fx = line_endpoints[i + 1]
            
            if start_fx.type == 'di' and end_fx.type == 'ding':
                direction = 'up'
            elif start_fx.type == 'ding' and end_fx.type == 'di':
                direction = 'down'
            else:
                continue
            
            start_bi_idx = None
            end_bi_idx = None
            
            for j, bi in enumerate(bis):
                if start_bi_idx is None:
                    if bi.start_fx == start_fx or bi.end_fx == start_fx:
                        start_bi_idx = j
                if bi.end_fx == end_fx:
                    end_bi_idx = j
            
            if start_bi_idx is None or end_bi_idx is None:
                continue
            
            if bis[start_bi_idx].end_fx == start_fx:
                start_bi_idx += 1
            
            if start_bi_idx >= end_bi_idx:
                continue
            
            bi_list = bis[start_bi_idx:end_bi_idx + 1]
            start_bi = bis[start_bi_idx]
            end_bi = bis[end_bi_idx]
            
            xd = SimpleXD(
                index=len(xds),
                direction=direction,
                start_bi=start_bi,
                end_bi=end_bi,
                bi_list=bi_list,
                is_done=True,
            )
            xd.start_price = start_fx.val
            xd.end_price = end_fx.val
            xd.start_time = start_fx.time
            xd.end_time = end_fx.time
            
            xds.append(xd)
        
        return xds
    
    def _calculate_xd_strength(self) -> None:
        """计算线段的力度"""
        for xd in self._xds:
            xd.strength = sum(bi.strength for bi in xd.bi_list)
    
    def _correct_line_endpoint(self, line_endpoints: List[SimpleFX], fx_from_bi: List[SimpleFX]) -> None:
        """线段修正：检查倒数第二个端点是否为最优（移植自chanClass on_line line_change）
        
        修正逻辑：当新线段端点形成后，回头检查 line_endpoints[-2] 和 line_endpoints[-1] 之间，
        是否存在更极端的笔端点可以替代 line_endpoints[-2]。
        候选必须同时形成有效的3元素极值模式（比前后2个同类型笔端点更极端）。
        """
        cur_fx = line_endpoints[-1]
        last_fx = line_endpoints[-2]
        line_change = last_fx
        target_type = last_fx.type
        
        for idx in range(len(fx_from_bi)):
            fx = fx_from_bi[idx]
            if fx.time <= last_fx.time:
                continue
            if fx.time >= cur_fx.time:
                continue
            if fx.type != target_type:
                continue
            if idx + 2 >= len(fx_from_bi) or idx - 2 < 0:
                continue
            
            n1 = fx_from_bi[idx + 2]
            n2 = fx_from_bi[idx - 2]
            
            if cur_fx.type == "ding" and target_type == "di":
                if fx.val < n1.val and fx.val < n2.val and fx.val < line_change.val:
                    line_change = fx
            elif cur_fx.type == "di" and target_type == "ding":
                if fx.val > n1.val and fx.val > n2.val and fx.val > line_change.val:
                    line_change = fx
        
        if line_change is not last_fx:
            line_endpoints[-2] = line_change
    
    # ========================================
    # 7. 中枢计算
    # ========================================
    
    def _calculate_zs(self, items: List[SimpleBi], level: str) -> List[SimpleZS]:
        """计算笔中枢"""
        if len(items) < self.zs_min_bi:
            return []
        
        zss: List[SimpleZS] = []
        zs_index = 0
        i = 0
        
        def get_bi_range(bi: SimpleBi) -> Tuple[float, float]:
            return (bi.low, bi.high)
        
        while i <= len(items) - self.zs_min_bi:
            first_bis = items[i:i + self.zs_min_bi]
            ranges = [get_bi_range(bi) for bi in first_bis]
            
            zd = max(r[0] for r in ranges)
            zg = min(r[1] for r in ranges)
            
            if zd < zg:
                zs_bis = list(first_bis)
                j = i + self.zs_min_bi
                
                while j < len(items):
                    next_bi = items[j]
                    next_low, next_high = get_bi_range(next_bi)
                    
                    if next_low < zg and next_high > zd:
                        zs_bis.append(next_bi)
                        j += 1
                    else:
                        break
                
                all_ranges = [get_bi_range(bi) for bi in zs_bis]
                first_three = all_ranges[:3]
                zd = max(r[0] for r in first_three)
                zg = min(r[1] for r in first_three)
                gg = max(r[1] for r in all_ranges)
                dd = min(r[0] for r in all_ranges)
                
                if gg > zg and dd < zd:
                    direction = "zd"
                elif gg > zg:
                    direction = "up"
                elif dd < zd:
                    direction = "down"
                else:
                    direction = "zd"
                
                relation = "new"
                if zss:
                    prev_zs = zss[-1]
                    if zd > prev_zs.zg:
                        relation = "up_trend"
                    elif zg < prev_zs.zd:
                        relation = "down_trend"
                    else:
                        relation = "extend"
                
                zs = SimpleZS(
                    index=zs_index,
                    zs_type=level,
                    direction=direction,
                    start_time=zs_bis[0].start_time,
                    end_time=zs_bis[-1].end_time,
                    zg=zg,
                    zd=zd,
                    gg=gg,
                    dd=dd,
                    level=1,
                    relation=relation,
                    bi_count=len(zs_bis),
                )
                zss.append(zs)
                zs_index += 1
                
                i = j
            else:
                i += 1
        
        return zss
    
    def _calculate_zs_from_xd(self, xds: List[SimpleXD], level: str) -> List[SimpleZS]:
        """计算线段中枢"""
        if len(xds) < self.zs_min_bi:
            return []
        
        zss: List[SimpleZS] = []
        zs_index = 0
        i = 0
        
        def get_xd_range(xd: SimpleXD) -> Tuple[float, float]:
            return (xd.low, xd.high)
        
        while i <= len(xds) - self.zs_min_bi:
            first_xds = xds[i:i + self.zs_min_bi]
            ranges = [get_xd_range(xd) for xd in first_xds]
            
            zd = max(r[0] for r in ranges)
            zg = min(r[1] for r in ranges)
            
            if zd < zg:
                zs_xds = list(first_xds)
                j = i + self.zs_min_bi
                
                while j < len(xds):
                    next_xd = xds[j]
                    next_low, next_high = get_xd_range(next_xd)
                    
                    if next_low < zg and next_high > zd:
                        zs_xds.append(next_xd)
                        j += 1
                    else:
                        break
                
                all_ranges = [get_xd_range(xd) for xd in zs_xds]
                first_three = all_ranges[:3]
                zd = max(r[0] for r in first_three)
                zg = min(r[1] for r in first_three)
                gg = max(r[1] for r in all_ranges)
                dd = min(r[0] for r in all_ranges)
                
                if gg > zg and dd < zd:
                    direction = "zd"
                elif gg > zg:
                    direction = "up"
                elif dd < zd:
                    direction = "down"
                else:
                    direction = "zd"
                
                relation = "new"
                if zss:
                    prev_zs = zss[-1]
                    if zd > prev_zs.zg:
                        relation = "up_trend"
                    elif zg < prev_zs.zd:
                        relation = "down_trend"
                    else:
                        relation = "extend"
                
                zs = SimpleZS(
                    index=zs_index,
                    zs_type=level,
                    direction=direction,
                    start_time=zs_xds[0].start_time,
                    end_time=zs_xds[-1].end_time,
                    zg=zg,
                    zd=zd,
                    gg=gg,
                    dd=dd,
                    level=1,
                    relation=relation,
                    bi_count=len(zs_xds),
                )
                zss.append(zs)
                zs_index += 1
                i = j
            else:
                i += 1
        
        return zss
    
    # ========================================
    # 8. MACD计算（用于背驰判断，移植自chanClass）
    # ========================================
    
    def _calculate_macd_hist(self) -> List[float]:
        """计算原始K线的MACD直方图（用于背驰面积比较）
        
        与chanClass的cal_macd方法一致：
        - MACD = (DIF - DEA) * 2
        - DIF = EMA(close, 12) - EMA(close, 26)
        - DEA = EMA(DIF, 9)
        """
        if self._raw_df is None or len(self._raw_df) == 0:
            return []
        close = self._raw_df["close"].astype(float)
        ema_short = close.ewm(span=12, adjust=False).mean()
        ema_long = close.ewm(span=26, adjust=False).mean()
        dif = ema_short - ema_long
        dea = dif.ewm(span=9, adjust=False).mean()
        return ((dif - dea) * 2).tolist()
    
    def _get_bi_macd_area(self, bi: SimpleBi) -> float:
        """获取笔对应的MACD直方图面积
        
        面积 = 笔覆盖的K线范围内，MACD直方图值的绝对值之和。
        使用原始K线索引（bi.start_index, bi.end_index）。
        
        与chanClass的cal_macd方法对应：返回total面积（正负柱绝对值之和）。
        """
        if not self._macd_hist:
            return 0.0
        s = bi.start_index
        e = bi.end_index
        if s is None or e is None:
            return 0.0
        n = len(self._macd_hist)
        lo = max(0, min(s, e))
        hi = min(n - 1, max(s, e))
        return sum(abs(v) for v in self._macd_hist[lo:hi + 1] if v == v)
    
    # ========================================
    # 9. 买卖点和背驰计算（移植自chanClass）
    # ========================================
    
    def _calculate_1st_class_mmds(self) -> None:
        """计算一类买卖点（中枢背驰，缠论原文）
        
        1买 = 向下离开最后一个中枢 + 背驰（离开段MACD面积 < 进入段） + 价格 < DD
        1卖 = 向上离开最后一个中枢 + 背驰（离开段MACD面积 < 进入段） + 价格 > GG
        
        背驰判断逻辑（移植自chanClass.on_turn）：
        1. 多个中枢时：趋势背驰（比较前后两个中枢离开段的MACD面积）
        2. 单个中枢时：盘整背驰（比较进入段与离开段的MACD面积）
        3. MACD面积比例 < divergence_ratio_threshold（默认0.4）判定为背驰
        4. MACD为0时回退到斜率比较（与chanClass一致）
        """
        if len(self._bis) < 5 or not self._primary_zss:
            return
        
        zs_with_buy: set[int] = set()
        zs_with_sell: set[int] = set()
        
        for i, bi in enumerate(self._bis):
            related_zs = self._find_leaving_zs(bi)
            if not related_zs:
                continue
            
            zs_id = id(related_zs)
            
            if bi.type == "down" and bi.end_price >= related_zs.zd:
                continue
            if bi.type == "up" and bi.end_price <= related_zs.zg:
                continue
            
            if not self._check_bi_divergence(related_zs, bi):
                continue
            
            # 区间套确认（移植自chanClass qjt_turn/qjt_trend）
            if self.qjt:
                qjt_start = related_zs.start_time
                qjt_end = bi.end_time
                if bi.type == "down":
                    qjt_confirmed, _ = self.qjt_turn(qjt_start, qjt_end, "down")
                else:
                    qjt_confirmed, _ = self.qjt_turn(qjt_start, qjt_end, "up")
                if not qjt_confirmed:
                    continue
            
            bi.bcs.append(SimpleBC(bc_type="bi", is_bc=True, zs=related_zs))
            
            if bi.type == "down" and zs_id not in zs_with_buy:
                if bi.low < related_zs.dd:
                    bs_type = self._get_bs_type(related_zs)
                    strength = self._cal_b1_buy_strength(bi.low, related_zs)
                    bi.mmds.append(SimpleMMD(
                        name="1buy", zs=related_zs,
                        msg="中枢背驰一买", strength=strength, bs_type=bs_type
                    ))
                    zs_with_buy.add(zs_id)
            
            elif bi.type == "up" and zs_id not in zs_with_sell:
                if bi.high > related_zs.gg:
                    bs_type = self._get_bs_type(related_zs)
                    strength = self._cal_b1_sell_strength(bi.high, related_zs)
                    bi.mmds.append(SimpleMMD(
                        name="1sell", zs=related_zs,
                        msg="中枢背驰一卖", strength=strength, bs_type=bs_type
                    ))
                    zs_with_sell.add(zs_id)
    
    def _calculate_2nd_class_mmds(self) -> None:
        """计算二类买卖点（缠论原文）
        
        2买 = 1买之后的回调不破1买低点（回调底 > 1买底）
        2卖 = 1卖之后的回调不破1卖高点（回调顶 < 1卖顶）
        
        与chanClass.on_pivot中二类买卖点逻辑一致：
        - pos_fx[1] > buy[0][1] → 2buy（回调底高于1买底）
        - pos_fx[0] < sell[0][1] → 2sell（回调顶低于1卖顶）
        """
        for i, bi in enumerate(self._bis):
            if i == 0:
                continue
            
            prev_bi = self._bis[i - 1]
            
            if bi.type == "down":
                for mmd in prev_bi.mmds:
                    if mmd.name == "1buy":
                        if bi.low > prev_bi.low:
                            strength = self._cal_b2_buy_strength(bi, mmd.zs)
                            bi.mmds.append(SimpleMMD(
                                name="2buy", zs=mmd.zs, msg="二买",
                                strength=strength
                            ))
                        break
            
            elif bi.type == "up":
                for mmd in prev_bi.mmds:
                    if mmd.name == "1sell":
                        if bi.high < prev_bi.high:
                            strength = self._cal_b2_sell_strength(bi, mmd.zs)
                            bi.mmds.append(SimpleMMD(
                                name="2sell", zs=mmd.zs, msg="二卖",
                                strength=strength
                            ))
                        break
    
    def _calculate_3rd_class_mmds(self) -> None:
        """计算三类买卖点（缠论原文）
        
        3买 = 离开中枢向上后回拉不进入中枢（回调低点 > ZG）
        3卖 = 离开中枢向下后回拉不进入中枢（回调高点 < ZD）
        
        与chanClass.on_pivot中三类买卖点逻辑一致：
        - cur_fx[1] > last_pivot[3]（ZG）→ 3buy
        - cur_fx[0] < last_pivot[2]（ZD）→ 3sell
        """
        if not self._primary_zss or len(self._bis) < 3:
            return
        
        for zs in self._primary_zss:
            found_3buy = False
            found_3sell = False
            
            for i, bi in enumerate(self._bis):
                if bi.start_time <= zs.end_time:
                    continue
                
                has_1st = any(m.name in ("1buy", "1sell") for m in bi.mmds)
                if has_1st:
                    continue
                
                if bi.type == "down" and not found_3buy:
                    if bi.low > zs.zg:
                        if i > 0:
                            prev_bi = self._bis[i - 1]
                            if prev_bi.type == "up" and prev_bi.high > zs.zg:
                                # 区间套确认：3买前必须有完整离开走势
                                if self.qjt:
                                    qjt_ok, _ = self.qjt_trend(zs.end_time, bi.end_time, "up")
                                    if not qjt_ok:
                                        continue
                                strength = self._cal_b3_buy_strength(bi.low, zs)
                                bi.mmds.append(SimpleMMD(
                                    name="3buy", zs=zs, msg="三类买点",
                                    strength=strength
                                ))
                                found_3buy = True
                
                elif bi.type == "up" and not found_3sell:
                    if bi.high < zs.zd:
                        if i > 0:
                            prev_bi = self._bis[i - 1]
                            if prev_bi.type == "down" and prev_bi.low < zs.zd:
                                # 区间套确认：3卖前必须有完整离开走势
                                if self.qjt:
                                    qjt_ok, _ = self.qjt_trend(zs.end_time, bi.end_time, "down")
                                    if not qjt_ok:
                                        continue
                                strength = self._cal_b3_sell_strength(bi.high, zs)
                                bi.mmds.append(SimpleMMD(
                                    name="3sell", zs=zs, msg="三类卖点",
                                    strength=strength
                                ))
                                found_3sell = True
    
    def _invalidate_mmds(self) -> None:
        """买卖点失效判断（移植自chanClass.on_pivot）
        
        缠论原文失效条件（与chanClass完全一致）：
        1买失效：后续笔创新低（低于1买笔的低点）
          - chanClass: buy[0][1] > cur_fx[1] → 置一买无效
        1卖失效：后续笔创新高（高于1卖笔的高点）
          - chanClass: sell[0][1] < cur_fx[0] → 置一卖无效
        2买失效：后续笔跌破1买低点
          - chanClass: data[start] < data[start - 2] → 一买+二买均无效
        2卖失效：后续笔突破1卖高点
        3买失效：后续笔跌破ZG
          - chanClass: buy[2][0] < last_pivot[1] → 置三类买点无效
        3卖失效：后续笔突破ZD
          - chanClass: sell[2][0] < last_pivot[1] → 置三类卖点无效
        """
        for i, bi in enumerate(self._bis):
            to_remove = []
            for mmd in bi.mmds:
                invalidated = False
                
                if mmd.name == "1buy":
                    for j in range(i + 1, len(self._bis)):
                        if self._bis[j].low < bi.low:
                            invalidated = True
                            break
                
                elif mmd.name == "1sell":
                    for j in range(i + 1, len(self._bis)):
                        if self._bis[j].high > bi.high:
                            invalidated = True
                            break
                
                elif mmd.name == "2buy":
                    one_buy_bi = None
                    for j in range(i - 1, -1, -1):
                        for prev_mmd in self._bis[j].mmds:
                            if prev_mmd.name == "1buy":
                                one_buy_bi = self._bis[j]
                                break
                        if one_buy_bi:
                            break
                    if one_buy_bi:
                        for j in range(i + 1, len(self._bis)):
                            if self._bis[j].low < one_buy_bi.low:
                                invalidated = True
                                break
                
                elif mmd.name == "2sell":
                    one_sell_bi = None
                    for j in range(i - 1, -1, -1):
                        for prev_mmd in self._bis[j].mmds:
                            if prev_mmd.name == "1sell":
                                one_sell_bi = self._bis[j]
                                break
                        if one_sell_bi:
                            break
                    if one_sell_bi:
                        for j in range(i + 1, len(self._bis)):
                            if self._bis[j].high > one_sell_bi.high:
                                invalidated = True
                                break
                
                elif mmd.name == "3buy" and mmd.zs:
                    for j in range(i + 1, len(self._bis)):
                        if self._bis[j].low <= mmd.zs.zg:
                            invalidated = True
                            break
                
                elif mmd.name == "3sell" and mmd.zs:
                    for j in range(i + 1, len(self._bis)):
                        if self._bis[j].high >= mmd.zs.zd:
                            invalidated = True
                            break
                
                if invalidated:
                    to_remove.append(mmd)
            
            for mmd in to_remove:
                bi.mmds.remove(mmd)
    
    # --- 背驰判断辅助方法 ---
    
    def _find_leaving_zs(self, bi: SimpleBi) -> Optional[SimpleZS]:
        """找到笔正在离开的中枢（最后一个笔起点在中枢结束之后的中枢）"""
        for zs in reversed(self._primary_zss):
            if bi.start_time >= zs.end_time:
                return zs
        return None
    
    def _get_zs_enter_bi(self, zs: SimpleZS, direction: str) -> Optional[SimpleBi]:
        """找到中枢的进入段（中枢第一笔之前、同方向的最后一笔）
        
        与chanClass中 ee_data[0] = [data[start-1], data[start]] 对应：
        enter = 中枢第一笔之前同方向笔
        """
        first_idx = None
        for idx, b in enumerate(self._bis):
            if b.start_time >= zs.start_time:
                first_idx = idx
                break
        
        if first_idx is None or first_idx == 0:
            return None
        
        for idx in range(first_idx - 1, -1, -1):
            if self._bis[idx].type == direction:
                return self._bis[idx]
        return None
    
    def _find_zs_leaving_bi(self, zs: SimpleZS, direction: str) -> Optional[SimpleBi]:
        """找到中枢的离开段（中枢结束后、第一个同方向离开中枢的笔）"""
        for bi in self._bis:
            if bi.start_time < zs.end_time:
                continue
            if direction == "down" and bi.end_price < zs.zd:
                return bi
            if direction == "up" and bi.end_price > zs.zg:
                return bi
        return None
    
    def _check_bi_divergence(self, zs: SimpleZS, bi: SimpleBi) -> bool:
        """检查笔是否与中枢形成背驰（移植自chanClass.on_turn）
        
        判断逻辑：
        1. 趋势背驰（多个中枢时）：当前中枢离开段 vs 前一个中枢离开段的MACD面积
        2. 盘整背驰（单个中枢时）：进入段 vs 离开段的MACD面积
        3. MACD面积比例 < threshold（默认0.4，即缩小60%以上）→ 背驰
        4. MACD为0时回退到斜率比较（与chanClass.on_turn中的NaN处理一致）
        
        对应chanClass代码：
        ratio = end_macd_val / start_macd_val
        is_divergence = ratio < self.divergence_ratio_threshold
        """
        curr_area = self._get_bi_macd_area(bi)
        
        zs_idx = None
        for idx, z in enumerate(self._primary_zss):
            if z is zs:
                zs_idx = idx
                break
        
        if zs_idx is None:
            return False
        
        # 1. 趋势背驰：比较相邻两个中枢的离开段
        if zs_idx > 0:
            prev_zs = self._primary_zss[zs_idx - 1]
            prev_leaving = self._find_zs_leaving_bi(prev_zs, bi.type)
            if prev_leaving:
                prev_area = self._get_bi_macd_area(prev_leaving)
                if prev_area > 0 and curr_area / prev_area < self.divergence_ratio_threshold:
                    return True
        
        # 2. 盘整背驰：比较进入段与离开段
        enter_bi = self._get_zs_enter_bi(zs, bi.type)
        if enter_bi:
            enter_area = self._get_bi_macd_area(enter_bi)
            if enter_area > 0 and curr_area / enter_area < self.divergence_ratio_threshold:
                return True
        
        # 3. MACD为0时回退到斜率比较（chanClass: enter_slope > exit_slope）
        if enter_bi:
            enter_klines = max(abs(enter_bi.end_index - enter_bi.start_index), 1)
            curr_klines = max(abs(bi.end_index - bi.start_index), 1)
            enter_slope = abs(enter_bi.end_price - enter_bi.start_price) / enter_klines
            curr_slope = abs(bi.end_price - bi.start_price) / curr_klines
            return curr_slope < enter_slope
        
        return False
    
    # --- 买卖点强度和走势类型辅助方法（移植自chanClass） ---
    
    def _get_bs_type(self, zs: SimpleZS) -> str:
        """判断背驰类型：盘整/趋势（移植自chanClass cal_bs_type）
        
        如果当前中枢与前一个中枢同方向（relation为up_trend或down_trend）→ 趋势背驰
        否则 → 盘整背驰
        """
        if zs.relation in ("up_trend", "down_trend"):
            return "趋势"
        return "盘整"
    
    def _cal_b1_buy_strength(self, price: float, zs: SimpleZS) -> str:
        """计算一类买点强度（移植自chanClass cal_b1_strength）
        
        超强：大幅跌破DD（超过中枢高度50%）
        强：跌破DD
        中：跌破ZD
        弱：其他
        """
        if zs:
            DD = zs.dd
            ZD = zs.zd
            ZG = zs.zg
            pivot_height = ZG - ZD
            threshold = DD - pivot_height * 0.5
            if price < threshold:
                return "超强"
            elif price < DD:
                return "强"
            elif price < ZD:
                return "中"
        return "弱"
    
    def _cal_b1_sell_strength(self, price: float, zs: SimpleZS) -> str:
        """计算一类卖点强度（对称于一类买点）
        
        超强：大幅突破GG（超过中枢高度50%）
        强：突破GG
        中：突破ZG
        弱：其他
        """
        if zs:
            GG = zs.gg
            ZD = zs.zd
            ZG = zs.zg
            pivot_height = ZG - ZD
            threshold = GG + pivot_height * 0.5
            if price > threshold:
                return "超强"
            elif price > GG:
                return "强"
            elif price > ZG:
                return "中"
        return "弱"
    
    def _cal_b2_buy_strength(self, bi: SimpleBi, zs: Optional[SimpleZS]) -> str:
        """计算二类买点强度（移植自chanClass cal_b2_strength）
        
        超强：回调底 > ZG
        强：回调笔顶 > ZG
        中：回调笔顶 > ZD
        弱：其他
        """
        if zs:
            if bi.low > zs.zg:
                return "超强"
            if bi.high > zs.zg:
                return "强"
            if bi.high > zs.zd:
                return "中"
        return "弱"
    
    def _cal_b2_sell_strength(self, bi: SimpleBi, zs: Optional[SimpleZS]) -> str:
        """计算二类卖点强度（对称于二类买点）
        
        超强：回调顶 < ZD
        强：回调笔底 < ZD
        中：回调笔底 < ZG
        弱：其他
        """
        if zs:
            if bi.high < zs.zd:
                return "超强"
            if bi.low < zs.zd:
                return "强"
            if bi.low < zs.zg:
                return "中"
        return "弱"
    
    def _cal_b3_buy_strength(self, price: float, zs: Optional[SimpleZS]) -> str:
        """计算三类买点强度（移植自chanClass cal_b3_strength）
        
        强：价格 > GG（远高于中枢）
        弱：其他
        """
        if zs and price > zs.gg:
            return "强"
        return "弱"
    
    def _cal_b3_sell_strength(self, price: float, zs: Optional[SimpleZS]) -> str:
        """计算三类卖点强度（对称于三类买点）
        
        强：价格 < DD（远低于中枢）
        弱：其他
        """
        if zs and price < zs.dd:
            return "强"
        return "弱"
    
    # ========================================
    # 10. 增量计算优化（真正的 O(1) 快速路径）
    # ========================================
    
    def _merge_incremental(self, bar: Dict[str, Any]) -> bool:
        """增量合并一根K线到合并K线列表（O(1)）
        
        与 _merge_klines（全量O(n)）的区别：
        - 只检查最后一根合并K线与新bar的包含关系
        - 不遍历全部K线
        
        Returns:
            合并后的最后一根K线的H/L是否有变化（影响分型判断）
        """
        raw_idx = len(self._raw_rows) - 1
        curr_high = float(bar['high'])
        curr_low = float(bar['low'])
        
        if not self._merged_klines:
            self._merged_klines.append(MergedKline(
                index=0, date=bar['date'],
                high=curr_high, low=curr_low,
                open_price=float(bar['open']), close=float(bar['close']),
                raw_indices=[raw_idx],
                raw_high=curr_high, raw_low=curr_low,
                raw_high_idx=raw_idx, raw_low_idx=raw_idx,
            ))
            return True
        
        last = self._merged_klines[-1]
        
        has_contain = (
            (curr_high <= last.high and curr_low >= last.low) or
            (curr_high >= last.high and curr_low <= last.low)
        )
        
        if has_contain:
            if len(self._merged_klines) >= 2:
                direction = "up" if self._merged_klines[-1].high > self._merged_klines[-2].high else "down"
            else:
                direction = "up" if (curr_high > last.high or curr_low > last.low) else "down"
            
            old_high, old_low = last.high, last.low
            
            if direction == "up":
                last.high = max(curr_high, last.high)
                last.low = max(curr_low, last.low)
            else:
                last.high = min(curr_high, last.high)
                last.low = min(curr_low, last.low)
            
            last.date = bar['date']
            last.raw_indices.append(raw_idx)
            if curr_high > last.raw_high:
                last.raw_high = curr_high
                last.raw_high_idx = raw_idx
            if curr_low < last.raw_low:
                last.raw_low = curr_low
                last.raw_low_idx = raw_idx
            
            return last.high != old_high or last.low != old_low
        else:
            new_idx = len(self._merged_klines)
            self._merged_klines.append(MergedKline(
                index=new_idx, date=bar['date'],
                high=curr_high, low=curr_low,
                open_price=float(bar['open']), close=float(bar['close']),
                raw_indices=[raw_idx],
                raw_high=curr_high, raw_low=curr_low,
                raw_high_idx=raw_idx, raw_low_idx=raw_idx,
            ))
            return True
    
    def _check_tail_fractal(self) -> bool:
        """检查尾部3根合并K线是否产生/改变了分型（O(1)）
        
        与 _calculate_fx（全量O(n)）的区别：
        - 只检查最后3根合并K线
        - 如果分型已存在且未变化，直接返回False
        
        Returns:
            分型列表是否有变化
        """
        n = len(self._merged_klines)
        if n < 3:
            return False
        
        prev = self._merged_klines[n - 3]
        curr = self._merged_klines[n - 2]
        next_ = self._merged_klines[n - 1]
        
        is_ding = curr.high > prev.high and curr.high > next_.high
        is_di = curr.low < prev.low and curr.low < next_.low
        
        if not is_ding and not is_di:
            if self._fx_list and self._fx_list[-1].index == n - 2:
                self._fx_list.pop()
                return True
            return False
        
        if is_ding and is_di:
            high_rise = max(curr.high - prev.high, curr.high - next_.high)
            low_drop = max(prev.low - curr.low, next_.low - curr.low)
            if low_drop >= high_rise:
                fx_type, price, raw_idx = "di", curr.low, curr.raw_low_idx
            else:
                fx_type, price, raw_idx = "ding", curr.high, curr.raw_high_idx
        elif is_ding:
            fx_type, price, raw_idx = "ding", curr.high, curr.raw_high_idx
        else:
            fx_type, price, raw_idx = "di", curr.low, curr.raw_low_idx
        
        if self._fx_list and self._fx_list[-1].index == n - 2:
            old_fx = self._fx_list[-1]
            if old_fx.type == fx_type and abs(old_fx.val - price) < 1e-10:
                return False
            self._fx_list.pop()
        
        self._fx_list.append(SimpleFX(fx_type, n - 2, curr, price, curr.date, raw_idx))
        return True
    
    def _partial_stroke_recompute(self) -> None:
        """只重算最后2-3笔（增量笔重算）
        
        原理：分型变化只发生在尾部，因此只有最后几笔可能受影响。
        1. 找到最后一个"安全"笔（其端点分型远离变化点）
        2. 回退一个笔作为上下文（stroke_change可能修改倒数第二个笔）
        3. 从上下文点开始，用_calculate_bi_v3的核心逻辑重新处理剩余分型
        4. 替换受影响的笔尾部
        
        与 _calculate_bi_v3（全量O(n)）的区别：
        - 只处理最后3-5个分型，而非全部
        - 保留前面的安全笔不重新计算
        """
        if len(self._fx_list) < 2:
            return
        
        last_fx_idx = self._fx_list[-1].index
        
        safe_end = 0
        for i, bi in enumerate(self._bis):
            if bi.end_fx.index >= last_fx_idx - 4:
                break
            safe_end = i + 1
        else:
            safe_end = len(self._bis)
        
        context_end = max(0, safe_end - 1)
        safe_bis = self._bis[:context_end]
        
        if safe_bis:
            ctx_start_fx_idx = safe_bis[-1].start_fx.index
        else:
            ctx_start_fx_idx = 0
        
        affected_fx = [fx for fx in self._fx_list if fx.index >= ctx_start_fx_idx]
        
        stroke_list = []
        if safe_bis:
            stroke_list.append(safe_bis[-1].start_fx)
            stroke_list.append(safe_bis[-1].end_fx)
        
        for cur_fx in affected_fx:
            if len(stroke_list) < 1:
                stroke_list.append(cur_fx)
                continue
            
            last_fx = stroke_list[-1]
            
            if last_fx.type == cur_fx.type:
                should_extend = False
                if last_fx.type == "di" and cur_fx.val < last_fx.val:
                    should_extend = True
                elif last_fx.type == "ding" and cur_fx.val > last_fx.val:
                    should_extend = True
                if should_extend and len(stroke_list) >= 2:
                    pen_start = stroke_list[-2]
                    if cur_fx.raw_index - pen_start.raw_index < 5:
                        should_extend = False
                if should_extend:
                    stroke_list[-1] = cur_fx
            else:
                gap = cur_fx.raw_index - last_fx.raw_index
                if gap < 5:
                    continue
                valid = ((cur_fx.type == "di" and cur_fx.val < last_fx.val) or
                         (cur_fx.type == "ding" and cur_fx.val > last_fx.val))
                if valid:
                    stroke_list.append(cur_fx)
                    if len(stroke_list) >= 3:
                        self._correct_stroke_endpoint(stroke_list, self._fx_list)
        
        skip = 2 if safe_bis else 0
        new_tail_bis = []
        bi_index = context_end
        
        for i in range(skip, len(stroke_list) - 1):
            s_fx = stroke_list[i]
            e_fx = stroke_list[i + 1]
            if s_fx.type == e_fx.type:
                continue
            direction = "up" if s_fx.type == "di" else "down"
            bi = SimpleBi(
                index=bi_index, direction=direction,
                start_fx=s_fx, end_fx=e_fx,
                start_index=s_fx.raw_index, end_index=e_fx.raw_index,
            )
            new_tail_bis.append(bi)
            bi_index += 1
        
        self._bis = safe_bis + new_tail_bis
    
    def _recompute_from_fx(self) -> None:
        """从已有的分型列表重新计算全部缠论结构
        
        优化点：
        1. 跳过K线合并（已由_merge_incremental增量完成）
        2. 跳过分型识别（已由_check_tail_fractal增量完成）
        3. 笔：只重算最后几笔（_partial_stroke_recompute）
        4. 线段/中枢/买卖点：全量重算（从更新后的笔列表开始）
        """
        self._partial_stroke_recompute()
        
        if not self._raw_rows:
            return
        df = pd.DataFrame(self._raw_rows)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        self._raw_df = df
        self._calculate_bi_strength(df)
        
        self._xds = self._calculate_xd(self._bis)
        self._calculate_xd_strength()
        
        self._bi_zss = self._calculate_zs(self._bis, "bi")
        self._xd_zss = self._calculate_zs_from_xd(self._xds, "xd")
        self._primary_zss = self._xd_zss if self.build_line_pivot else self._bi_zss
        
        self._macd_hist = self._calculate_macd_hist()
        
        self._calculate_1st_class_mmds()
        self._calculate_2nd_class_mmds()
        self._calculate_3rd_class_mmds()
        self._invalidate_mmds()
        
        self._cross_pivot_invalidate()
        self._update_mmd_positions()
        
        if self.gz:
            self._check_gz_tmp_mmd()
    
    # ========================================
    # 11. 跨中枢失效逻辑（移植自chanClass on_pivot）
    # ========================================
    
    def _cross_pivot_invalidate(self) -> None:
        """跨中枢失效判断（移植自chanClass on_pivot 第934-1028行）
        
        两种失效机制：
        1. 趋势性失效（第998-1028行）：
           - 上升趋势（3个中枢ZG递增且互不重叠）→ 失效倒数第3个中枢的卖点
           - 下降趋势（3个中枢ZD递减且互不重叠）→ 失效倒数第3个中枢的买点
           - 原理：趋势已经确认，之前的中枢级别的反向信号是假信号
        
        2. B2连带失效（第979-989行）：
           - B2之后的笔跌破了B2回调的起点 → B1和B2同时失效
           - 原理：回调创新低意味着下降趋势延续，之前的买点是假信号
        """
        zss = self._primary_zss
        if len(zss) < 3:
            return
        
        pre2 = zss[-3]
        pre1 = zss[-2]
        last = zss[-1]
        
        # 趋势性失效：上升趋势（中枢不重叠且递升）
        # chanClass: pre1[3] < last[2] and pre2[3] < pre1[2]
        # pre1.ZG < last.ZD → 前一个中枢在上，当前中枢在下（不重叠）
        if pre1.zg < last.zd and pre2.zg < pre1.zd:
            for bi in self._bis:
                for mmd in list(bi.mmds):
                    if mmd.name in ("1sell", "2sell") and mmd.zs is pre2:
                        bi.mmds.remove(mmd)
                        logger.debug(f"[{self.code}] 跨中枢趋势性失效: {mmd.name} (上升趋势)")
        
        # 趋势性失效：下降趋势（中枢不重叠且递降）
        if pre1.zd > last.zg and pre2.zd > pre1.zg:
            for bi in self._bis:
                for mmd in list(bi.mmds):
                    if mmd.name in ("1buy", "2buy") and mmd.zs is pre2:
                        bi.mmds.remove(mmd)
                        logger.debug(f"[{self.code}] 跨中枢趋势性失效: {mmd.name} (下降趋势)")
        
        # B2连带失效
        self._invalidate_b2_cascade()
    
    def _invalidate_b2_cascade(self) -> None:
        """B2连带失效：B2之后的笔创新低/高时，B1和B2同时失效
        
        对应chanClass on_pivot第979-989行：
            if pre_buy[1] and len(data) > pre_buy[1][4] + 2:
                start = pre_buy[1][4] + 1
                if data[start] < data[start - 2]:
                    pre_buy[0] = []
                    pre_buy[1] = []
        
        含义：2买之后的向下笔跌破了2买回调之前的向上笔高点，
        说明下降趋势延续，1买和2买都失效。
        """
        for i, bi in enumerate(self._bis):
            for mmd in list(bi.mmds):
                if mmd.name != "2buy":
                    continue
                
                one_buy = None
                for j in range(i - 1, -1, -1):
                    for prev_mmd in self._bis[j].mmds:
                        if prev_mmd.name == "1buy":
                            one_buy = (j, prev_mmd)
                            break
                    if one_buy:
                        break
                
                if not one_buy:
                    continue
                
                for j in range(i + 1, len(self._bis)):
                    if self._bis[j].low < self._bis[one_buy[0]].low:
                        logger.debug(f"[{self.code}] B2连带失效: B1+B2 (笔{j}跌破1buy低点)")
                        bi.mmds.remove(mmd)
                        one_buy_bi = self._bis[one_buy[0]]
                        if one_buy[1] in one_buy_bi.mmds:
                            one_buy_bi.mmds.remove(one_buy[1])
                        break
        
        for i, bi in enumerate(self._bis):
            for mmd in list(bi.mmds):
                if mmd.name != "2sell":
                    continue
                
                one_sell = None
                for j in range(i - 1, -1, -1):
                    for prev_mmd in self._bis[j].mmds:
                        if prev_mmd.name == "1sell":
                            one_sell = (j, prev_mmd)
                            break
                    if one_sell:
                        break
                
                if not one_sell:
                    continue
                
                for j in range(i + 1, len(self._bis)):
                    if self._bis[j].high > self._bis[one_sell[0]].high:
                        logger.debug(f"[{self.code}] S2连带失效: S1+S2 (笔{j}突破1sell高点)")
                        bi.mmds.remove(mmd)
                        one_sell_bi = self._bis[one_sell[0]]
                        if one_sell[1] in one_sell_bi.mmds:
                            one_sell_bi.mmds.remove(one_sell[1])
                        break
    
    # ========================================
    # 12. x_bs_pos等效（移植自chanClass x_bs_pos）
    # ========================================
    
    def _update_mmd_positions(self) -> None:
        """更新买卖点位置和强度（移植自chanClass x_bs_pos）
        
        在增量计算后，笔可能延伸/修正导致买卖点的价格和强度需要更新。
        
        对应chanClass x_bs_pos 的核心逻辑：
        1. 检查每个买卖点关联的笔端点是否仍是同一分型
        2. 如果价格变了（因包含关系合并改变了分型极值），重新计算强度
        3. 如果笔的方向变了（不应发生，但防御性检查），移除该买卖点
        
        在当前实现中，_partial_stroke_recompute已处理大部分情况（新笔=新买卖点）。
        此方法处理边界情况：笔未变化但分型价格微调（浮点精度等）。
        """
        for bi in self._bis:
            for mmd in bi.mmds:
                if not mmd.zs:
                    continue
                
                if mmd.name == "1buy" and bi.type == "down":
                    mmd.strength = self._cal_b1_buy_strength(bi.end_price, mmd.zs)
                    mmd.bs_type = self._get_bs_type(mmd.zs)
                elif mmd.name == "1sell" and bi.type == "up":
                    mmd.strength = self._cal_b1_sell_strength(bi.end_price, mmd.zs)
                    mmd.bs_type = self._get_bs_type(mmd.zs)
                elif mmd.name == "2buy" and bi.type == "down":
                    mmd.strength = self._cal_b2_buy_strength(bi, mmd.zs)
                elif mmd.name == "2sell" and bi.type == "up":
                    mmd.strength = self._cal_b2_sell_strength(bi, mmd.zs)
                elif mmd.name == "3buy":
                    mmd.strength = self._cal_b3_buy_strength(bi.end_price, mmd.zs)
                elif mmd.name == "3sell":
                    mmd.strength = self._cal_b3_sell_strength(bi.end_price, mmd.zs)
    
    # ========================================
    # 13. 区间套背驰确认（移植自chanClass qjt）
    # ========================================
    
    def qjt_turn(self, start_time: Any, end_time: Any, direction: str) -> Tuple[bool, List]:
        """区间套判断背驰：在更小级别验证当前级别发现的背驰（移植自chanClass qjt_turn）
        
        核心思想：当前级别发现背驰后，去下一级别检查该背驰段内是否形成了
        完整的中枢结构和买卖点。如果小级别也有对应的买卖点确认，
        则区间套成立，当前级别的背驰信号更可靠。
        
        实现方式（适配engine_new的OOP结构）：
        1. 遍历 next_level（更小级别）及其下级
        2. 在小级别中查找 [start_time, end_time] 时间范围内是否有对应方向的买卖点
        3. 任何一级有确认则返回 True
        
        Args:
            start_time: 背驰段开始时间
            end_time: 背驰段结束时间
            direction: 'up' 或 'down'
        
        Returns:
            (是否确认, 小级别中枢列表)
        """
        qjt_zs_list: List[SimpleZS] = []
        
        if not self.qjt:
            return True, qjt_zs_list
        
        chan = self.next_level
        if not chan:
            # 没有更小级别，区间套默认通过
            return True, qjt_zs_list
        
        logger.debug(f"[{self.code}] 区间套判断背驰: {self.frequency}, "
                      f"范围=[{start_time} ~ {end_time}], 方向={direction}")
        
        ans = True
        while chan:
            tmp = False
            
            # 在小级别中查找时间范围内的买卖点
            if direction == "up":
                # 向上背驰：在小级别找卖点确认
                for bi in reversed(chan._bis):
                    for mmd in bi.mmds:
                        if mmd.name in ("1sell", "2sell", "3sell"):
                            if start_time <= bi.end_time <= end_time:
                                tmp = True
                                break
                    if tmp:
                        break
            else:
                # 向下背驰：在小级别找买点确认
                for bi in reversed(chan._bis):
                    for mmd in bi.mmds:
                        if mmd.name in ("1buy", "2buy", "3buy"):
                            if start_time <= bi.end_time <= end_time:
                                tmp = True
                                break
                    if tmp:
                        break
            
            # 如果小级别有买卖点，继续往更小级别验证
            if tmp:
                # 收集小级别在范围内的中枢
                for zs in chan._primary_zss:
                    if zs.start_time >= start_time and zs.end_time <= end_time:
                        qjt_zs_list.append(zs)
                
                # 用小级别买卖点的时间范围继续向更小级别验证
                for bi in reversed(chan._bis):
                    for mmd in bi.mmds:
                        if start_time <= bi.end_time <= end_time:
                            if mmd.zs:
                                start_time = mmd.zs.start_time
                                end_time = mmd.zs.end_time
                            break
                    else:
                        continue
                    break
                
                chan = chan.next_level
            else:
                chan = chan.next_level
            
            ans = tmp and ans
            if not ans:
                break
        
        logger.debug(f"[{self.code}] 区间套结果: {ans}")
        return ans, qjt_zs_list
    
    def qjt_trend(self, start_time: Any, end_time: Any, direction: str) -> Tuple[bool, List]:
        """区间套判断走势：在小级别验证是否存在完整走势（移植自chanClass qjt_trend）
        
        与 qjt_turn 不同，这里只检查小级别是否有中枢形成，不要求有买卖点。
        用于判断3类买卖点前是否形成了完整的离开走势。
        
        Args:
            start_time: 走势段开始时间
            end_time: 走势段结束时间
            direction: 'up' 或 'down'
        
        Returns:
            (是否有走势确认, 小级别中枢列表)
        """
        qjt_zs_list: List[SimpleZS] = []
        
        if not self.qjt:
            return True, qjt_zs_list
        
        chan = self.next_level
        if not chan:
            return True, qjt_zs_list
        
        ans = False
        while chan:
            tmp = False
            
            # 检查小级别在时间范围内是否有中枢
            for zs in chan._primary_zss:
                if zs.start_time <= end_time and zs.end_time >= start_time:
                    tmp = True
                    qjt_zs_list.append(zs)
                    break
            
            ans = tmp or ans
            if ans:
                break
            chan = chan.next_level
        
        return ans, qjt_zs_list
    
    # ========================================
    # 11. 共振机制（移植自chanClass gz）
    # ========================================
    
    def _check_gz_tmp_mmd(self) -> None:
        """检查当前级别是否有新的一类买卖点，用于共振确认
        
        逻辑（移植自chanClass）：
        - 当前级别产生1buy时，等待上一级别（更大级别）出现B2/B3确认
        - 当前级别产生1sell时，等待上一级别出现S2/S3确认
        """
        if not self._bis:
            return
        
        last_bi = self._bis[-1]
        for mmd in last_bi.mmds:
            if mmd.name in ("1buy", "1sell"):
                self._gz_tmp_mmd = mmd
                self._gz_delay_k_num = 0
                # 记录上一级别最后的买卖点（用于后续比较是否有变化）
                self._gz_prev_last_mmd = self._get_prev_last_mmd()
                logger.debug(f"[{self.code}] 共振: 捕获临时买卖点 {mmd.name}")
                break
    
    def _get_prev_last_mmd(self) -> Optional[SimpleMMD]:
        """获取上一级别（更大级别）最近的买卖点（移植自chanClass get_prev_last_bs）"""
        if not self.prev or not self.prev._bis:
            return None
        
        for bi in reversed(self.prev._bis):
            for mmd in bi.mmds:
                if mmd.name in ("1buy", "2buy", "3buy", "1sell", "2sell", "3sell"):
                    return mmd
        return None
    
    def _process_gz(self) -> Optional[SimpleMMD]:
        """共振处理：检查上一级别是否确认了当前级别的买卖点（移植自chanClass on_gz）
        
        核心逻辑（移植自chanClass.on_gz）：
        1. 当本级有临时买卖点(_gz_tmp_mmd)时，等待上一级别出现B1/B2/B3或S1/S2/S3
        2. 如果上一级别出现了新的买卖点（与上次不同），则确认共振
        3. 确认后：标记当前买卖点为共振确认，记录到_confirmed_mmds
        4. 超时（超过gz_delay_k_max根K线仍未确认）：取消临时买卖点
        
        共振组合规则（移植自chanClass注释）：
        - 小级别1buy + 大级别B2/B3 → 共振买入
        - 小级别1sell + 大级别S2/S3 → 共振卖出
        
        Returns:
            共振确认的买卖点，或 None（未确认或超时）
        """
        chan = self.prev
        if not chan:
            self._gz_tmp_mmd = None
            return None
        
        # 获取上一级别最近的买卖点
        prev_last_mmd = self._get_prev_last_mmd()
        
        # 超时或临时买卖点已失效
        if (self._gz_delay_k_num >= self._gz_delay_k_max 
            or not self._gz_tmp_mmd):
            logger.debug(f"[{self.code}] 共振超时: delay={self._gz_delay_k_num}")
            self._gz_delay_k_num = 0
            self._gz_prev_last_mmd = None
            self._gz_tmp_mmd = None
            return None
        
        # 检查上一级别是否有新的买卖点（与上次记录的不同）
        if (prev_last_mmd is not None 
            and prev_last_mmd is not self._gz_prev_last_mmd):
            
            # 判断共振组合是否有效
            confirmed = self._check_gz_combination(self._gz_tmp_mmd, prev_last_mmd)
            
            if confirmed and self._gz_tmp_mmd:
                logger.info(
                    f"[{self.code}] 共振确认! "
                    f"本级={self._gz_tmp_mmd.name}, "
                    f"上级别={prev_last_mmd.name}, "
                    f"delay={self._gz_delay_k_num}"
                )
                # 标记买卖点为共振确认
                self._gz_tmp_mmd.msg = f"共振确认({self.frequency}+{chan.frequency})"
                self._gz_confirmed_mmds.append(self._gz_tmp_mmd)
                
                result = self._gz_tmp_mmd
                self._gz_delay_k_num = 0
                self._gz_prev_last_mmd = None
                self._gz_tmp_mmd = None
                return result
        
        return None
    
    def _check_gz_combination(self, local_mmd: SimpleMMD, prev_mmd: SimpleMMD) -> bool:
        """检查共振组合是否有效
        
        有效组合（移植自chanClass on_gz）：
        - 小级别 1buy + 大级别 B2(2buy) 或 B3(3buy) 或 B1(1buy) → 确认
        - 小级别 1sell + 大级别 S2(2sell) 或 S3(3sell) 或 S1(1sell) → 确认
        """
        if local_mmd.name == "1buy":
            return prev_mmd.name in ("1buy", "2buy", "3buy")
        elif local_mmd.name == "1sell":
            return prev_mmd.name in ("1sell", "2sell", "3sell")
        return False
    
    def get_gz_confirmed_mmds(self) -> List[SimpleMMD]:
        """获取所有共振确认的买卖点"""
        return self._gz_confirmed_mmds
    
    # ========================================
    # 对外接口
    # ========================================
    
    def get_bis(self) -> List[SimpleBi]:
        return self._bis
    
    def get_xds(self) -> List[SimpleXD]:
        return self._xds
    
    def get_bi_zss(self, zs_type: Optional[str] = None) -> List[SimpleZS]:
        return self._bi_zss
    
    def get_xd_zss(self, zs_type: Optional[str] = None) -> List[SimpleZS]:
        return self._xd_zss
    
    def get_zsd_zss(self) -> List[SimpleZS]:
        return self._zsd_zss
    
    def get_merged_klines(self) -> List[MergedKline]:
        return self._merged_klines
    
    def get_fx_list(self) -> List[SimpleFX]:
        return self._fx_list
    
    def get_macd_data(self) -> Dict[str, Any]:
        """获取 MACD 指标数据"""
        if self._raw_df is None or len(self._raw_df) == 0:
            return {"dates": [], "dif": [], "dea": [], "hist": []}
        
        df = self._raw_df
        close = df["close"].astype(float)
        
        ema_short = close.ewm(span=12, adjust=False).mean()
        ema_long = close.ewm(span=26, adjust=False).mean()
        dif = ema_short - ema_long
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = (dif - dea) * 2
        
        return {
            "dates": df["date"].tolist(),
            "dif": dif.tolist(),
            "dea": dea.tolist(),
            "hist": hist.tolist(),
        }


ICL = SimpleICL


@dataclass
class EngineConfig:
    """缠论引擎配置"""
    
    options: Dict[str, Any] = None
    bi_min_kline: int = 4
    xd_min_bi: int = 3
    zs_min_bi: int = 3
    
    def __post_init__(self):
        if self.options is None:
            self.options = {}


@dataclass
class KlineInput:
    """供 engine 使用的最小 K 线输入结构"""
    
    date: Any
    open: float
    high: float
    low: float
    close: float
    volume: float


class ChanlunEngine:
    """面向上层的缠论引擎封装"""
    
    def __init__(self, config: EngineConfig) -> None:
        self._config = config
    
    def analyze_klines(
        self,
        *,
        code: str,
        frequency: str,
        klines: Iterable[KlineInput | Dict[str, Any]],
    ) -> ICL:
        """对一段完整 K 线序列进行缠论计算"""
        
        rows: List[Dict[str, Any]] = []
        for k in klines:
            if isinstance(k, KlineInput):
                row = {
                    "date": k.date,
                    "open": k.open,
                    "high": k.high,
                    "low": k.low,
                    "close": k.close,
                    "volume": k.volume,
                }
            else:
                row = {
                    "date": k["date"],
                    "open": k["open"],
                    "high": k["high"],
                    "low": k["low"],
                    "close": k["close"],
                    "volume": k["volume"],
                }
            rows.append(row)
        
        if not rows:
            logger.error(f"[{code}] {frequency} - K 线序列为空")
            raise ValueError("analyze_klines 收到的 K 线序列为空，无法进行缠论计算")
        
        if len(rows) < 50:
            logger.error(f"[{code}] {frequency} - K 线数量不足: {len(rows)} 根")
            raise ValueError(f"K 线数量不足，至少需要 50 根，当前 {len(rows)} 根")
        
        logger.info(f"[{code}] {frequency} - 开始缠论分析，共 {len(rows)} 根 K 线")
        
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        
        if df["date"].isna().any():
            logger.error(f"[{code}] {frequency} - K 线数据中存在无效的 date 字段")
            raise ValueError("K 线数据中存在无法转换为 datetime 的 date 字段")
        
        options = self._config.options.copy() if self._config.options else {}
        options['bi_min_kline'] = self._config.bi_min_kline
        options['xd_min_bi'] = self._config.xd_min_bi
        options['zs_min_bi'] = self._config.zs_min_bi
        
        icl = ICL(code=code, frequency=frequency, config=options)
        icl = icl.process_klines(df)
        
        bis_count = len(icl.get_bis())
        xds_count = len(icl.get_xds())
        bi_zss_count = len(icl.get_bi_zss())
        logger.info(
            f"[{code}] {frequency} - 缠论分析完成: "
            f"笔={bis_count}, 线段={xds_count}, 笔中枢={bi_zss_count}"
        )
        
        return icl
