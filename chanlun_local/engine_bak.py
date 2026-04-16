"""缠论引擎封装（engine）- 改进版

本模块的职责：
- 接收已经准备好的、完整的 K 线数据序列（不裁剪、不修改）
- 进行缠论结构计算（笔、线段、中枢等）
- 返回 ICL 对象，供上层按需读取笔、线段、中枢、买卖点、背驰等结构

改进内容（v2.0）：
1. K线包含关系处理 - 合并K线后再识别分型
2. 分型识别完善 - 严格的顶底分型判断
3. 笔算法改进 - 正确处理分型连接和笔的延伸
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
        raw_high: float = None,  # 原始最高价（合并前所有K线的最高价）
        raw_low: float = None,   # 原始最低价（合并前所有K线的最低价）
    ):
        self.index = index  # 合并后的索引
        self.date = date
        self.high = high
        self.low = low
        self.open = open_price
        self.close = close
        self.raw_indices = raw_indices or [index]  # 原始K线索引列表
        # 保留原始极值（用于分型识别，确保不会丢失极端点）
        self.raw_high = raw_high if raw_high is not None else high
        self.raw_low = raw_low if raw_low is not None else low
    
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
        self.index = index   # 在合并K线列表中的索引
        self.k = kline       # 中间那根K线
        self.val = price     # 分型价格（顶分型取high，底分型取low）
        self.time = time
        self.raw_index = raw_index or index  # 原始K线索引
    
    def __repr__(self):
        return f"<SimpleFX type={self.type} idx={self.index} price={self.val:.2f}>"


class SimpleKline:
    """简化的 K 线对象（用于兼容 mapper.py）"""
    def __init__(self, date: Any, high: float, low: float, close: float):
        self.date = date
        self.high = high
        self.low = low
        self.close = close


class SimpleBi:
    """笔对象（改进版）"""
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
        
        # 分型信息
        self.start_fx = start_fx
        self.end_fx = end_fx
        
        # K 线索引范围（用于力度计算）
        self.start_index = start_index
        self.end_index = end_index
        
        # 时间与价格信息
        self.start_time = start_fx.time
        self.end_time = end_fx.time
        self.start_price = float(start_fx.val)
        self.end_price = float(end_fx.val)
        
        # 兼容 mapper.py 的分型结构
        start_kline = SimpleKline(self.start_time, self.start_price, self.start_price, self.start_price)
        end_kline = SimpleKline(self.end_time, self.end_price, self.end_price, self.end_price)
        self.start = SimpleFX("di" if direction == "up" else "ding", start_fx.index, start_fx.k, self.start_price, self.start_time)
        self.end = SimpleFX("ding" if direction == "up" else "di", end_fx.index, end_fx.k, self.end_price, self.end_time)
        
        # 高低点
        if direction == "up":
            self.high = self.end_price
            self.low = self.start_price
        else:
            self.high = self.start_price
            self.low = self.end_price
        
        # 力度（多维度），默认 0
        self.strength: float = 0.0
        self.macd_strength: float = 0.0
        self.price_strength: float = 0.0
        self.slope_strength: float = 0.0
        
        # 买卖点和背驰列表
        self.mmds: List[Any] = []
        self.bcs: List[Any] = []
    
    def is_done(self) -> bool:
        """判断笔是否完成"""
        return self._is_done
    
    def __repr__(self):
        return (
            f"<SimpleBi index={self.index} type={self.type} "
            f"start={self.start_price:.2f} end={self.end_price:.2f} done={self._is_done}>"
        )


class SimpleXD:
    """线段对象（改进版）"""
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
        
        # 线段覆盖的笔
        self.bi_list = bi_list
        self.start_bi_index = start_bi.index
        self.end_bi_index = end_bi.index
        
        # 时间与价格信息
        self.start_time = start_bi.start_time
        self.end_time = end_bi.end_time
        
        # 根据线段方向确定起止价格（确保连续性）
        # 向上线段：从底分型开始 → 第一笔终点价格
        # 向下线段：从顶分型开始 → 第一笔起点价格
        if direction == "up":
            # 向上线段：第一笔是向下笔，终点是底分型
            self.start_price = start_bi.end_price
            self.end_price = end_bi.end_price
        else:
            # 向下线段：第一笔是向上笔，起点是顶分型
            self.start_price = start_bi.start_price
            self.end_price = end_bi.end_price
        
        # 兼容 mapper.py 的分型结构
        start_kline = SimpleKline(self.start_time, self.start_price, self.start_price, self.start_price)
        end_kline = SimpleKline(self.end_time, self.end_price, self.end_price, self.end_price)
        self.start = SimpleFX("di" if direction == "up" else "ding", 0, None, self.start_price, self.start_time)
        self.end = SimpleFX("ding" if direction == "up" else "di", 0, None, self.end_price, self.end_time)
        
        # 高低点和分型
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
        
        # 力度
        self.strength: float = 0.0
        
        # 买卖点和背驰列表
        self.mmds: List[Any] = []
        self.bcs: List[Any] = []
    
    def is_done(self) -> bool:
        return self._is_done
    
    def __repr__(self) -> str:
        return (
            f"<SimpleXD index={self.index} type={self.type} "
            f"start={self.start_price:.2f} end={self.end_price:.2f} bis={len(self.bi_list)}>"
        )


class SimpleZS:
    """中枢对象（改进版）"""
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
        self.zs_type = zs_type  # "bi" 笔中枢 / "xd" 线段中枢
        self.direction = direction  # "up" / "down" / "zd"（震荡）
        
        # 时间信息
        self.start_time = start_time
        self.end_time = end_time
        
        # 中枢的四个关键价格
        self.zg = zg  # 中枢高点（ZG）
        self.zd = zd  # 中枢低点（ZD）
        self.gg = gg  # 高高点（GG）
        self.dd = dd  # 低低点（DD）
        
        # 兼容旧版字段
        self.high = zg
        self.low = zd
        self.type = direction
        
        # 中枢状态
        self.level = level
        self.relation = relation  # "new" / "extend" / "up_trend" / "down_trend"
        self.bi_count = bi_count
        self.done = True
        self.real = True
    
    def __repr__(self) -> str:
        return (
            f"<SimpleZS index={self.index} type={self.zs_type} "
            f"direction={self.direction} ZG={self.zg:.2f} ZD={self.zd:.2f} "
            f"GG={self.gg:.2f} DD={self.dd:.2f}>"
        )


class SimpleBC:
    """背驰对象"""
    def __init__(
        self,
        bc_type: str,
        is_bc: bool = True,
        zs: Optional[SimpleZS] = None,
        compare_item: Any = None,
    ):
        self.type = bc_type  # "bi" / "xd" / "zsd" / "pz" / "qs"
        self.bc = is_bc
        self.zs = zs
        self.compare_item = compare_item  # 对比的笔/线段
    
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
        self.name = name  # "1buy"/"2buy"/"3buy"/"1sell"/"2sell"/"3sell"
        self.zs = zs
        self.msg = msg
    
    def __repr__(self) -> str:
        return f"<SimpleMMD name={self.name} msg={self.msg}>"


# ============================================================
# 缠论引擎核心类（改进版）
# ============================================================

class SimpleICL:
    """缠论引擎核心类（改进版 v2.0）
    
    改进内容：
    1. K线包含关系处理
    2. 严格的分型识别
    3. 正确的笔划分
    4. 基于特征序列的线段划分
    5. 完善的中枢计算
    6. 多维度背驰判断
    """
    
    def __init__(self, code: str, frequency: str, config: Dict[str, Any]):
        self.code = code
        self.frequency = frequency
        self.config = config or {}
        
        # 算法参数
        self.bi_min_kline = self.config.get('bi_min_kline', 5)  # 笔的最小K线数量（合并后）
        self.xd_min_bi = self.config.get('xd_min_bi', 3)  # 线段的最小笔数量
        self.zs_min_bi = self.config.get('zs_min_bi', 5)  # 中枢的最小笔数量
        
        # 中间结果
        self._merged_klines: List[MergedKline] = []
        self._fx_list: List[SimpleFX] = []
        
        # 缠论结构结果
        self._bis: List[SimpleBi] = []
        self._xds: List[SimpleXD] = []
        self._bi_zss: List[SimpleZS] = []
        self._xd_zss: List[SimpleZS] = []
        self._zsd_zss: List[SimpleZS] = []
        
        # 原始数据
        self._raw_df: pd.DataFrame = None
    
    def process_klines(self, df: pd.DataFrame) -> "SimpleICL":
        """对 K 线进行缠论结构计算
        
        计算流程：
        1. K线包含关系处理（合并K线）
        2. 在合并K线上识别分型
        3. 根据分型生成笔
        4. 根据笔生成线段（特征序列法）
        5. 计算中枢
        6. 计算买卖点和背驰
        """
        if len(df) == 0:
            return self
        
        # 保存原始数据
        self._raw_df = df.copy()
        
        # 确保 df 有必要的字段
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
        
        # 3. 生成笔
        self._bis = self._calculate_bi(self._fx_list, self._merged_klines)
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
        """处理K线包含关系
        
        包含关系定义：
        - 当前K线的高低点完全在前一K线的高低点范围内，或反之
        - 即：(H1 >= H2 and L1 <= L2) 或 (H2 >= H1 and L2 <= L1)
        
        合并规则：
        - 向上趋势：取两根K线的 max(high), max(low)
        - 向下趋势：取两根K线的 min(high), min(low)
        
        趋势判断：
        - 比较合并后的最新K线与前一K线的高点
        """
        if len(df) < 2:
            return [MergedKline(
                index=0,
                date=df.iloc[0]['date'],
                high=float(df.iloc[0]['high']),
                low=float(df.iloc[0]['low']),
                open_price=float(df.iloc[0]['open']),
                close=float(df.iloc[0]['close']),
                raw_indices=[0],
            )] if len(df) == 1 else []
        
        merged: List[MergedKline] = []
        
        # 第一根K线直接加入
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
        ))
        
        for i in range(1, len(df)):
            row = df.iloc[i]
            curr_high = float(row['high'])
            curr_low = float(row['low'])
            
            prev = merged[-1]
            prev_high = prev.high
            prev_low = prev.low
            
            # 检查是否存在包含关系
            has_contain = (
                (curr_high <= prev_high and curr_low >= prev_low) or  # 当前被前一个包含
                (curr_high >= prev_high and curr_low <= prev_low)     # 当前包含前一个
            )
            
            if has_contain:
                # 确定趋势方向
                if len(merged) >= 2:
                    direction = "up" if merged[-1].high > merged[-2].high else "down"
                else:
                    # 只有一根K线时，看当前K线的趋势
                    direction = "up" if curr_high > prev_high or curr_low > prev_low else "down"
                
                # 合并K线
                if direction == "up":
                    # 向上趋势：取高高、高低
                    new_high = max(curr_high, prev_high)
                    new_low = max(curr_low, prev_low)
                else:
                    # 向下趋势：取低高、低低
                    new_high = min(curr_high, prev_high)
                    new_low = min(curr_low, prev_low)
                
                # 更新最后一根合并K线
                prev.high = new_high
                prev.low = new_low
                prev.raw_indices.append(i)
                # 保持日期为最后一根的日期
                prev.date = row['date']
                # ⭐ 保留原始极值（确保不丢失极端点）
                prev.raw_high = max(prev.raw_high, curr_high)
                prev.raw_low = min(prev.raw_low, curr_low)
            else:
                # 无包含关系，直接添加新K线
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
                ))
        
        return merged
    
    # ========================================
    # 2. 分型识别
    # ========================================
    
    def _calculate_fx(self, klines: List[MergedKline]) -> List[SimpleFX]:
        """在合并后的K线上识别分型（使用原始极值）
        
        顶分型：中间K线的原始最高点是三根K线中最高的
        底分型：中间K线的原始最低点是三根K线中最低的
        
        严格条件：
        - 顶分型：k[i].raw_high > k[i-1].raw_high AND k[i].raw_high > k[i+1].raw_high
        - 底分型：k[i].raw_low < k[i-1].raw_low AND k[i].raw_low < k[i+1].raw_low
        
        注意：使用 raw_high/raw_low 确保合并K线时不会丢失极端点
        """
        if len(klines) < 3:
            return []
        
        fx_list: List[SimpleFX] = []
        
        for i in range(1, len(klines) - 1):
            prev = klines[i - 1]
            curr = klines[i]
            next_ = klines[i + 1]
            
            # 使用原始极值进行分型识别
            # 顶分型判断（严格大于）
            if curr.raw_high > prev.raw_high and curr.raw_high > next_.raw_high:
                fx = SimpleFX(
                    fx_type="ding",
                    index=i,
                    kline=curr,
                    price=curr.raw_high,  # 使用原始最高价
                    time=curr.date,
                    raw_index=curr.raw_indices[-1] if curr.raw_indices else i,
                )
                fx_list.append(fx)
            
            # 底分型判断（严格小于）
            elif curr.raw_low < prev.raw_low and curr.raw_low < next_.raw_low:
                fx = SimpleFX(
                    fx_type="di",
                    index=i,
                    kline=curr,
                    price=curr.raw_low,  # 使用原始最低价
                    time=curr.date,
                    raw_index=curr.raw_indices[-1] if curr.raw_indices else i,
                )
                fx_list.append(fx)
        
        return fx_list
    
    # ========================================
    # 3. 笔的生成（参考 chanClass.py 实现）
    # ========================================
    
    def _calculate_bi(
        self,
        fx_list: List[SimpleFX],
        klines: List[MergedKline]
    ) -> List[SimpleBi]:
        """根据分型生成笔（参考 chanClass.py 的实现）
        
        核心逻辑：
        1. 笔延伸：同类型分型，且更极端时延伸（替换）
        2. 新笔生成：类型相反 + K线间隔>=4 + 价格关系满足
        3. 分型修正：检查并修正倒数第二个分型是否是最极端的
        
        价格关系条件：
        - 向下笔（顶→底）：底分型的high < 顶分型的low
        - 向上笔（底→顶）：顶分型的low > 底分型的high
        
        注意：chanClass.py 用 'up' 表示顶分型，'down' 表示底分型
              engine.py 用 'ding' 表示顶分型，'di' 表示底分型
        """
        if len(fx_list) < 2:
            return []
        
        # stroke_list: 用于存储构成笔的分型（参考 chanClass.py）
        # 这里的分型是经过筛选后构成笔端点的分型
        stroke_list: List[SimpleFX] = []
        
        for cur_fx in fx_list:
            if len(stroke_list) < 1:
                # 第一个分型直接加入
                stroke_list.append(cur_fx)
            else:
                last_fx = stroke_list[-1]
                pivot_flag = False
                
                # 1. 笔延伸逻辑：同类型分型
                if last_fx.type == cur_fx.type:
                    # 同类型分型：检查是否更极端
                    if last_fx.type == "di":
                        # 底分型：更低才延伸
                        if cur_fx.val < last_fx.val:
                            stroke_list[-1] = cur_fx
                            pivot_flag = True
                    else:
                        # 顶分型：更高才延伸
                        if cur_fx.val > last_fx.val:
                            stroke_list[-1] = cur_fx
                            pivot_flag = True
                
                # 2. 新笔生成逻辑：类型相反
                else:
                    # 检查K线间隔（chanClass.py 用 >3，即至少4根）
                    kline_gap = cur_fx.index - last_fx.index
                    
                    # 检查价格关系（参考 chanClass.py 的条件）
                    # chanClass.py: (cur_fx[3] == 'down' and cur_fx[1] < last_fx[1] and cur_fx[0] < last_fx[0])
                    # 即：底分型需要 low < 顶分型.low 且 high < 顶分型.high
                    # 顶分型需要 high > 底分型.high 且 low > 底分型.low
                    price_valid = False
                    
                    if cur_fx.type == "di":
                        # 当前是底分型，前一个是顶分型 -> 向下笔
                        # 需要满足：底分型的low < 顶分型的low 且 底分型的high < 顶分型的high
                        cur_low = cur_fx.k.low if cur_fx.k else cur_fx.val
                        cur_high = cur_fx.k.high if cur_fx.k else cur_fx.val
                        last_low = last_fx.k.low if last_fx.k else last_fx.val
                        last_high = last_fx.k.high if last_fx.k else last_fx.val
                        price_valid = cur_low < last_low and cur_high < last_high
                    else:
                        # 当前是顶分型，前一个是底分型 -> 向上笔
                        # 需要满足：顶分型的high > 底分型的high 且 顶分型的low > 底分型的low
                        cur_low = cur_fx.k.low if cur_fx.k else cur_fx.val
                        cur_high = cur_fx.k.high if cur_fx.k else cur_fx.val
                        last_low = last_fx.k.low if last_fx.k else last_fx.val
                        last_high = last_fx.k.high if last_fx.k else last_fx.val
                        price_valid = cur_high > last_high and cur_low > last_low
                    
                    # 满足条件：间隔足够 + 价格关系正确
                    if kline_gap > 3 and price_valid:
                        stroke_list.append(cur_fx)
                        pivot_flag = True
                
                # 3. 分型修正（参考 chanClass.py 的 stroke_change 逻辑）
                # 只在笔延伸或新增时检查倒数第二个分型
                if pivot_flag and len(stroke_list) > 1:
                    self._check_and_fix_second_last_fx(stroke_list, cur_fx, fx_list)
        
        # 4. 从 stroke_list 生成笔对象
        bis: List[SimpleBi] = []
        bi_index = 0
        
        for i in range(len(stroke_list) - 1):
            start_fx = stroke_list[i]
            end_fx = stroke_list[i + 1]
            
            # 确定方向：底分型→顶分型=向上笔，顶分型→底分型=向下笔
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
    
    def _check_and_fix_second_last_fx(
        self,
        stroke_list: List[SimpleFX],
        cur_fx: SimpleFX,
        original_fx_list: List[SimpleFX] = None
    ) -> None:
        """检查并修正倒数第二个分型
        
        参考 chanClass.py 的 stroke_change 逻辑：
        - 当向下笔结束时，检查倒数第二个顶分型是否是最高的
        - 当向上笔结束时，检查倒数第二个底分型是否是最低的
        
        重要：需要从原始分型列表中查找，而不是从 stroke_list 中
        """
        if len(stroke_list) < 3 or not original_fx_list:
            return
        
        # stroke_list[-2] 是倒数第二个分型
        second_last = stroke_list[-2]
        second_last_time = second_last.time
        
        # 在原始分型列表中查找 stroke_list[-2] 之后、stroke_list[-1] 之前的分型
        # 看是否有更极端的
        best_fx = second_last
        
        # 遍历原始分型列表，找到时间在 second_last 和 cur_fx 之间的分型
        for fx in original_fx_list:
            # 跳过时间范围外的分型
            if fx.time <= second_last_time or fx.time >= cur_fx.time:
                continue
            
            # 只检查同类型分型
            if fx.type != second_last.type:
                continue
            
            # 检查是否更极端
            if second_last.type == "ding":
                # 顶分型，找更高的
                if fx.val > best_fx.val:
                    # 检查与当前分型的K线间隔是否足够
                    if cur_fx.index - fx.index > 3:
                        best_fx = fx
            else:
                # 底分型，找更低的
                if fx.val < best_fx.val:
                    if cur_fx.index - fx.index > 3:
                        best_fx = fx
        
        # 如果找到了更极端的分型，替换
        if best_fx != second_last:
            stroke_list[-2] = best_fx
    
    def _filter_fx_alternating(self, fx_list: List[SimpleFX]) -> List[SimpleFX]:
        """过滤分型，确保顶底交替，同类型分型保留最极端的
        
        注意：这个方法现在不再被 _calculate_bi 使用
        保留是为了兼容其他可能的用途
        """
        if not fx_list:
            return []
        
        result: List[SimpleFX] = [fx_list[0]]
        
        for fx in fx_list[1:]:
            last = result[-1]
            
            if fx.type == last.type:
                # 同类型，保留更极端的
                if fx.type == "ding":
                    if fx.val > last.val:
                        result[-1] = fx
                else:
                    if fx.val < last.val:
                        result[-1] = fx
            else:
                result.append(fx)
        
        return result
    
    # ========================================
    # 4. 笔的力度计算
    # ========================================
    
    def _calculate_bi_strength(self, df: pd.DataFrame) -> None:
        """计算笔的力度（多维度）
        
        力度计算包括：
        1. MACD 力度：MACD 柱子面积
        2. 价格力度：价格变化幅度
        3. 斜率力度：单位时间价格变化
        """
        if not self._bis or df is None or len(df) == 0:
            return
        
        # 计算 MACD
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
            
            # 1. MACD 力度
            if bi.type == "up":
                bi.macd_strength = float(sum(abs(v) for v in segment if v > 0))
            else:
                bi.macd_strength = float(sum(abs(v) for v in segment if v < 0))
            
            # 2. 价格力度
            bi.price_strength = abs(bi.end_price - bi.start_price)
            
            # 3. 斜率力度
            kline_count = abs(e - s) + 1
            bi.slope_strength = bi.price_strength / max(kline_count, 1)
            
            # 综合力度（加权平均）
            bi.strength = (
                0.5 * bi.macd_strength +
                0.3 * bi.price_strength +
                0.2 * bi.slope_strength * 100  # 斜率需要放大
            )
    
    # ========================================
    # 5. 线段的生成（基于笔的分型列表）
    # ========================================
    
    def _calculate_xd(self, bis: List[SimpleBi]) -> List[SimpleXD]:
        """根据笔生成线段（完全重写，确保连续性）
        
        线段定义：
        1. 线段由笔构成，端点是分型
        2. 相邻线段共享端点（前一线段终点 = 后一线段起点）
        3. 特征序列分型识别线段端点
        
        算法：
        1. 从笔中提取分型列表（笔端点的分型）
        2. 在分型列表上识别顶底分型，确定线段端点
        3. 确保线段连续：前一个端点 = 下一个线段的起点
        """
        if len(bis) < 3:
            return []
        
        # 从笔中提取分型列表：笔端点的分型
        # fx_from_bi[0] = 第一笔的起点分型
        # fx_from_bi[i] = 笔(i-1)的终点分型
        fx_from_bi: List[SimpleFX] = [bis[0].start_fx]
        for bi in bis:
            fx_from_bi.append(bi.end_fx)
        
        if len(fx_from_bi) < 5:
            return []
        
        # 线段端点列表：存储线段端点的分型
        # 确保相邻端点共享同一个分型对象，保证连续性
        line_endpoints: List[SimpleFX] = []
        
        # 第一个端点：第一个分型
        line_endpoints.append(fx_from_bi[0])
        
        for i in range(4, len(fx_from_bi)):
            # 检查顶分型（结束向上线段）
            # 条件：data[-1]是顶分型，data[-3]高于data[-1]和data[-5]
            if (fx_from_bi[i].type == 'ding' and 
                fx_from_bi[i-2].val >= fx_from_bi[i].val and 
                fx_from_bi[i-2].val >= fx_from_bi[i-4].val):
                
                # 找到顶分型端点：fx_from_bi[i-2]
                candidate = fx_from_bi[i-2]
                
                # 最后一个端点是底分型才能添加顶分型
                if line_endpoints[-1].type == 'di':
                    # 检查间隔
                    last_idx = fx_from_bi.index(line_endpoints[-1])
                    if (i - 2 - last_idx) > 2:
                        line_endpoints.append(candidate)
                elif line_endpoints[-1].type == 'ding':
                    # 同类型，延伸（取更高的）
                    if candidate.val > line_endpoints[-1].val:
                        line_endpoints[-1] = candidate
            
            # 检查底分型（结束向下线段）
            # 条件：data[-1]是底分型，data[-3]低于data[-1]和data[-5]
            if (fx_from_bi[i].type == 'di' and 
                fx_from_bi[i-2].val <= fx_from_bi[i].val and 
                fx_from_bi[i-2].val <= fx_from_bi[i-4].val):
                
                # 找到底分型端点：fx_from_bi[i-2]
                candidate = fx_from_bi[i-2]
                
                # 最后一个端点是顶分型才能添加底分型
                if line_endpoints[-1].type == 'ding':
                    last_idx = fx_from_bi.index(line_endpoints[-1])
                    if (i - 2 - last_idx) > 2:
                        line_endpoints.append(candidate)
                elif line_endpoints[-1].type == 'di':
                    # 同类型，延伸（取更低的）
                    if candidate.val < line_endpoints[-1].val:
                        line_endpoints[-1] = candidate
        
        # 如果端点太少，无法形成线段
        if len(line_endpoints) < 2:
            return []
        
        # 从端点生成线段对象
        xds: List[SimpleXD] = []
        
        for i in range(len(line_endpoints) - 1):
            start_fx = line_endpoints[i]
            end_fx = line_endpoints[i + 1]
            
            # 确定方向
            if start_fx.type == 'di' and end_fx.type == 'ding':
                direction = 'up'
            elif start_fx.type == 'ding' and end_fx.type == 'di':
                direction = 'down'
            else:
                # 类型相同，跳过
                continue
            
            # 找到对应的笔范围
            start_bi_idx = None
            end_bi_idx = None
            
            for j, bi in enumerate(bis):
                # 找包含起点分型的笔
                if start_bi_idx is None:
                    if bi.start_fx == start_fx or bi.end_fx == start_fx:
                        start_bi_idx = j
                # 找包含终点分型的笔
                if bi.end_fx == end_fx:
                    end_bi_idx = j
            
            if start_bi_idx is None or end_bi_idx is None:
                continue
            
            # 关键修复：如果起点分型在笔的终点，线段应从下一笔开始
            # 因为：
            # - 向下线段从顶分型开始，第一笔应该是向下笔
            # - 向上线段从底分型开始，第一笔应该是向上笔
            # - 如果分型在笔的终点，那笔是相反方向的，下一笔才是正确方向
            if bis[start_bi_idx].end_fx == start_fx:
                start_bi_idx += 1
            
            if start_bi_idx >= end_bi_idx:
                continue
            
            bi_list = bis[start_bi_idx:end_bi_idx + 1]
            start_bi = bis[start_bi_idx]
            end_bi = bis[end_bi_idx]
            
            # 线段价格和时间直接使用端点分型的值（确保连续性）
            xd = SimpleXD(
                index=len(xds),
                direction=direction,
                start_bi=start_bi,
                end_bi=end_bi,
                bi_list=bi_list,
                is_done=True,
            )
            # 覆盖起止价格和时间，使用分型值确保连续
            xd.start_price = start_fx.val
            xd.end_price = end_fx.val
            xd.start_time = start_fx.time
            xd.end_time = end_fx.time
            
            xds.append(xd)
        
        return xds
    
    # ========================================
    # 6. 线段力度计算
    # ========================================
    
    def _calculate_xd_strength(self) -> None:
        """计算线段的力度"""
        for xd in self._xds:
            # 线段力度 = 包含的笔的力度之和
            xd.strength = sum(bi.strength for bi in xd.bi_list)
    
    # ========================================
    # 7. 中枢计算
    # ========================================
    
    def _calculate_zs(self, items: List[SimpleBi], level: str) -> List[SimpleZS]:
        """计算笔中枢
        
        中枢定义：
        - 至少3笔有重叠区间
        - ZG = min(所有笔的高点)
        - ZD = max(所有笔的低点)
        - 必须 ZD < ZG 才形成中枢
        """
        if len(items) < self.zs_min_bi:
            return []
        
        zss: List[SimpleZS] = []
        zs_index = 0
        i = 0
        
        def get_bi_range(bi: SimpleBi) -> Tuple[float, float]:
            """获取笔的价格区间 (low, high)"""
            return (bi.low, bi.high)
        
        while i <= len(items) - self.zs_min_bi:
            # 取连续的笔尝试形成中枢
            first_bis = items[i:i + self.zs_min_bi]
            ranges = [get_bi_range(bi) for bi in first_bis]
            
            # 计算重叠区间
            zd = max(r[0] for r in ranges)  # 所有低点的最大值
            zg = min(r[1] for r in ranges)  # 所有高点的最小值
            
            if zd < zg:
                # 形成中枢，尝试扩展
                zs_bis = list(first_bis)
                j = i + self.zs_min_bi
                
                while j < len(items):
                    next_bi = items[j]
                    next_low, next_high = get_bi_range(next_bi)
                    
                    # 检查是否与中枢有重叠
                    if next_low < zg and next_high > zd:
                        zs_bis.append(next_bi)
                        j += 1
                    else:
                        break
                
                # 计算最终的中枢参数
                all_ranges = [get_bi_range(bi) for bi in zs_bis]
                
                # ZG, ZD 使用前3笔确定
                first_three = all_ranges[:3]
                zd = max(r[0] for r in first_three)
                zg = min(r[1] for r in first_three)
                
                # GG, DD 使用所有笔
                gg = max(r[1] for r in all_ranges)
                dd = min(r[0] for r in all_ranges)
                
                # 判断中枢方向
                if gg > zg and dd < zd:
                    direction = "zd"  # 震荡
                elif gg > zg:
                    direction = "up"
                elif dd < zd:
                    direction = "down"
                else:
                    direction = "zd"
                
                # 计算与前一个中枢的关系
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
                
                # 跳过已处理的笔
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
        # 1. 计算笔的背驰和一类买卖点
        self._calculate_bi_bcs_and_mmds()
        
        # 2. 计算线段的背驰和二类买卖点
        self._calculate_xd_bcs_and_mmds()
        
        # 3. 计算三类买卖点
        self._calculate_class3_mmds()
    
    def _calculate_bi_bcs_and_mmds(self) -> None:
        """计算笔的背驰和一类买卖点"""
        if len(self._bis) < 5:
            return
        
        for i in range(4, len(self._bis)):
            current_bi = self._bis[i]
            
            # 查找同向前笔（跳2笔）
            for j in range(i - 2, -1, -2):
                prev_bi = self._bis[j]
                
                if current_bi.type != prev_bi.type:
                    continue
                
                # 检测背驰
                is_bc = self._check_divergence(prev_bi, current_bi)
                
                if is_bc:
                    # 查找相关中枢
                    related_zs = self._find_related_zs(current_bi, self._bi_zss)
                    
                    # 添加背驰标记
                    current_bi.bcs.append(SimpleBC(
                        bc_type="bi",
                        is_bc=True,
                        zs=related_zs,
                        compare_item=prev_bi,
                    ))
                    
                    # 判断一类买卖点
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
            # 找中枢后的笔
            for bi in self._bis:
                if bi.start_time <= zs.end_time:
                    continue
                
                # 三买：向上笔回落不进中枢
                if bi.type == "down" and bi.low > zs.zd:
                    # 检查前一笔是否突破中枢上沿
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
                
                # 三卖：向下笔反弹不进中枢
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
        """检测笔背驰（多维度）"""
        if prev.type != curr.type:
            return False
        
        # 力度比较
        prev_strength = prev.strength
        curr_strength = curr.strength
        
        if prev_strength <= 0 or curr_strength <= 0:
            # 力度无效，使用价格幅度
            prev_strength = prev.price_strength
            curr_strength = curr.price_strength
        
        if prev_strength <= 0:
            return False
        
        # 背驰条件：新高/新低 + 力度减弱
        strength_ratio = curr_strength / prev_strength
        
        if prev.type == "up":
            # 上笔：创新高但力度减弱
            return curr.end_price > prev.end_price and strength_ratio < 0.8
        else:
            # 下笔：创新低但力度减弱
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
        """获取合并后的K线（调试用）"""
        return self._merged_klines
    
    def get_fx_list(self) -> List[SimpleFX]:
        """获取分型列表（调试用）"""
        return self._fx_list
    
    def get_macd_data(self) -> Dict[str, Any]:
        """获取 MACD 指标数据（用于可视化）
        
        返回：
        - dates: 日期列表
        - dif: DIF 线
        - dea: DEA 线 (信号线)
        - hist: MACD 柱状图 (DIF - DEA) * 2
        """
        if self._raw_df is None or len(self._raw_df) == 0:
            return {"dates": [], "dif": [], "dea": [], "hist": []}
        
        df = self._raw_df
        close = df["close"].astype(float)
        
        # 计算 MACD
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


# 将 SimpleICL 作为 ICL 的别名，保持接口一致
ICL = SimpleICL


# ============================================================
# 引擎配置和封装类
# ============================================================

@dataclass
class EngineConfig:
    """缠论引擎配置"""
    
    options: Dict[str, Any] = None
    bi_min_kline: int = 4  # 笔的最小 K 线数量（合并后）
    xd_min_bi: int = 3     # 线段的最小笔数量
    zs_min_bi: int = 3     # 中枢的最小笔数量
    
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
        
        # 合并配置
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
