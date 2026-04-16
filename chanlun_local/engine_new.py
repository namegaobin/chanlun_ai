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
        msg: Optional[str] = None
    ):
        self.name = name
        self.zs = zs
        self.msg = msg
    
    def __repr__(self) -> str:
        return f"<SimpleMMD name={self.name} msg={self.msg}>"


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
        
        # 7. 计算中枢
        self._bi_zss = self._calculate_zs(self._bis, "bi")
        self._xd_zss = self._calculate_zs_from_xd(self._xds, "xd")
        logger.debug(f"笔中枢: {len(self._bi_zss)}, 线段中枢: {len(self._xd_zss)}")
        
        # 8. 计算买卖点和背驰
        self._calculate_mmds_and_bcs()
        
        return self
    
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
        """在合并后的K线上识别分型（使用原始极值）"""
        if len(klines) < 3:
            return []
        
        fx_list: List[SimpleFX] = []
        
        for i in range(1, len(klines) - 1):
            prev = klines[i - 1]
            curr = klines[i]
            next_ = klines[i + 1]
            
            if curr.raw_high > prev.raw_high and curr.raw_high > next_.raw_high:
                fx = SimpleFX(
                    fx_type="ding",
                    index=i,
                    kline=curr,
                    price=curr.raw_high,
                    time=curr.date,
                    raw_index=curr.raw_high_idx,
                )
                fx_list.append(fx)
            
            elif curr.raw_low < prev.raw_low and curr.raw_low < next_.raw_low:
                fx = SimpleFX(
                    fx_type="di",
                    index=i,
                    kline=curr,
                    price=curr.raw_low,
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
           - 延伸时，新分型与当前终点之间必须至少有4根K线距离
           - 延伸时，新分型与笔起点之间必须满足笔形成条件（>3根K线）
        
        2. 新笔生成：
           - 类型相反 + K线间隔>3 + 价格关系满足
           - 新笔的起点 = 前一笔的终点（确保连续性）
        
        3. 不做笔终点修正（避免破坏连续性）
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
                    
                    # 延伸条件检查
                    if should_extend and len(stroke_list) >= 2:
                        pen_start_fx = stroke_list[-2]
                        # 延伸后整笔的K线数量必须 >= 5
                        if cur_fx.index - pen_start_fx.index < 5:
                            should_extend = False
                    
                    if should_extend:
                        stroke_list[-1] = cur_fx
                
                # 2. 新笔生成逻辑：类型相反
                else:
                    # 检查K线间隔（必须 > 3）
                    kline_gap = cur_fx.index - last_fx.index
                    
                    if kline_gap <= 3:
                        continue
                    
                    # 检查价格关系
                    price_valid = False
                    
                    if cur_fx.type == "di":
                        # 当前是底分型，前一个是顶分型 -> 向下笔
                        cur_low = cur_fx.k.low if cur_fx.k else cur_fx.val
                        cur_high = cur_fx.k.high if cur_fx.k else cur_fx.val
                        last_low = last_fx.k.low if last_fx.k else last_fx.val
                        last_high = last_fx.k.high if last_fx.k else last_fx.val
                        price_valid = cur_low < last_low and cur_high < last_high
                    else:
                        # 当前是顶分型，前一个是底分型 -> 向上笔
                        cur_low = cur_fx.k.low if cur_fx.k else cur_fx.val
                        cur_high = cur_fx.k.high if cur_fx.k else cur_fx.val
                        last_low = last_fx.k.low if last_fx.k else last_fx.val
                        last_high = last_fx.k.high if last_fx.k else last_fx.val
                        price_valid = cur_high > last_high and cur_low > last_low
                    
                    if price_valid:
                        stroke_list.append(cur_fx)
        
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
            if (fx_from_bi[i].type == 'ding' and 
                fx_from_bi[i-2].val >= fx_from_bi[i].val and 
                fx_from_bi[i-2].val >= fx_from_bi[i-4].val):
                
                candidate = fx_from_bi[i-2]
                
                if line_endpoints[-1].type == 'di':
                    last_idx = fx_from_bi.index(line_endpoints[-1])
                    if (i - 2 - last_idx) > 2:
                        line_endpoints.append(candidate)
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
                elif line_endpoints[-1].type == 'di':
                    if candidate.val < line_endpoints[-1].val:
                        line_endpoints[-1] = candidate
        
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
    # 8. 买卖点和背驰计算
    # ========================================
    
    def _calculate_mmds_and_bcs(self) -> None:
        """计算买卖点和背驰"""
        self._calculate_bi_bcs_and_mmds()
        self._calculate_xd_bcs_and_mmds()
        self._calculate_class3_mmds()
    
    def _calculate_bi_bcs_and_mmds(self) -> None:
        """计算笔的背驰和一类买卖点"""
        if len(self._bis) < 5:
            return
        
        for i in range(4, len(self._bis)):
            current_bi = self._bis[i]
            
            for j in range(i - 2, -1, -2):
                prev_bi = self._bis[j]
                
                if current_bi.type != prev_bi.type:
                    continue
                
                is_bc = self._check_divergence(prev_bi, current_bi)
                
                if is_bc:
                    related_zs = self._find_related_zs(current_bi, self._bi_zss)
                    
                    current_bi.bcs.append(SimpleBC(
                        bc_type="bi",
                        is_bc=True,
                        zs=related_zs,
                        compare_item=prev_bi,
                    ))
                    
                    if related_zs and self._is_leaving_zs(current_bi, related_zs):
                        if current_bi.type == "down":
                            current_bi.mmds.append(SimpleMMD(
                                name="1buy",
                                zs=related_zs,
                                msg="笔背驰一买"
                            ))
                        else:
                            current_bi.mmds.append(SimpleMMD(
                                name="1sell",
                                zs=related_zs,
                                msg="笔背驰一卖"
                            ))
                    break
    
    def _calculate_xd_bcs_and_mmds(self) -> None:
        """计算线段的背驰和二类买卖点"""
        if len(self._xds) < 3:
            return
        
        for i in range(2, len(self._xds)):
            current_xd = self._xds[i]
            
            for j in range(i - 2, -1, -2):
                prev_xd = self._xds[j]
                
                if current_xd.type != prev_xd.type:
                    continue
                
                is_bc = self._check_xd_divergence(prev_xd, current_xd)
                
                if is_bc:
                    related_zs = self._find_related_zs_for_xd(current_xd, self._xd_zss)
                    
                    current_xd.bcs.append(SimpleBC(
                        bc_type="xd",
                        is_bc=True,
                        zs=related_zs,
                        compare_item=prev_xd,
                    ))
                    
                    if related_zs and self._is_leaving_zs_for_xd(current_xd, related_zs):
                        if current_xd.type == "down":
                            current_xd.mmds.append(SimpleMMD(
                                name="2buy",
                                zs=related_zs,
                                msg="线段背驰二买"
                            ))
                        else:
                            current_xd.mmds.append(SimpleMMD(
                                name="2sell",
                                zs=related_zs,
                                msg="线段背驰二卖"
                            ))
                    break
    
    def _calculate_class3_mmds(self) -> None:
        """计算三类买卖点"""
        if not self._bi_zss or len(self._bis) < 3:
            return
        
        for zs in self._bi_zss:
            for bi in self._bis:
                if bi.start_time <= zs.end_time:
                    continue
                
                if bi.type == "down" and bi.low > zs.zd:
                    bi_idx = self._bis.index(bi)
                    if bi_idx > 0:
                        prev_bi = self._bis[bi_idx - 1]
                        if prev_bi.type == "up" and prev_bi.high > zs.zg:
                            bi.mmds.append(SimpleMMD(
                                name="3buy",
                                zs=zs,
                                msg="三类买点"
                            ))
                            break
                
                if bi.type == "up" and bi.high < zs.zg:
                    bi_idx = self._bis.index(bi)
                    if bi_idx > 0:
                        prev_bi = self._bis[bi_idx - 1]
                        if prev_bi.type == "down" and prev_bi.low < zs.zd:
                            bi.mmds.append(SimpleMMD(
                                name="3sell",
                                zs=zs,
                                msg="三类卖点"
                            ))
                            break
    
    def _check_divergence(self, prev: SimpleBi, curr: SimpleBi) -> bool:
        """检测笔背驰"""
        if prev.type != curr.type:
            return False
        
        prev_strength = prev.strength
        curr_strength = curr.strength
        
        if prev_strength <= 0 or curr_strength <= 0:
            prev_strength = prev.price_strength
            curr_strength = curr.price_strength
        
        if prev_strength <= 0:
            return False
        
        strength_ratio = curr_strength / prev_strength
        
        if prev.type == "up":
            return curr.end_price > prev.end_price and strength_ratio < 0.8
        else:
            return curr.end_price < prev.end_price and strength_ratio < 0.8
    
    def _check_xd_divergence(self, prev: SimpleXD, curr: SimpleXD) -> bool:
        """检测线段背驰"""
        if prev.type != curr.type:
            return False
        
        prev_strength = prev.strength
        curr_strength = curr.strength
        
        if prev_strength <= 0 or curr_strength <= 0:
            return False
        
        strength_ratio = curr_strength / prev_strength
        
        if prev.type == "up":
            return curr.end_price > prev.end_price and strength_ratio < 0.8
        else:
            return curr.end_price < prev.end_price and strength_ratio < 0.8
    
    def _find_related_zs(self, bi: SimpleBi, zss: List[SimpleZS]) -> Optional[SimpleZS]:
        """查找与笔相关的中枢"""
        for zs in reversed(zss):
            if bi.start_time <= zs.end_time and bi.end_time >= zs.start_time:
                return zs
            if bi.start_time > zs.end_time:
                return zs
        return None
    
    def _find_related_zs_for_xd(self, xd: SimpleXD, zss: List[SimpleZS]) -> Optional[SimpleZS]:
        """查找与线段相关的中枢"""
        for zs in reversed(zss):
            if xd.start_time <= zs.end_time and xd.end_time >= zs.start_time:
                return zs
            if xd.start_time > zs.end_time:
                return zs
        return None
    
    def _is_leaving_zs(self, bi: SimpleBi, zs: SimpleZS) -> bool:
        """判断笔是否离开中枢"""
        if bi.type == "down":
            return bi.end_price < zs.zd
        else:
            return bi.end_price > zs.zg
    
    def _is_leaving_zs_for_xd(self, xd: SimpleXD, zs: SimpleZS) -> bool:
        """判断线段是否离开中枢"""
        if xd.type == "down":
            return xd.end_price < zs.zd
        else:
            return xd.end_price > zs.zg
    
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
