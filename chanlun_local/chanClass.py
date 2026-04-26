# 导入函数库
import math
from copy import copy
import pandas as pd
import numpy as np
import talib as tl
from enum import Enum
from datetime import datetime, timedelta
from typing import Callable, Optional
from typing import Optional, List, Dict, Any



class Interval(Enum):
    MINUTE = "1m"
    MINUTE5 = "5m"
    MINUTE30 = "30m"
    HOUR = "1h"
    DAILY = "1d"
    WEEKLY = "1w"

FREQS = ['日线', '30分钟', '5分钟', '1分钟']

FREQS_WINDOW = {
    '日线': [240, Interval.MINUTE, Interval.DAILY],
    '30分钟': [30, Interval.MINUTE, Interval.MINUTE30],
    '5分钟': [5, Interval.MINUTE, Interval.MINUTE5],
    '1分钟': [1, Interval.MINUTE, Interval.MINUTE],
}

INTERVAL_FREQ = {
    '1d': '日线',
    '30m': '30分钟',
    '5m': '5分钟',
    '1m': '1分钟'
}



class Exchange(Enum):
    XSHE = "XSHE"
    XSHG = "XSHG"


# 日志类（模拟原项目中的 ChanLog，需根据实际需求调整）
import logging
chan_logger = logging.getLogger(__name__)

class ChanLog:
    @staticmethod
    def log(freq, symbol, message):
        # 关闭日志输出（调试完成后）
        # print(f"[{freq}][{symbol}] {message}")
        return None

        
class TickData:
    symbol: str
    exchange: Exchange
    datetime: datetime

    name: str = ""
    volume: float = 0
    open_interest: float = 0
    last_price: float = 0
    last_volume: float = 0
    limit_up: float = 0
    limit_down: float = 0

    open_price: float = 0
    high_price: float = 0
    low_price: float = 0
    pre_close: float = 0

    bid_price_1: float = 0
    bid_price_2: float = 0
    bid_price_3: float = 0
    bid_price_4: float = 0
    bid_price_5: float = 0

    ask_price_1: float = 0
    ask_price_2: float = 0
    ask_price_3: float = 0
    ask_price_4: float = 0
    ask_price_5: float = 0

    bid_volume_1: float = 0
    bid_volume_2: float = 0
    bid_volume_3: float = 0
    bid_volume_4: float = 0
    bid_volume_5: float = 0

    ask_volume_1: float = 0
    ask_volume_2: float = 0
    ask_volume_3: float = 0
    ask_volume_4: float = 0
    ask_volume_5: float = 0

    def __post_init__(self):
        self.vt_symbol = f"{self.symbol}.{self.exchange.value}"

class BarData:
    datetime: datetime
    symbol: str
    exchange: Exchange = None
    interval: Interval = None
    volume: float = 0
    open_interest: float = 0
    open_price: float = 0
    high_price: float = 0
    low_price: float = 0
    close_price: float = 0

    def __init__(self, datetime, symbol, exchange, freq, open_price, high_price, low_price, close_price, volume):
        self.datetime = datetime
        self.symbol = symbol
        self.exchange =  exchange
        self.interval = Interval(freq)
        self.open_interest = 0
        self.open_price = open_price
        self.high_price = high_price
        self.low_price = low_price
        self.close_price = close_price
        self.volume = volume
        self.vt_symbol = symbol
        # self.vt_symbol = f"{self.symbol}.{self.exchange.value}"    

class BarGenerator:
    """
    Target:
    1. generating 1 minute bar data from tick data
    2. generateing x minute bar/x hour bar data from 1 minute data

    Notice:
    1. for x minute bar, x must be able to divide 60: 2, 3, 5, 6, 10, 15, 20, 30
    2. for x hour bar, x can be any number
    """

    def __init__(
            self,
            on_bar: Callable,
            window: int = 0,
            on_window_bar: Callable = None,
            interval: Interval = Interval.MINUTE,
            target: Interval = Interval.MINUTE
    ):
        self.bar: BarData = None
        self.on_bar: Callable = on_bar

        self.interval: Interval = interval
        self.interval_count: int = 0

        self.window: int = window
        self.window_bar: BarData = None
        self.on_window_bar: Callable = on_window_bar

        self.last_tick: TickData = None
        self.last_bar: BarData = None

        self.target = target

    def update_tick(self, tick: TickData) -> None:
        """
        Update new tick data into generator.
        """
        new_minute = False

        # Filter tick data with 0 last price
        if not tick.last_price:
            return

        # Filter tick data with less intraday trading volume (i.e. older timestamp)
        # if self.last_tick and tick.volume and tick.volume < self.last_tick.volume:
        #     return
        # 过滤掉收到的过去的tick
        if self.last_tick and tick.datetime < self.last_tick.datetime:
            return

        if not self.bar:
            new_minute = True
        elif self.bar.datetime.minute != tick.datetime.minute:
            self.bar.datetime = self.bar.datetime.replace(
                second=0, microsecond=0
            )
            self.on_bar(self.bar)

            new_minute = True

        if new_minute:
            self.bar = BarData(symbol=tick.symbol,
                exchange=tick.exchange,
                interval=Interval.MINUTE,
                datetime=tick.datetime,
                open_price=tick.last_price,
                high_price=tick.last_price,
                low_price=tick.last_price,
                close_price=tick.last_price,
                open_interest=tick.open_interest
            )
        else:
            self.bar.high_price = max(self.bar.high_price, tick.last_price)
            self.bar.low_price = min(self.bar.low_price, tick.last_price)
            self.bar.close_price = tick.last_price
            self.bar.open_interest = tick.open_interest
            self.bar.datetime = tick.datetime

        if self.last_tick:
            volume_change = tick.volume - self.last_tick.volume
            self.bar.volume += max(volume_change, 0)

        self.last_tick = tick

    def update_bar(self, bar: BarData) -> None:
        """
        Update 1 minute bar into generator
        """
        # If not inited, creaate window bar object
        if not self.window_bar:
            # Generate timestamp for bar data
            if self.interval == Interval.MINUTE:
                dt = bar.datetime.replace(second=0, microsecond=0)
            else:
                dt = bar.datetime.replace(minute=0, second=0, microsecond=0)

            self.window_bar = BarData(
                datetime=dt,
                symbol=bar.symbol,
                freq=bar.interval,
                exchange=bar.exchange,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
            )

        # Otherwise, update high/low price into window bar
        else:
            dt = bar.datetime.replace(second=0, microsecond=0)
            if not self.interval == Interval.MINUTE:
                dt = bar.datetime.replace(minute=0, second=0, microsecond=0)
            self.window_bar.datetime = dt
            self.window_bar.high_price = max(
                self.window_bar.high_price, bar.high_price)
            self.window_bar.low_price = min(
                self.window_bar.low_price, bar.low_price)

        # Update close price/volume into window bar
        self.window_bar.close_price = bar.close_price
        self.window_bar.volume += int(bar.volume)
        self.window_bar.open_interest = bar.open_interest
        self.window_bar.interval = self.target
        # Check if window bar completed
        finished = False

        if self.interval == Interval.MINUTE:
            # x-minute bar
            self.interval_count += 1

            if not self.interval_count % self.window:
                finished = True
                self.interval_count = 0
        elif self.interval == Interval.HOUR:
            if self.last_bar and bar.datetime.hour != self.last_bar.datetime.hour:
                # 1-hour bar
                if self.window == 1:
                    finished = True
                # x-hour bar
                else:
                    self.interval_count += 1

                    if not self.interval_count % self.window:
                        finished = True
                        self.interval_count = 0

        if finished:
            #print(self.window_bar)
            self.on_window_bar(self.window_bar)
            self.window_bar = None

        # Cache last bar object
        self.last_bar = bar

    def generate(self) -> Optional[BarData]:
        """
        Generate the bar data and call callback immediately.
        """
        bar = self.bar

        if self.bar:
            bar.datetime = bar.datetime.replace(second=0, microsecond=0)
            self.on_bar(bar)

        self.bar = None
        return bar

class Chan_Class:

    def __init__(self, freq, symbol, sell, buy, include=True, include_feature=False, build_line_pivot=False, qjt=True,
                 gz=False, buy1=100, buy2=200, buy3=200, sell1=100, sell2=200, sell3=200):

        self.freq = freq
        self.symbol = symbol
        self.prev = None
        self.next = None
        self.k_list = []
        self.chan_k_list = []
        self.fx_list = []
        self.stroke_list = []
        self.stroke_index_in_k = {}
        # P0: 笔级别数据存储 - 增强版笔数据结构
        self.pens = []  # 完整笔数据: [{'index': int, 'start_fx': fx, 'end_fx': fx, 'direction': str,
                   #                    'open_price': float, 'high_price': float, 'low_price': float,
                   #                    'close_price': float, 'volume': float, 'start_k_index': int, 'end_k_index': int}]
        self.pen_macd = {}  # 笔级别MACD: {pen_index: {'dif': float, 'dea': float, 'macd': float, 'area': float}}
        self.line_list = []
        self.line_index = {}
        self.line_index_in_k = {}
        self.line_feature = []
        self.s_feature = []
        self.x_feature = []

        self.pivot_list = []
        self.trend_list = []
        self.buy_list = []
        self.sell_list = []
        self.macd = {}
        self.buy = buy
        self.sell = sell
        self.buy1 = buy1
        self.buy2 = buy2
        self.buy3 = buy3
        self.sell1 = sell1
        self.sell2 = sell2
        self.sell3 = sell3
        # 动力减弱最小指标
        self.dynamic_reduce = 0
        # 笔生成方法，new, old
        # 是否进行K线包含处理
        self.include = include
        # 中枢生成方法，stroke, line
        # 使用笔还是线段作为中枢的构成, true使用线段
        self.build_line_pivot = build_line_pivot
        # 线段生成方法
        # 是否进行K线包含处理
        self.include_feature = include_feature
        # 是否使用区间套
        self.qjt = qjt
        # 是否使用共振
        # 采用买卖点共振组合方法，1分钟一类买卖点+5分钟二类买卖点或三类买卖点，都属于共振
        self.gz = gz
        # 计数
        self.gz_delay_k_num = 0
        # 最大
        self.gz_delay_k_max = 12
        # 潜在bs
        self.gz_tmp_bs = None
        # 高级别bs
        self.gz_prev_last_bs = None
        # 已执行的信号
        self.executed_signals = set()
        
        # 背驰判断参数
        self.divergence_ratio_threshold = 0.4  # MACD面积比例阈值（离开段/进入段 < 0.4 算背驰，即缩小60%）

    def set_prev(self, chan):
        self.prev = chan

    def set_next(self, chan):
        self.next = chan

    def on_bar(self, bar: BarData):
        self.k_list.append(bar)
        if self.gz and self.gz_tmp_bs:
            self.gz_delay_k_num += 1
            self.on_gz()
        if self.include:
            self.on_process_k_include(bar)
        else:
            self.on_process_k_no_include(bar)

    def on_process_k_include(self, bar: BarData):
        """合并k线"""
        if len(self.chan_k_list) < 2:
            self.chan_k_list.append(bar)
        else:
            pre_bar = self.chan_k_list[-2]
            last_bar = self.chan_k_list[-1]
            if (last_bar.high_price >= bar.high_price and last_bar.low_price <= bar.low_price) or (
                    last_bar.high_price <= bar.high_price and last_bar.low_price >= bar.low_price):
                if last_bar.high_price > pre_bar.high_price:
                    new_bar = copy(bar)
                    new_bar.high_price = max(last_bar.high_price, new_bar.high_price)
                    new_bar.low_price = max(last_bar.low_price, new_bar.low_price)
                    new_bar.open_price = max(last_bar.open_price, new_bar.open_price)
                    new_bar.close_price = max(last_bar.close_price, new_bar.close_price)
                else:
                    new_bar = copy(bar)
                    new_bar.high_price = min(last_bar.high_price, new_bar.high_price)
                    new_bar.low_price = min(last_bar.low_price, new_bar.low_price)
                    new_bar.open_price = min(last_bar.open_price, new_bar.open_price)
                    new_bar.close_price = min(last_bar.close_price, new_bar.close_price)

                self.chan_k_list[-1] = new_bar
                ChanLog.log(self.freq, self.symbol, "combine k line: " + str(new_bar.datetime))
            else:
                self.chan_k_list.append(bar)
            # 包含和非包含处理的k线都需要判断是否分型了
            self.on_process_fx(self.chan_k_list)

    def on_process_k_no_include(self, bar: BarData):
        """不用合并k线"""
        self.chan_k_list.append(bar)
        self.on_process_fx(self.chan_k_list)

    def on_process_fx(self, data):
        """分型判断（缠论第62课 + 实盘注释"等于也算"）

        缠论原文定义：
        - 顶分型：中间K线高点最高（等于也算）
        - 底分型：中间K线低点最低（等于也算）

        注：缠师在实盘注释中明确说"等于也算"，因此移除额外辅助条件
        """
        if len(data) > 2:
            flag = False
            # 顶分型：中间K线高点最高（等于也算）
            if (data[-2].high_price >= data[-1].high_price and
                data[-2].high_price >= data[-3].high_price):
                self.fx_list.append([data[-2].high_price, data[-2].low_price, data[-2].datetime, 'up', len(data) - 2])
                flag = True

            # 底分型：中间K线低点最低（等于也算）
            if (data[-2].low_price <= data[-1].low_price and
                data[-2].low_price <= data[-3].low_price):
                self.fx_list.append([data[-2].high_price, data[-2].low_price, data[-2].datetime, 'down', len(data) - 2])
                flag = True

            if flag:
                self.on_stroke(self.fx_list[-1])
                ChanLog.log(self.freq, self.symbol, "fx_list: ")
                ChanLog.log(self.freq, self.symbol, self.fx_list[-1])

    def build_pen_data(self, start_fx, end_fx, start_index, end_index):
        """
        P0: 构建完整的笔数据
        Args:
            start_fx: 起始分型 [high, low, datetime, direction, k_index]
            end_fx: 结束分型 [high, low, datetime, direction, k_index]
            start_index: 笔在stroke_list中的索引
            end_index: 笔在stroke_list中的索引（用于笔延伸时更新）
        Returns:
            笔数据字典
        """
        # 确定起止K线索引
        k_start = min(start_fx[4], end_fx[4])
        k_end = max(start_fx[4], end_fx[4])

        # 提取笔涵盖的K线数据
        k_data = self.k_list[k_start:k_end+1]

        if not k_data:
            return None

        # 计算笔的OHLCV
        open_price = start_fx[1] if start_fx[3] == 'down' else start_fx[0]  # 底分型low或顶分型high
        close_price = end_fx[1] if end_fx[3] == 'down' else end_fx[0]
        high_price = max(bar.high_price for bar in k_data)
        low_price = min(bar.low_price for bar in k_data)
        volume = sum(bar.volume for bar in k_data)

        # 确定笔的方向
        # 从底分型到顶分型 = 向上笔
        # 从顶分型到底分型 = 向下笔
        if start_fx[3] == 'down' and end_fx[3] == 'up':
            direction = 'up'
        elif start_fx[3] == 'up' and end_fx[3] == 'down':
            direction = 'down'
        else:
            # 异常情况，根据价格变化判断
            if end_fx[1] > start_fx[1]:  # 更高
                direction = 'up'
            else:
                direction = 'down'

        return {
            'index': end_index,
            'start_fx': start_fx,
            'end_fx': end_fx,
            'direction': direction,
            'open_price': open_price,
            'high_price': high_price,
            'low_price': low_price,
            'close_price': close_price,
            'volume': volume,
            'start_k_index': k_start,
            'end_k_index': k_end
        }

    def on_stroke(self, data):
        """生成笔"""
        if len(self.stroke_list) < 1:
            self.stroke_list.append(data)
            # P0: 构建第一笔数据
            pen_data = self.build_pen_data(data, data, 0, 0)
            if pen_data:
                self.pens.append(pen_data)
            ChanLog.log(self.freq, self.symbol, self.stroke_list)
        else:
            last_fx = self.stroke_list[-1]
            cur_fx = data
            pivot_flag = False
            # 分型之间需要超过三根chank线
            # 延申也是需要条件的
            if last_fx[3] == cur_fx[3]:
                if (last_fx[3] == 'down' and cur_fx[1] < last_fx[1]) or (
                        last_fx[3] == 'up' and cur_fx[0] > last_fx[0]):
                    # 笔延申
                    self.stroke_list[-1] = cur_fx
                    # P0: 更新笔数据
                    if len(self.pens) > 0:
                        pen_index = len(self.stroke_list) - 1
                        # 重新构建最后一笔数据
                        if len(self.stroke_list) >= 2:
                            pen_data = self.build_pen_data(self.stroke_list[-2], cur_fx, pen_index, pen_index)
                            if pen_data:
                                self.pens[-1] = pen_data
                    pivot_flag = True

            else:
                # if (cur_fx[4] - last_fx[4] > 3) and (
                #         (cur_fx[3] == 'down' and cur_fx[1] < last_fx[1] and cur_fx[0] < last_fx[0]) or (
                #         cur_fx[3] == 'up' and cur_fx[0] > last_fx[0] and cur_fx[1] > last_fx[1])):
                if (cur_fx[4] - last_fx[4] > 3) and (
                        (cur_fx[3] == 'down' and cur_fx[0] < last_fx[1]) or (
                        cur_fx[3] == 'up' and cur_fx[1] > last_fx[0])):
                    # 笔新增
                    self.stroke_list.append(cur_fx)
                    # P0: 构建笔数据
                    pen_data = self.build_pen_data(self.stroke_list[-2], cur_fx, len(self.stroke_list)-1, len(self.stroke_list)-1)
                    if pen_data:
                        self.pens.append(pen_data)
                    ChanLog.log(self.freq, self.symbol, "stroke_list: ")
                    ChanLog.log(self.freq, self.symbol, self.stroke_list[-1])
                    # ChanLog.log(self.freq, self.symbol, self.stroke_list)
                    pivot_flag = True

            # 修正倒数第二个分型是否是最高的顶分型或者是否是最低的底分型
            # 只修一笔，不修多笔
            start = -2
            stroke_change = None
            if pivot_flag and len(self.stroke_list) > 1:
                stroke_change = self.stroke_list[-2]
                if cur_fx[3] == 'down':
                    while len(self.fx_list) > abs(start) and self.fx_list[start][2] > self.stroke_list[-2][2]:
                        if self.fx_list[start][3] == 'up' and self.fx_list[start][0] > stroke_change[0]:
                            if len(self.stroke_list) < 3 or (cur_fx[4] - self.fx_list[start][4] > 3):
                                stroke_change = self.fx_list[start]
                        start -= 1
                else:
                    while len(self.fx_list) > abs(start) and self.fx_list[start][2] > self.stroke_list[-2][2]:
                        if self.fx_list[start][3] == 'down' and self.fx_list[start][1] < stroke_change[1]:
                            if len(self.stroke_list) < 3 or (cur_fx[4] - self.fx_list[start][4] > 3):
                                stroke_change = self.fx_list[start]
                        start -= 1
            if stroke_change and not stroke_change == self.stroke_list[-2]:
                ChanLog.log(self.freq, self.symbol, 'stroke_change')
                ChanLog.log(self.freq, self.symbol, stroke_change)
                self.stroke_list[-2] = stroke_change
                if len(self.stroke_list) > 2:
                    cur_fx = self.stroke_list[-2]
                    last_fx = self.stroke_list[-3]
                    self.macd[cur_fx[2]] = self.cal_macd(last_fx[4], cur_fx[4])
                # if cur_fx[4] - self.stroke_list[-2][4] < 4:
                #     self.stroke_list.pop()

            if self.build_line_pivot:
                self.on_line(self.stroke_list)
            else:
                if len(self.stroke_list) > 1:
                    cur_fx = self.stroke_list[-1]
                    last_fx = self.stroke_list[-2]
                    self.macd[cur_fx[2]] = self.cal_macd(last_fx[4], cur_fx[4])
                self.on_line(self.stroke_list)
                if pivot_flag:
                    self.on_pivot(self.stroke_list, None)

    def on_line(self, data):
        # line_list保持和stroke_list结构相同，都是由分型构成的
        # 特征序列则不同，
        if len(data) > 4:
            # ChanLog.log(self.freq, self.symbol, 'line_index:')
            # ChanLog.log(self.freq, self.symbol, self.line_index)
            pivot_flag = False
            if data[-1][3] == 'up' and data[-3][0] >= data[-1][0] and data[-3][0] >= data[-5][0]:
                if not self.line_list or self.line_list[-1][3] == 'down':
                    if not self.line_list or ((len(self.stroke_list) - 3) - self.line_index[
                        str(self.line_list[-1][2])] > 2 and self.line_list[-1][1] < data[-3][0]):
                        # 出现顶
                        self.line_list.append(data[-3])
                        self.line_index[str(self.line_list[-1][2])] = len(self.stroke_list) - 3
                        pivot_flag = True
                else:
                    # 延申顶
                    if self.line_list[-1][0] < data[-3][0]:
                        self.line_list[-1] = data[-3]
                        self.line_index[str(self.line_list[-1][2])] = len(self.stroke_list) - 3
                        pivot_flag = True
            if data[-1][3] == 'down' and data[-3][1] <= data[-1][1] and data[-3][1] <= data[-5][1]:
                if not self.line_list or self.line_list[-1][3] == 'up':
                    if not self.line_list or ((len(self.stroke_list) - 3) - self.line_index[
                        str(self.line_list[-1][2])] > 2 and self.line_list[-1][0] > data[-3][1]):
                        # 出现底
                        self.line_list.append(data[-3])
                        self.line_index[str(self.line_list[-1][2])] = len(self.stroke_list) - 3
                        pivot_flag = True
                else:
                    # 延申底
                    if self.line_list[-1][1] > data[-3][1]:
                        self.line_list[-1] = data[-3]
                        self.line_index[str(self.line_list[-1][2])] = len(self.stroke_list) - 3
                        pivot_flag = True

            line_change = None
            if pivot_flag and len(self.line_list) > 1:
                last_fx = self.line_list[-2]
                line_change = last_fx
                cur_fx = self.line_list[-1]
                cur_index = self.line_index[str(cur_fx[2])]
                start = -6
                last_index = self.line_index[str(last_fx[2])]
                if cur_index - last_index > 3:
                    while len(self.stroke_list) >= abs(start - 2) and self.stroke_list[start][2] > last_fx[2]:
                        if cur_fx[3] == 'down' and self.stroke_list[start][0] > self.stroke_list[start + 2][0] and \
                                self.stroke_list[start][0] > self.stroke_list[start - 2][0] and self.stroke_list[start][
                            0] > line_change[0]:
                            line_change = self.stroke_list[start]
                        if cur_fx[3] == 'up' and self.stroke_list[start][1] < self.stroke_list[start + 2][1] and \
                                self.stroke_list[start][1] < self.stroke_list[start - 2][1] and self.stroke_list[start][
                            1] < line_change[1]:
                            line_change = self.stroke_list[start]
                        start -= 2

            if line_change and not line_change == self.line_list[-2]:
                ChanLog.log(self.freq, self.symbol, 'line_change')
                ChanLog.log(self.freq, self.symbol, line_change)
                ChanLog.log(self.freq, self.symbol, self.line_list)
                self.line_index[str(line_change[2])] = self.line_index[str(self.line_list[-2][2])]
                self.line_list[-2] = line_change
                if len(self.line_list) > 2:
                    cur_fx = self.line_list[-2]
                    last_fx = self.line_list[-3]
                    self.macd[cur_fx[2]] = self.cal_macd(last_fx[4], cur_fx[4])

            if self.line_list and self.build_line_pivot:
                if len(self.line_list) > 1:
                    cur_fx = self.line_list[-1]
                    last_fx = self.line_list[-2]
                    self.macd[cur_fx[2]] = self.cal_macd(last_fx[4], cur_fx[4])
                ChanLog.log(self.freq, self.symbol, 'line_list:')
                ChanLog.log(self.freq, self.symbol, self.line_list[-1])
                self.on_pivot(self.line_list, None)

    def on_pivot(self, data, type):
        # 中枢列表[[日期1，日期2，中枢低点，中枢高点, 中枢类型，中枢进入段，中枢离开段, 形成时间, GG, DD,BS,BS,TS]]]
        # 日期1：中枢开始的时间
        # 日期2：中枢结束的时间，可能延申
        # 中枢类型： ‘up', 'down'
        # BS: 买点
        # BS: 卖点
        # TS: 背驰段
        if len(data) > 5:
            # 构成笔或者是线段的分型
            cur_fx = data[-1]
            last_fx = data[-2]
            new_pivot = None
            flag = False
            # 构成新的中枢
            # 判断形成新的中枢的可能性
            if not self.pivot_list or (len(self.pivot_list) > 0 and len(data) - self.pivot_list[-1][6] > 4):
                cur_pivot = [data[-5][2], last_fx[2]]
                if cur_fx[3] == 'down' and data[-2][0] > data[-5][1]:
                    # 缠论第17课：中枢区间由前三笔的重叠区间确定
                    # 每一笔由相邻两个分型构成，前三笔需要前4个分型
                    # 笔1: data[-5]→data[-4], 笔2: data[-4]→data[-3], 笔3: data[-3]→data[-2]
                    stroke1_high = max(data[-5][0], data[-4][0])
                    stroke1_low = min(data[-5][1], data[-4][1])
                    stroke2_high = max(data[-4][0], data[-3][0])
                    stroke2_low = min(data[-4][1], data[-3][1])
                    stroke3_high = max(data[-3][0], data[-2][0])
                    stroke3_low = min(data[-3][1], data[-2][1])
                    ZD = max(stroke1_low, stroke2_low, stroke3_low)  # 前三笔低点的最大值
                    ZG = min(stroke1_high, stroke2_high, stroke3_high)  # 前三笔高点的最小值
                    # GG/DD 用所有分型的极值（分型列表而非笔列表）
                    all_highs = [s[0] for s in data[-5:]]
                    all_lows = [s[1] for s in data[-5:]]
                    DD = min(all_lows)
                    GG = max(all_highs)
                    if ZG > ZD:
                        cur_pivot.append(ZD)
                        cur_pivot.append(ZG)
                        cur_pivot.append('down')
                        cur_pivot.append(len(data) - 5)
                        cur_pivot.append(len(data) - 2)
                        cur_pivot.append(cur_fx[2])
                        cur_pivot.append(GG)
                        cur_pivot.append(DD)
                        cur_pivot.append([[], [], []])
                        cur_pivot.append([[], [], []])
                        cur_pivot.append([])
                        new_pivot = cur_pivot
                        # 中枢形成，判断背驰
                if cur_fx[3] == 'up' and data[-2][1] < data[-5][0]:
                    # 缠论第17课：中枢区间由前三笔的重叠区间确定
                    stroke1_high = max(data[-5][0], data[-4][0])
                    stroke1_low = min(data[-5][1], data[-4][1])
                    stroke2_high = max(data[-4][0], data[-3][0])
                    stroke2_low = min(data[-4][1], data[-3][1])
                    stroke3_high = max(data[-3][0], data[-2][0])
                    stroke3_low = min(data[-3][1], data[-2][1])
                    ZD = max(stroke1_low, stroke2_low, stroke3_low)
                    ZG = min(stroke1_high, stroke2_high, stroke3_high)
                    all_highs = [s[0] for s in data[-5:]]
                    all_lows = [s[1] for s in data[-5:]]
                    DD = min(all_lows)
                    GG = max(all_highs)
                    if ZG > ZD:
                        cur_pivot.append(ZD)
                        cur_pivot.append(ZG)
                        cur_pivot.append('up')
                        cur_pivot.append(len(data) - 5)
                        cur_pivot.append(len(data) - 2)
                        cur_pivot.append(cur_fx[2])
                        cur_pivot.append(GG)
                        cur_pivot.append(DD)
                        cur_pivot.append([[], [], []])
                        cur_pivot.append([[], [], []])
                        cur_pivot.append([])
                        new_pivot = cur_pivot
                if not self.pivot_list:
                    if new_pivot:
                        flag = True
                else:
                    last_pivot = self.pivot_list[-1]
                    if new_pivot and ((new_pivot[2] > last_pivot[3] and cur_fx[3] == 'up') or (
                            new_pivot[3] < last_pivot[2] and cur_fx[3] == 'down')):
                        flag = True
                    if type and new_pivot and type == new_pivot[4]:
                        flag = True

            if len(self.pivot_list) > 0 and not flag:
                last_pivot = self.pivot_list[-1]
                ts = last_pivot[12]
                # 由于stroke/line_change，不断change中枢
                start = last_pivot[5]
                # 防止异常
                if len(data) <= start:
                    self.pivot_list.pop()
                    if not self.pivot_list:
                        return
                    last_pivot = self.pivot_list[-1]
                    start = last_pivot[5]
                buy = last_pivot[10]
                sell = last_pivot[11]
                enter = data[start][2]
                exit = cur_fx[2]
                ee_data = [[data[start - 1], data[start]],
                           [data[len(data) - 2], data[len(data) - 1]]]

                if last_pivot[4] == 'up':
                    # 中枢扩展时重新计算 ZD/ZG/GG/DD
                    # 缠论第17课：ZD/ZG由前三笔确定，GG/DD由所有分型确定
                    if len(data) > start + 3:
                        # 前三笔（用前4个分型计算）
                        s1_high = max(data[start][0], data[start+1][0])
                        s1_low = min(data[start][1], data[start+1][1])
                        s2_high = max(data[start+1][0], data[start+2][0])
                        s2_low = min(data[start+1][1], data[start+2][1])
                        s3_high = max(data[start+2][0], data[start+3][0])
                        s3_low = min(data[start+2][1], data[start+3][1])
                        last_pivot[2] = max(s1_low, s2_low, s3_low)  # ZD
                        last_pivot[3] = min(s1_high, s2_high, s3_high)  # ZG
                        # GG/DD 用所有分型的极值
                        last_pivot[8] = max(s[0] for s in data[start:len(data)])  # GG
                        last_pivot[9] = min(s[1] for s in data[start:len(data)])  # DD
                    if cur_fx[3] == 'up':
                        if sell[0]:
                            # 一卖后的顶分型判断一卖是否有效，无效则将上一个一卖置为无效
                            if sell[0][1] < cur_fx[0] and len(data) - last_pivot[6] < 3:
                                # 置一卖无效
                                sell[0][5] = 0
                                sell[0][6] = self.k_list[-1].datetime
                                sell[0] = []
                                # 置二卖无效
                                if sell[1]:
                                    sell[1][5] = 0
                                    sell[1][6] = self.k_list[-1].datetime
                                    sell[1] = []
                        # P0：笔级别背驰判断
                        pen_diverged = False
                        if self.on_turn(enter, exit, ee_data, last_pivot[4]):
                            pen_diverged = True
                            ChanLog.log(self.freq, self.symbol, f'中枢级别背驰确认(卖): 进入段={enter}, 离开段={exit}')

                        # P2：成交量背驰确认（辅助条件）
                        vol_diverged = False
                        if len(ee_data) >= 2 and len(ee_data[0]) >= 2 and len(ee_data[1]) >= 2:
                            enter_start_idx = ee_data[0][0][4] if len(ee_data[0][0]) > 4 else -1
                            enter_end_idx = ee_data[0][1][4] if len(ee_data[0][1]) > 4 else -1
                            exit_start_idx = ee_data[1][0][4] if len(ee_data[1][0]) > 4 else -1
                            exit_end_idx = ee_data[1][1][4] if len(ee_data[1][1]) > 4 else -1
                            # 索引必须有效（>=0）
                            if enter_start_idx >= 0 and exit_start_idx >= 0:
                                vol_diverged = self._check_volume_divergence(
                                    enter_start_idx, enter_end_idx, exit_start_idx, exit_end_idx
                                )

                        # P6-2: 区分趋势背驰和盘整背驰
                        if pen_diverged:
                            bs_type = self.cal_bs_type()
                            # 一卖需要上升趋势背驰（价格上升趋势中的背驰）
                            is_trend_bc = (bs_type == '上升趋势')

                            # 调试日志：分析一卖为什么没生成
                            pivot_GG = last_pivot[8] if len(last_pivot) > 8 else last_pivot[3]
                            pivot_ZG = last_pivot[3]
                            ChanLog.log(self.freq, self.symbol,
                                       f'背驰触发: 类型={bs_type}, cur_fx_high={cur_fx[0]:.2f}, ZG={pivot_ZG:.2f}, GG={pivot_GG:.2f}')

                            # ============================================================
                            # 缠论原文价格条件（第24课、第29课）- 放宽条件
                            # ============================================================
                            # 趋势背驰一卖：价格突破GG或回到中枢范围内
                            # 盘整背驰一卖：价格回到中枢范围内即可（置信度较低）
                            sell_valid = False
                            if is_trend_bc:
                                # 趋势背驰：突破GG或触及ZG都算
                                if cur_fx[0] >= pivot_GG or cur_fx[0] >= pivot_ZG:
                                    sell_valid = True
                            else:
                                # 盘整背驰：价格回到中枢范围内即可
                                if cur_fx[0] >= last_pivot[2]:  # 不低于ZD
                                    sell_valid = True

                            if sell_valid:
                                ts.append([last_fx[2], cur_fx[2]])
                                if not sell[0]:
                                    # 区间套验证：改为加分项，不作为否决条件
                                    qjt_confirmed, qjt_pivot_list = self.qjt_turn(last_fx[2], cur_fx[2], 'up')
                                    qjt_depth = 0 if qjt_confirmed else -1

                                    # 计算置信度（与一买对称）
                                    confidence = 60  # 基础分
                                    if is_trend_bc:
                                        confidence += 15  # 趋势背驰加分
                                    if qjt_confirmed:
                                        confidence += 15  # 区间套确认加分
                                    if vol_diverged:
                                        confidence += 10  # 成交量背驰加分

                                    ChanLog.log(self.freq, self.symbol,
                                               f'一卖确认: {bs_type}, 区间套={qjt_confirmed}, 成交量={vol_diverged}, 置信度={confidence}')

                                    sell[0] = [cur_fx[2], cur_fx[0], 'S1', self.k_list[-1].datetime, len(data) - 1, 1,
                                               None, bs_type, confidence, qjt_pivot_list, qjt_depth]
                                    self.on_buy_sell(sell[0])
                        if sell[0] and not sell[1]:
                            pos_sell1 = sell[0][4]
                            if len(data) > pos_sell1 + 2:
                                pos_fx = data[pos_sell1 + 2]
                                if pos_fx[3] == 'up':
                                    if pos_fx[1] < sell[0][1]:
                                        # 形成二卖
                                        ans, qjt_pivot_list = self.qjt_trend(last_fx[2], cur_fx[2], 'up')
                                        if ans:
                                            sell[1] = [pos_fx[2], pos_fx[0], 'S2', self.k_list[-1].datetime,
                                                       pos_sell1 + 2, 1, None, self.cal_bs_type(), None, qjt_pivot_list]
                                        self.on_buy_sell(sell[1])
                                    else:
                                        # 一卖无效
                                        sell[0][5] = 0
                                        sell[0][6] = self.k_list[-1].datetime
                                        sell[0] = []

                        if cur_fx[0] < last_pivot[2] and not sell[2] and not buy[0]:
                            # 形成三卖：反弹笔最高点严格低于ZD（不允许触及）
                            # 缠论原文第20课：三卖是"反弹不破ZD"，触及则不是三卖
                            ans, qjt_pivot_list = self.qjt_trend(last_fx[2], cur_fx[2], 'up')
                            if ans:
                                condition = len(data) > 2 and data[-3][0] < last_pivot[2] and data[-3][2] > last_pivot[
                                    1]
                                if not condition:
                                    sell[2] = [cur_fx[2], cur_fx[0], 'S3', self.k_list[-1].datetime, len(data) - 1, 1,
                                               None, self.cal_bs_type(), None, qjt_pivot_list]
                                    self.on_buy_sell(sell[2])

                        # if (not last_fx[1] > last_pivot[3]) and (not cur_fx[0] < last_pivot[2]):
                        #     last_pivot[1] = cur_fx[2]
                        #     last_pivot[6] = len(data) - 1

                    else:
                        # 判断是否延申
                        if (not cur_fx[1] > last_pivot[3]) and (not last_fx[0] < last_pivot[2]):
                            last_pivot[1] = cur_fx[2]
                            last_pivot[6] = len(data) - 1
                        else:
                            # 判断形成第三类买点
                            if cur_fx[1] > last_pivot[2] and not buy[2] and not sell[0]:
                                ans, qjt_pivot_list = self.qjt_trend(last_fx[2], cur_fx[2], 'down')
                                if ans:
                                    condition = len(data) > 2 and data[-3][1] > last_pivot[3] and data[-3][2] > \
                                                last_pivot[1]
                                    if not condition:
                                        sth_pivot = last_pivot
                                        # if len(self.pivot_list) > 1:
                                        #     sth_pivot = self.pivot_list[-2]
                                        buy[2] = [cur_fx[2], cur_fx[1], 'B3', self.k_list[-1].datetime, len(data) - 1,
                                                  1, None, self.cal_bs_type(),
                                                  self.cal_b3_strength(cur_fx[1], sth_pivot), qjt_pivot_list]
                                        ChanLog.log(self.freq, self.symbol, 'B3-pivot')
                                        ChanLog.log(self.freq, self.symbol, sth_pivot)
                                        ChanLog.log(self.freq, self.symbol, buy[2])
                                        self.on_buy_sell(buy[2])


                else:
                    # 中枢扩展时重新计算 ZD/ZG/GG/DD
                    # 缠论第17课：ZD/ZG由前三笔确定，GG/DD由所有分型确定
                    if len(data) > start + 3:
                        # 前三笔（用前4个分型计算）
                        s1_high = max(data[start][0], data[start+1][0])
                        s1_low = min(data[start][1], data[start+1][1])
                        s2_high = max(data[start+1][0], data[start+2][0])
                        s2_low = min(data[start+1][1], data[start+2][1])
                        s3_high = max(data[start+2][0], data[start+3][0])
                        s3_low = min(data[start+2][1], data[start+3][1])
                        last_pivot[2] = max(s1_low, s2_low, s3_low)  # ZD
                        last_pivot[3] = min(s1_high, s2_high, s3_high)  # ZG
                        # GG/DD 用所有分型的极值
                        last_pivot[8] = max(s[0] for s in data[start:len(data)])  # GG
                        last_pivot[9] = min(s[1] for s in data[start:len(data)])  # DD
                    if cur_fx[3] == 'down':
                        if buy[0]:
                            # 一买后的底分型判断一买是否有效，无效则将上一个一买置为无效
                            if buy[0][1] > cur_fx[1] and len(data) - last_pivot[6] < 3:
                                # 置一买无效
                                buy[0][5] = 0
                                buy[0][6] = self.k_list[-1].datetime
                                buy[0] = []
                                # 置二买无效
                                if buy[1]:
                                    buy[1][5] = 0
                                    buy[1][6] = self.k_list[-1].datetime
                                    buy[1] = []

                        # P0：笔级别背驰判断
                        # 使用中枢进入段和离开段的MACD面积对比（通过on_turn方法）
                        pen_diverged = False
                        if self.on_turn(enter, exit, ee_data, last_pivot[4]):
                            pen_diverged = True
                            ChanLog.log(self.freq, self.symbol, f'中枢级别背驰确认: 进入段={enter}, 离开段={exit}')

                        # P2：成交量背驰确认（辅助条件）
                        vol_diverged = False
                        if len(ee_data) >= 2 and len(ee_data[0]) >= 2 and len(ee_data[1]) >= 2:
                            enter_start_idx = ee_data[0][0][4] if len(ee_data[0][0]) > 4 else -1
                            enter_end_idx = ee_data[0][1][4] if len(ee_data[0][1]) > 4 else -1
                            exit_start_idx = ee_data[1][0][4] if len(ee_data[1][0]) > 4 else -1
                            exit_end_idx = ee_data[1][1][4] if len(ee_data[1][1]) > 4 else -1
                            # 索引必须有效（>=0）
                            if enter_start_idx >= 0 and exit_start_idx >= 0:
                                vol_diverged = self._check_volume_divergence(
                                    enter_start_idx, enter_end_idx, exit_start_idx, exit_end_idx
                                )

                        # P6-2: 区分趋势背驰和盘整背驰
                        if pen_diverged:
                            bs_type = self.cal_bs_type()
                            # 一买需要下降趋势背驰（价格下降趋势中的背驰）
                            is_trend_bc = (bs_type == '下降趋势')

                            # 调试日志：分析一买为什么没生成
                            pivot_DD = last_pivot[9] if len(last_pivot) > 9 else last_pivot[2]
                            pivot_ZD = last_pivot[2]
                            ChanLog.log(self.freq, self.symbol,
                                       f'背驰触发: 类型={bs_type}, cur_fx_low={cur_fx[1]:.2f}, ZD={pivot_ZD:.2f}, DD={pivot_DD:.2f}')

                            # ============================================================
                            # 缠论原文价格条件（第24课、第29课）- 放宽条件
                            # ============================================================
                            # 趋势背驰一买：价格跌破DD或回到中枢范围内
                            # 盘整背驰一买：价格回到中枢范围内即可（置信度较低）
                            buy_valid = False
                            if is_trend_bc:
                                # 趋势背驰：跌破DD或触及ZD都算
                                if cur_fx[1] <= pivot_DD or cur_fx[1] <= pivot_ZD:
                                    buy_valid = True
                            else:
                                # 盘整背驰：价格回到中枢范围内即可
                                if cur_fx[1] <= last_pivot[3]:  # 不超过ZG
                                    buy_valid = True

                            if buy_valid:
                                ts.append([last_fx[2], cur_fx[2]])
                                if not buy[0]:
                                    # 区间套验证：改为加分项，不作为否决条件
                                    qjt_confirmed, qjt_pivot_list = self.qjt_turn(last_fx[2], cur_fx[2], 'down')
                                    qjt_depth = 0 if qjt_confirmed else -1

                                    # 计算置信度（区间套确认时加分）
                                    confidence = 60  # 基础分
                                    if is_trend_bc:
                                        confidence += 15  # 趋势背驰加分
                                    if qjt_confirmed:
                                        confidence += 15  # 区间套确认加分
                                    if vol_diverged:
                                        confidence += 10  # 成交量背驰加分

                                    ChanLog.log(self.freq, self.symbol,
                                               f'一买确认: {bs_type}, 区间套={qjt_confirmed}, 成交量={vol_diverged}, 置信度={confidence}')

                                    buy[0] = [cur_fx[2], cur_fx[1], 'B1', self.k_list[-1].datetime, len(data) - 1, 1,
                                              None, bs_type, confidence, qjt_pivot_list, qjt_depth]
                                    if self.gz:
                                        self.gz_prev_last_bs = self.get_prev_last_bs()
                                        self.gz_tmp_bs = buy
                                        buy[0][5] = 0
                                    else:
                                        self.on_buy_sell(buy[0])

                        # 二买生成逻辑（缠论第18课）
                        # 方式1：一买成功后，后续底分型高于一买价格
                        # 方式2：即使没有一买，但底分型高于中枢ZD（独立二买）
                        if not buy[1]:
                            if buy[0] and buy[0][5] == 1:
                                # 方式1：一买成功后的二买
                                pos_buy1 = buy[0][4]
                                if len(data) > pos_buy1 + 2:
                                    pos_fx = data[pos_buy1 + 2]
                                    if pos_fx[3] == 'down':
                                        if pos_fx[1] > buy[0][1]:
                                            # 形成二买
                                            ans, qjt_pivot_list = self.qjt_trend(last_fx[2], cur_fx[2], 'down')
                                            if ans:
                                                sth_pivot = last_pivot
                                                buy[1] = [pos_fx[2], pos_fx[1], 'B2', self.k_list[-1].datetime,
                                                          pos_buy1 + 2, 1, None, self.cal_bs_type(),
                                                          self.cal_b2_strength(pos_fx[1], last_fx, sth_pivot),
                                                          qjt_pivot_list]
                                                self.on_buy_sell(buy[1])
                                        else:
                                            # 一买无效
                                            buy[0][5] = 0
                                            buy[0][6] = self.k_list[-1].datetime
                                            buy[0] = []
                            elif not buy[0] and cur_fx[1] > last_pivot[2]:
                                # 方式2：独立二买（缠论第18课补充）
                                # 当底分型高于中枢下沿ZD时，即使没有一买也可形成二买
                                ans, qjt_pivot_list = self.qjt_trend(last_fx[2], cur_fx[2], 'down')
                                if ans:
                                    sth_pivot = last_pivot
                                    buy[1] = [cur_fx[2], cur_fx[1], 'B2', self.k_list[-1].datetime,
                                              len(data) - 1, 1, None, self.cal_bs_type(),
                                              self.cal_b2_strength(cur_fx[1], last_fx, sth_pivot),
                                              qjt_pivot_list]
                                    ChanLog.log(self.freq, self.symbol, f'独立二买确认: cur_fx[1]={cur_fx[1]:.2f} > ZD={last_pivot[2]:.2f}')
                                    self.on_buy_sell(buy[1])

                        if cur_fx[1] > last_pivot[3] and not buy[2] and not sell[0]:
                            # 形成三买：回调笔最低点严格高于ZG（不允许触及）
                            # 缠论原文第20课：三买是"回调不破ZG"，触及则不是三买
                            ans, qjt_pivot_list = self.qjt_trend(last_fx[2], cur_fx[2], 'down')
                            if ans:
                                condition = len(data) > 2 and data[-3][1] > last_pivot[3] and data[-3][2] > \
                                            last_pivot[1]
                                if not condition:
                                    sth_pivot = last_pivot
                                    # if len(self.pivot_list) > 1:
                                    #     sth_pivot = self.pivot_list[-2]

                                    buy[2] = [cur_fx[2], cur_fx[1], 'B3', self.k_list[-1].datetime, len(data) - 1, 1,
                                              None, self.cal_bs_type(),
                                              self.cal_b3_strength(cur_fx[1], sth_pivot),
                                              qjt_pivot_list]
                                    ChanLog.log(self.freq, self.symbol, 'B3-pivot')
                                    ChanLog.log(self.freq, self.symbol, sth_pivot)
                                    ChanLog.log(self.freq, self.symbol, buy[2])
                                    self.on_buy_sell(buy[2])

                        # if (not cur_fx[1] > last_pivot[3]) and (not last_fx[0] < last_pivot[2]):
                        #     last_pivot[1] = cur_fx[2]
                        #     last_pivot[6] = len(data) - 1
                    else:
                        # 判断是否延申
                        if (not last_fx[1] > last_pivot[3]) and (not cur_fx[0] < last_pivot[2]):
                            last_pivot[1] = cur_fx[2]
                            last_pivot[6] = len(data) - 1
                        else:
                            # 判断形成第三类卖点
                            if cur_fx[1] < last_pivot[3] and not sell[2] and not buy[0]:
                                ans, qjt_pivot_list = self.qjt_trend(last_fx[2], cur_fx[2], 'up')
                                if ans:
                                    condition = len(data) > 2 and data[-3][0] < last_pivot[2] and data[-3][2] > \
                                                last_pivot[1]
                                    if not condition:
                                        sell[2] = [cur_fx[2], cur_fx[0], 'S3', self.k_list[-1].datetime, len(data) - 1,
                                                   1, None, self.cal_bs_type(), None, qjt_pivot_list]
                                        self.on_buy_sell(sell[2])

                # 判断一二类买卖点失效
                if len(self.pivot_list) > 1:
                    pre = self.pivot_list[-2]
                    pre_buy = pre[10]
                    pre_sell = pre[11]
                    if pre_sell[0] and not pre_sell[1]:
                        pos_sell1 = pre_sell[0][4]
                        if len(data) > pos_sell1 + 2:
                            pos_fx = data[pos_sell1 + 2]
                            if pos_fx[3] == 'up':
                                if pos_fx[0] < pre_sell[0][1]:
                                    # 形成二卖
                                    pre_sell[1] = [pos_fx[2], pos_fx[0], 'S2', self.k_list[-1].datetime, pos_sell1 + 2,
                                                   1, None, pre_sell[0][7], None]
                                    self.on_buy_sell(pre_sell[1])
                                else:
                                    # 一卖无效
                                    pre_sell[0][5] = 0
                                    pre_sell[0][6] = self.k_list[-1].datetime
                                    pre_sell[0] = []

                    if pre_buy[0] and pre_buy[0][5] == 1 and not pre_buy[1]:
                        pos_buy1 = pre_buy[0][4]
                        if len(data) > pos_buy1 + 2:
                            pos_fx = data[pos_buy1 + 2]
                            if pos_fx[3] == 'down':
                                if pos_fx[1] > pre_buy[0][1]:
                                    sth_pivot = None
                                    # if len(self.pivot_list) > 2:
                                    #     sth_pivot = self.pivot_list[-3]
                                    if len(self.pivot_list) > 1:
                                        sth_pivot = self.pivot_list[-2]

                                    # 形成二买
                                    pre_buy[1] = [pos_fx[2], pos_fx[1], 'B2', self.k_list[-1].datetime, pos_buy1 + 2, 1,
                                                  None, pre_buy[0][7],
                                                  self.cal_b2_strength(pos_fx[1], data[pos_buy1 + 1], sth_pivot)]
                                    self.on_buy_sell(pre_buy[1])
                                else:
                                    # 一买无效
                                    pre_buy[0][5] = 0
                                    pre_buy[0][6] = self.k_list[-1].datetime
                                    pre_buy[0] = []

                    # B2失效的判断标准：以B2为起点的笔的顶不大于反转笔的顶。
                    # 判断条件有问题
                    if pre_buy[1] and len(data) > pre_buy[1][4] + 2:
                        start = pre_buy[1][4] + 1
                        if data[start] < data[start - 2]:
                            if pre_buy[0]:
                                # 一买无效
                                pre_buy[0][5] = 0
                                pre_buy[0][6] = self.k_list[-1].datetime
                                pre_buy[0] = []
                                pre_buy[1][5] = 0
                                pre_buy[1][6] = self.k_list[-1].datetime
                                pre_buy[1] = []

                    sth_pivot = None
                    # if len(self.pivot_list) > 2:
                    #     sth_pivot = self.pivot_list[-3]
                    if len(self.pivot_list) > 1:
                        sth_pivot = self.pivot_list[-2]
                    self.x_bs_pos(data, pre_buy, pre_sell, pre, sth_pivot)

                if len(self.pivot_list) > 2:
                    pre2 = self.pivot_list[-3]
                    pre_buy = pre2[10]
                    pre_sell = pre2[11]
                    pre1 = self.pivot_list[-2]
                    if pre1[3] < last_pivot[2] and pre2[3] < pre1[2]:
                        # 上升趋势
                        if pre_sell[0]:
                            # 置一卖无效
                            pre_sell[0][5] = 0
                            pre_sell[0][6] = self.k_list[-1].datetime
                            pre_sell[0] = []

                        if pre_sell[1]:
                            # 置二卖无效
                            pre_sell[1][5] = 0
                            pre_sell[1][6] = self.k_list[-1].datetime
                            pre_sell[1] = []
                    # if pre1[2] > last_pivot[3]:
                    #     # 下降趋势
                    #     if pre_buy[0]:
                    #         # 置一买无效
                    #         pre_buy[0][5] = 0
                    #         pre_buy[0][6] = self.k_list[-1].datetime
                    #         pre_buy[0] = []
                    #
                    #     if pre_buy[1]:
                    #         # 置二买无效
                    #         pre_buy[1][5] = 0
                    #         pre_buy[1][6] = self.k_list[-1].datetime
                    #         pre_buy[1] = []
                # 判断三类买卖点失效
                if sell[2] and sell[2][0] < last_pivot[1]:
                    sell[2][5] = 0
                    sell[2][6] = self.k_list[-1].datetime
                    sell[2] = []

                if buy[2] and buy[2][0] < last_pivot[1]:
                    buy[2][5] = 0
                    buy[2][6] = self.k_list[-1].datetime
                    buy[2] = []
                sth_pivot = last_pivot
                # if len(self.pivot_list) > 1:
                #     sth_pivot = self.pivot_list[-2]
                self.x_bs_pos(data, buy, sell, last_pivot, sth_pivot)

            if flag:
                if new_pivot:
                    self.pivot_list.append(new_pivot)
                    # 中枢形成，判断背驰
                    ts = new_pivot[12]
                    buy = new_pivot[10]
                    sell = new_pivot[11]
                    enter = data[new_pivot[5]][2]
                    exit = data[new_pivot[6]][2]
                    ee_data = [[data[new_pivot[5] - 1], data[new_pivot[5]]],
                               [data[new_pivot[6] - 1], data[new_pivot[6]]]]
                    if new_pivot[4] == 'up':
                        if self.on_turn(enter, exit, ee_data, new_pivot[4]) and cur_fx[0] > new_pivot[8]:
                            ts.append([last_fx[2], cur_fx[2]])
                            if not sell[0]:
                                # 形成一卖
                                ans, qjt_pivot_list = self.qjt_turn(last_fx[2], cur_fx[2], 'up')
                                if ans:
                                    sell[0] = [cur_fx[2], cur_fx[0], 'S1', self.k_list[-1].datetime, len(data) - 1, 1,
                                               None, self.cal_bs_type(), None, qjt_pivot_list]
                                    self.on_buy_sell(sell[0])

                    if new_pivot[4] == 'down':
                        # P0：笔级别背驰判断
                        # 使用中枢进入段和离开段的MACD面积对比（通过on_turn方法）
                        pen_diverged = False
                        if self.on_turn(enter, exit, ee_data, new_pivot[4]):
                            pen_diverged = True
                            ChanLog.log(self.freq, self.symbol, f'新中枢-中枢级别背驰确认: 进入段={enter}, 离开段={exit}')

                        if pen_diverged and cur_fx[1] < new_pivot[9]:
                            ts.append([last_fx[2], cur_fx[2]])
                            if not buy[0]:
                                # 形成一买
                                ans, qjt_pivot_list = self.qjt_turn(last_fx[2], cur_fx[2], 'down')
                                if ans:
                                    buy[0] = [cur_fx[2], cur_fx[1], 'B1', self.k_list[-1].datetime, len(data) - 1, 1,
                                              None, self.cal_bs_type(), self.cal_b1_strength(cur_fx[1], cur_fx, new_pivot), qjt_pivot_list]
                                    if self.gz:
                                        self.gz_prev_last_bs = self.get_prev_last_bs()
                                        self.gz_tmp_bs = buy
                                        buy[0][5] = 0
                                    else:
                                        self.on_buy_sell(buy[0])

                    ChanLog.log(self.freq, self.symbol, "pivot_list:")
                    ChanLog.log(self.freq, self.symbol, new_pivot)
                    self.on_trend(new_pivot, data)

    def x_bs_pos(self, data, buy, sell, last_pivot, sth_pivot):
        if not self.gz:
            if buy[0] and len(data) > buy[0][4] and data[buy[0][4]][2] != buy[0][0]:
                pos_fx = data[buy[0][4]]
                buy[0][5] = 0
                buy[0][6] = self.k_list[-1].datetime
                # B1<DD
                buy[0] = [pos_fx[2], pos_fx[1], 'B1', self.k_list[-1].datetime, buy[0][4], 1, None, buy[0][7],
                          self.cal_b1_strength(pos_fx[1], pos_fx, last_pivot)]
                self.on_buy_sell(buy[0])

        if sell[0] and len(data) > sell[0][4] and data[sell[0][4]][2] != sell[0][0]:
            pos_fx = data[sell[0][4]]
            sell[0][5] = 0
            sell[0][6] = self.k_list[-1].datetime
            # S1>GG
            sell[0] = [pos_fx[2], pos_fx[0], 'S1', self.k_list[-1].datetime, sell[0][4], 1, None, sell[0][7], None]
            self.on_buy_sell(sell[0])

        if buy[1] and len(data) > buy[1][4] and data[buy[1][4]][2] != buy[1][0]:
            pos_fx = data[buy[1][4]]
            buy[1][5] = 0
            buy[1][6] = self.k_list[-1].datetime
            if buy[0]:
                if pos_fx[1] > buy[0][1]:
                    # todo 笔延申重新判断为强弱
                    buy[1] = [pos_fx[2], pos_fx[1], 'B2', self.k_list[-1].datetime, buy[1][4], 1, None, buy[1][7],
                              self.cal_b2_strength(pos_fx[1], data[buy[1][4]], sth_pivot)]
                    self.on_buy_sell(buy[1])
                else:
                    # 一买无效
                    buy[0][5] = 0
                    buy[0][6] = self.k_list[-1].datetime

        if sell[1] and len(data) > sell[1][4] and data[sell[1][4]][2] != sell[1][0]:
            pos_fx = data[sell[1][4]]
            sell[1][5] = 0
            sell[1][6] = self.k_list[-1].datetime

            if pos_fx[0] < sell[0][1]:
                sell[1] = [pos_fx[2], pos_fx[0], 'S2', self.k_list[-1].datetime, sell[1][4], 1, None, sell[1][7], None]
                self.on_buy_sell(sell[1])
            else:
                # 一卖无效
                sell[0][5] = 0
                sell[0][6] = self.k_list[-1].datetime

        if buy[2] and len(data) > buy[2][4] and data[buy[2][4]][2] != buy[2][0] and buy[2][0] > last_pivot[1]:
            pos_fx = data[buy[2][4]]
            buy[2][5] = 0
            buy[2][6] = self.k_list[-1].datetime
            if pos_fx[1] > last_pivot[3]:
                buy[2] = [pos_fx[2], pos_fx[1], 'B3', self.k_list[-1].datetime, buy[2][4], 1, None, buy[2][7],
                          self.cal_b3_strength(pos_fx[1], sth_pivot)]
                ChanLog.log(self.freq, self.symbol, 'B3-pivot')
                ChanLog.log(self.freq, self.symbol, sth_pivot)
                ChanLog.log(self.freq, self.symbol, buy[2])
                self.on_buy_sell(buy[2])
        if sell[2] and len(data) > sell[2][4] and data[sell[2][4]][2] != sell[2][0] and sell[2][0] > last_pivot[1]:
            pos_fx = data[sell[2][4]]
            sell[2][5] = 0
            sell[2][6] = self.k_list[-1].datetime
            if pos_fx[0] < last_pivot[2]:
                sell[2] = [pos_fx[2], pos_fx[0], 'S3', self.k_list[-1].datetime, sell[2][4], 1, None, sell[2][7], None]
                self.on_buy_sell(sell[2])

    def cal_bs_type(self, pivot=None):
        """判断走势类型（趋势/盘整）

        缠论原文（第17课、第20课）：
        - 趋势定义：连续两个同级别中枢不重叠，且位置同向移动
        - 上升趋势：前中枢ZG < 当前中枢ZD（中枢不重叠，位置抬高）
        - 下降趋势：前中枢ZD > 当前中枢ZG（中枢不重叠，位置降低）
        - 有重叠 = 中枢扩张 = 盘整

        Args:
            pivot: 指定中枢，默认使用最后两个中枢

        Returns:
            str: '上升趋势'、'下降趋势' 或 '盘整'
        """
        if len(self.pivot_list) < 2:
            return '盘整'

        if pivot is None:
            pre = self.pivot_list[-2]
            cur = self.pivot_list[-1]
        else:
            idx = self.pivot_list.index(pivot)
            if idx < 1:
                return '盘整'
            pre = self.pivot_list[idx - 1]
            cur = pivot

        pre_ZD = pre[2]  # 前中枢下沿
        pre_ZG = pre[3]  # 前中枢上沿
        cur_ZD = cur[2]  # 当前中枢下沿
        cur_ZG = cur[3]  # 当前中枢上沿

        # 上升趋势：前中枢ZG < 当前中枢ZD（中枢不重叠，位置抬高）
        if pre_ZG < cur_ZD:
            return '上升趋势'
        # 下降趋势：前中枢ZD > 当前中枢ZG（中枢不重叠，位置降低）
        if pre_ZD > cur_ZG:
            return '下降趋势'

        # 放宽趋势：中枢位置同向移动（允许部分重叠）
        # 上升趋势：前中枢ZG < 当前中枢ZG（位置抬高）
        if pre_ZG < cur_ZG and pre_ZD < cur_ZD:
            return '上升趋势'
        # 下降趋势：前中枢ZD > 当前中枢ZD（位置降低）
        if pre_ZD > cur_ZD and pre_ZG > cur_ZG:
            return '下降趋势'

        # 有重叠 = 中枢扩张 = 盘整
        return '盘整'

    def _check_volume_divergence(self, enter_start_idx, enter_end_idx, exit_start_idx, exit_end_idx):
        """检查成交量背驰（缠论第12课：量能衰减确认背驰）

        核心逻辑：离开段成交量应小于进入段，表示动能衰竭

        Args:
            enter_start_idx: 进入段起始K线索引
            enter_end_idx: 进入段结束K线索引
            exit_start_idx: 离开段起始K线索引
            exit_end_idx: 离开段结束K线索引

        Returns:
            bool: 是否成交量背驰
        """
        if not self.k_list or len(self.k_list) < max(enter_end_idx, exit_end_idx) + 1:
            return False

        # 计算进入段总成交量
        enter_vol = 0.0
        for i in range(enter_start_idx, min(enter_end_idx + 1, len(self.k_list))):
            enter_vol += self.k_list[i].volume

        # 计算离开段总成交量
        exit_vol = 0.0
        for i in range(exit_start_idx, min(exit_end_idx + 1, len(self.k_list))):
            exit_vol += self.k_list[i].volume

        if enter_vol <= 0:
            return False

        vol_ratio = exit_vol / enter_vol

        # 成交量衰减超过30%才算背驰
        is_vol_divergence = vol_ratio < 0.7

        ChanLog.log(self.freq, self.symbol,
                   f'成交量背驰检查: 进入段={enter_vol:.2f}, 离开段={exit_vol:.2f}, '
                   f'比例={vol_ratio:.2%}, 结果={"背驰" if is_vol_divergence else "非背驰"}')

        return is_vol_divergence

    def cal_b1_strength(self, price, cur_fx, last_pivot):
        """
        计算B1买点的强度
        B1买点：在中枢下方，向下离开中枢时的第一类买点

        强度判断逻辑：
        - 超强：大幅跌破中枢低点DD（price < last_pivot[9]）
        - 强：跌破中枢下沿ZD（price < last_pivot[2]）
        - 中：接近中枢下沿ZD（price < last_pivot[3]）
        - 弱：在中枢内部或边缘

        Args:
            price: B1买点价格
            cur_fx: 当前底分型 [high, low, datetime, direction, index]
            last_pivot: 上一个中枢

        Returns:
            强度：'超强'/'强'/'中'/'弱'
        """
        if last_pivot:
            # price = cur_fx[1]（底分型的低点）
            DD = last_pivot[9]  # 中枢低点
            ZD = last_pivot[2]  # 中枢下沿
            ZG = last_pivot[3]  # 中枢上沿

            # 计算中枢高度，用于判断"大幅跌破"
            pivot_height = ZG - ZD
            threshold = DD - pivot_height * 0.5  # 跌破DD超过中枢高度的50%

            if price < threshold:
                return '超强'
            elif price < DD:
                return '强'
            elif price < ZD:
                return '中'
        return '弱'

    def cal_b3_strength(self, price, last_pivot):
        if last_pivot:
            if price > last_pivot[8]:
                return '强'
        return '弱'

    def calculate_stop_loss_target(self, bs_name, pivot, cur_fx):
        """计算买卖点的止损价和目标价

        缠论原文（第100-102课 防狼术）：
        - 做多止损：一买/二买用底分型最低点，三买用中枢ZD
        - 做空止损：一卖/二卖用顶分型最高点，三卖用中枢ZG
        - 目标价：根据中枢高度计算

        Args:
            bs_name: 'B1'/'B2'/'B3'/'S1'/'S2'/'S3'
            pivot: 中枢数据 [date1, date2, ZD, ZG, type, ...]
            cur_fx: 当前分型 [high, low, datetime, direction, k_index]

        Returns:
            tuple: (stop_loss, take_profit)
        """
        stop_loss = 0.0
        take_profit = 0.0

        if pivot is None:
            return stop_loss, take_profit

        ZD = pivot[2]   # 中枢下沿
        ZG = pivot[3]   # 中枢上沿
        GG = pivot[8] if len(pivot) > 8 else pivot[3]  # 中枢最高点
        DD = pivot[9] if len(pivot) > 9 else pivot[2]  # 中枢最低点
        zs_height = ZG - ZD  # 中枢高度

        if bs_name in ('B1', 'B2', 'B3'):
            # 做多止损和目标
            if bs_name == 'B3':
                stop_loss = ZD
                take_profit = GG + zs_height
            elif bs_name == 'B2':
                stop_loss = cur_fx[1] if cur_fx else DD
                take_profit = GG
            else:
                stop_loss = cur_fx[1] if cur_fx else DD
                take_profit = ZG

        elif bs_name in ('S1', 'S2', 'S3'):
            # 做空止损和目标
            if bs_name == 'S3':
                stop_loss = ZG
                take_profit = DD - zs_height
            elif bs_name == 'S2':
                stop_loss = cur_fx[0] if cur_fx else GG
                take_profit = DD
            else:
                stop_loss = cur_fx[0] if cur_fx else GG
                take_profit = ZD

        return stop_loss, take_profit

    def cal_b2_strength(self, price, fx, last_pivot):
        if last_pivot:
            if price > last_pivot[3]:
                return '超强'
            if fx[0] > last_pivot[3]:
                return '强'
            if fx[0] > last_pivot[2]:
                return '中'
        return '弱'

    def cal_macd(self, start, end):
        """
        计算MACD面积（区分红绿柱）

        Args:
            start: 起始K线索引
            end: 结束K线索引

        Returns:
            dict: {
                'total': 总面积（绝对值之和）,
                'positive': 红柱面积（零轴上方）,
                'negative': 绿柱面积（零轴下方，取绝对值）
            }
        """
        result = {'total': 0, 'positive': 0, 'negative': 0}
        if start >= end:
            return result
        if self.include:
            close_list = np.array([x.close_price for x in self.chan_k_list], dtype=np.double)
        else:
            close_list = np.array([x.close_price for x in self.k_list], dtype=np.double)
        dif, dea, macd = tl.MACD(close_list, fastperiod=12,
                                 slowperiod=26, signalperiod=9)
        for i, v in enumerate(macd.tolist()):
            if start <= i <= end:
                v_rounded = round(v, 4)
                if v_rounded >= 0:
                    result['positive'] += v_rounded  # 红柱（零轴上方）
                else:
                    result['negative'] += abs(v_rounded)  # 绿柱（零轴下方，取绝对值）
                result['total'] += abs(v_rounded)
        result['total'] = round(result['total'], 4)
        result['positive'] = round(result['positive'], 4)
        result['negative'] = round(result['negative'], 4)
        return result

    def _get_prev_pivot_leaving_strength(self, cur_pivot, type):
        """获取前一个中枢的离开段力度（用于趋势背驰比较）

        缠论原文（第24课、第25课）：
        趋势背驰比较的是：前一个中枢的离开段 vs 当前中枢的离开段

        Args:
            cur_pivot: 当前中枢
            type: 'up' 或 'down'（中枢方向）

        Returns:
            (strength, macd_area, ee_data): 力度、MACD面积、分型数据
        """
        if len(self.pivot_list) < 2:
            return 0.0, 0.0, None

        # 获取前一个中枢
        idx = self.pivot_list.index(cur_pivot) if cur_pivot in self.pivot_list else len(self.pivot_list) - 1
        if idx < 1:
            return 0.0, 0.0, None

        prev_pivot = self.pivot_list[idx - 1]
        data = self.stroke_list

        # 前中枢离开段 = 前中枢结束位置到前中枢后第一个反向分型
        prev_exit_time = prev_pivot[1]  # 前中枢结束时间

        # 查找前中枢离开段的分型
        leaving_start_fx = None
        leaving_end_fx = None
        for i, fx in enumerate(data):
            if fx[2] >= prev_exit_time:
                if leaving_start_fx is None:
                    leaving_start_fx = fx
                elif fx[3] != leaving_start_fx[3]:  # 方向相反
                    leaving_end_fx = fx
                    break

        if leaving_start_fx is None or leaving_end_fx is None:
            return 0.0, 0.0, None

        # 计算力度
        strength = self._calculate_movement_strength(leaving_start_fx, leaving_end_fx)

        # 计算MACD
        start_idx = leaving_start_fx[4] if len(leaving_start_fx) > 4 else 0
        end_idx = leaving_end_fx[4] if len(leaving_end_fx) > 4 else 0
        macd_info = self.cal_macd(start_idx, end_idx)

        if type == 'down':
            macd_area = macd_info.get('negative', 0)
        else:
            macd_area = macd_info.get('positive', 0)

        ee_data = [[leaving_start_fx, leaving_end_fx]]
        return strength, macd_area, ee_data

    def _check_leaving_strength_monotonic_decrease(self, cur_pivot, type):
        """校验趋势背驰的力度单调递减（缠论第33课）

        缠论原文（第33课）：
        趋势背驰的必要条件：所有离开中枢的笔，其力度必须严格递减。
        如果中间有任何一笔力度回升（非递减），则背驰不成立。

        Args:
            cur_pivot: 当前中枢
            type: 'up' 或 'down'

        Returns:
            bool: 是否满足力度单调递减
        """
        if len(self.pivot_list) < 3:
            return True  # 中枢数不足，不做校验

        # 收集所有中枢的离开段力度
        leaving_strengths = []
        data = self.stroke_list

        for pivot in self.pivot_list:
            exit_time = pivot[1]  # 中枢结束时间
            leaving_start_fx = None
            leaving_end_fx = None

            for fx in data:
                if fx[2] >= exit_time:
                    if leaving_start_fx is None:
                        leaving_start_fx = fx
                    elif fx[3] != leaving_start_fx[3]:
                        leaving_end_fx = fx
                        break

            if leaving_start_fx and leaving_end_fx:
                s = self._calculate_movement_strength(leaving_start_fx, leaving_end_fx)
                leaving_strengths.append(s)

        if len(leaving_strengths) < 3:
            return True  # 离开段不足3段，不做校验

        # 校验力度是否严格递减
        for i in range(1, len(leaving_strengths)):
            if leaving_strengths[i] >= leaving_strengths[i - 1]:
                ChanLog.log(self.freq, self.symbol,
                           f'力度单调递减校验失败: 第{i}段力度={leaving_strengths[i]:.4f} >= 第{i-1}段力度={leaving_strengths[i-1]:.4f}')
                return False

        return True

    def _calculate_movement_strength(self, start_fx, end_fx):
        """计算走势力度（缠论第5课原文定义）

        力度 = 价格幅度 × 0.6 + 斜率 × 0.4

        参考 engine_new.py _calculate_movement_strength (行2959-2987)

        Args:
            start_fx: 起始分型 [high, low, datetime, direction, k_index]
            end_fx: 结束分型 [high, low, datetime, direction, k_index]

        Returns:
            力度值
        """
        if start_fx is None or end_fx is None:
            return 0.0

        # 价格幅度
        if start_fx[3] == 'down':  # 底分型起始，向上笔
            price_amplitude = abs(end_fx[0] - start_fx[1])
        else:  # 顶分型起始，向下笔
            price_amplitude = abs(end_fx[1] - start_fx[0])

        # 时间效率（斜率）
        kline_count = max(abs(end_fx[4] - start_fx[4]), 1)
        slope = price_amplitude / kline_count

        # 综合力度 = 价格幅度 × 0.6 + 斜率 × 0.4
        strength = price_amplitude * 0.6 + slope * 0.4
        return max(strength, 1e-10)

    def cal_pen_macd(self, pen_index=None):
        """
        P0: 计算笔级别MACD
        Args:
            pen_index: 如果指定，只计算某笔的MACD；否则计算所有笔
        Returns:
            None（结果存入 self.pen_macd）
        """
        if len(self.pens) < 2:
            return

        # 构建笔的收盘价序列
        pen_close_prices = np.array([pen['close_price'] for pen in self.pens], dtype=np.double)

        # 计算笔级别MACD
        try:
            dif, dea, macd = tl.MACD(pen_close_prices, fastperiod=12, slowperiod=26, signalperiod=9)
        except:
            # 笔数据不足，无法计算
            return

        # 计算每笔的MACD面积（即该笔对应MACD值的绝对值）
        # 注意：这里pen_index是指笔在self.pens中的索引
        for i, pen in enumerate(self.pens):
            if i < len(macd):
                macd_value = macd[i]
                if math.isnan(macd_value):
                    macd_value = 0
                self.pen_macd[i] = {
                    'dif': float(dif[i]) if not math.isnan(dif[i]) else 0,
                    'dea': float(dea[i]) if not math.isnan(dea[i]) else 0,
                    'macd': float(macd_value),
                    'area': abs(float(macd_value))  # MACD柱子的面积（绝对值）
                }

    def check_pen_divergence(self, pen_index):
        """
        P0: 判断某笔是否与前一笔形成背驰
        Args:
            pen_index: 当前笔在self.pens中的索引
        Returns:
            True表示背驰，False表示未背驰
        """
        if pen_index < 1 or pen_index >= len(self.pens):
            return False

        current_pen = self.pens[pen_index]
        prev_pen = self.pens[pen_index - 1]

        # 需要两笔方向相反
        if current_pen['direction'] == prev_pen['direction']:
            return False

        # 确保已计算MACD
        if pen_index not in self.pen_macd or (pen_index - 1) not in self.pen_macd:
            self.cal_pen_macd()

        if pen_index not in self.pen_macd or (pen_index - 1) not in self.pen_macd:
            return False

        # 判断底背驰（向下笔）
        if current_pen['direction'] == 'down':
            # 价格创新低，但MACD面积缩小
            price_lower = current_pen['low_price'] < prev_pen['low_price']
            macd_shrink = self.pen_macd[pen_index]['area'] < self.pen_macd[pen_index - 1]['area']
            return price_lower and macd_shrink

        # 判断顶背驰（向上笔）
        elif current_pen['direction'] == 'up':
            # 价格创新高，但MACD面积缩小
            price_higher = current_pen['high_price'] > prev_pen['high_price']
            macd_shrink = self.pen_macd[pen_index]['area'] < self.pen_macd[pen_index - 1]['area']
            return price_higher and macd_shrink

        return False

    def on_turn(self, start, end, ee_data, type):
        """背驰判断（缠论原文多维度力度比较）

        缠论原文核心定义（第5课、第15课、第24课、第25课）：
        1. 力度 = 价格幅度 × 0.6 + 斜率 × 0.4（第5课原文定义）
        2. 背驰 = 离开段力度 < 进入段力度（第15课）
        3. MACD是辅助工具，不是判断依据（第25课）

        Args:
            start: 进入段时间
            end: 离开段时间
            ee_data: [[进入段起始分型, 进入段结束分型], [离开段起始分型, 离开段结束分型]]
            type: 'up' 或 'down'（中枢方向）

        Returns:
            bool: 是否背驰
        """
        # ============================================================
        # 第一步：力度计算（核心维度）
        # ============================================================
        enter_strength = 0.0
        exit_strength = 0.0

        if len(ee_data) >= 2 and len(ee_data[0]) >= 2 and len(ee_data[1]) >= 2:
            enter_start = ee_data[0][0]
            enter_end = ee_data[0][1]
            exit_start = ee_data[1][0]
            exit_end = ee_data[1][1]

            enter_strength = self._calculate_movement_strength(enter_start, enter_end)
            exit_strength = self._calculate_movement_strength(exit_start, exit_end)

        # 力度比
        if enter_strength > 0:
            strength_ratio = exit_strength / enter_strength
        else:
            strength_ratio = 1.0

        # ============================================================
        # 第二步：判断走势类型
        # ============================================================
        bs_type = self.cal_bs_type()
        is_trend = (bs_type == '趋势')

        # ============================================================
        # 第三步：结构背驰判定（缠论原文阈值）
        # ============================================================
        # 缠论原文：趋势背驰要求力度衰减，盘整背驰条件更宽松
        if is_trend:
            structure_bc = strength_ratio < 0.9  # 趋势：力度衰减10%即算背驰
        else:
            structure_bc = strength_ratio < 0.95  # 盘整：力度衰减5%即算背驰

        # ============================================================
        # 第四步：MACD辅助确认（非主要判断）
        # ============================================================
        start_macd = self.macd.get(start, {'total': 0, 'positive': 0, 'negative': 0})
        end_macd = self.macd.get(end, {'total': 0, 'positive': 0, 'negative': 0})

        # 兼容旧格式
        if isinstance(start_macd, (int, float)):
            start_macd = {'total': start_macd, 'positive': start_macd, 'negative': start_macd}
        if isinstance(end_macd, (int, float)):
            end_macd = {'total': end_macd, 'positive': end_macd, 'negative': end_macd}

        # 根据方向选择对应颜色的MACD面积
        if type == 'down':
            enter_macd = start_macd.get('negative', start_macd.get('total', 0))
            exit_macd = end_macd.get('negative', end_macd.get('total', 0))
        else:
            enter_macd = start_macd.get('positive', start_macd.get('total', 0))
            exit_macd = end_macd.get('positive', end_macd.get('total', 0))

        macd_confirm = False
        if enter_macd > 0:
            macd_ratio = exit_macd / enter_macd
            macd_confirm = macd_ratio < 0.8  # MACD面积衰减20%作为辅助确认

        # ============================================================
        # 第五步：综合判定
        # ============================================================
        # 缠论原则：结构优先，MACD辅助
        if structure_bc:
            ChanLog.log(self.freq, self.symbol,
                       f'背驰确认: {bs_type}, 力度比={strength_ratio:.2%}, MACD确认={macd_confirm}')
            return True
        elif macd_confirm and strength_ratio < 0.95:
            # 结构未达标但MACD确认，且力度有明显衰减，也算弱背驰
            ChanLog.log(self.freq, self.symbol,
                       f'弱背驰: {bs_type}, 力度比={strength_ratio:.2%}, MACD确认')
            return True

        return False

    def qjt_turn0(self, start, end, type):
        # 区间套判断背驰：判断有无中枢和qjt_trend相同
        qjt_pivot_list = []
        if not self.qjt:
            return True, qjt_pivot_list
        chan = self.next
        if not chan:
            return True, qjt_pivot_list
        ans = False
        ChanLog.log(self.freq, self.symbol, '区间套判断背驰：')
        ChanLog.log(self.freq, self.symbol, self.freq)
        ChanLog.log(self.freq, self.symbol, str(self.pivot_list[-1]) + ':' + str(start))
        while chan:
            last_pivot = chan.pivot_list[-1]
            tmp = False
            if last_pivot[1] > start:
                if last_pivot[11][0]:
                    tmp = True
                    start = chan.stroke_list[last_pivot[11][0][4] - 1][2]
                    if chan.build_line_pivot:
                        start = chan.stroke_list[last_pivot[11][0][4] - 1][2]
                if last_pivot[10][0]:
                    tmp = True
                    start = chan.stroke_list[last_pivot[10][0][4] - 1][2]
                    if chan.build_line_pivot:
                        start = chan.stroke_list[last_pivot[10][0][4] - 1][2]
            ChanLog.log(self.freq, self.symbol, chan.freq + ':' + str(tmp))
            ChanLog.log(self.freq, self.symbol, str(last_pivot) + ':' + str(start))
            ans = ans or tmp
            chan = chan.next
        return ans, qjt_pivot_list

    def qjt_turn1(self, start, end, type):
        # 区间套判断背驰: 利用低级别的买卖点
        qjt_pivot_list = []
        if not self.qjt:
            return True, qjt_pivot_list
        chan = self.next
        if not chan:
            return True, qjt_pivot_list
        ans = False
        ChanLog.log(self.freq, self.symbol, '区间套判断背驰：')
        ChanLog.log(self.freq, self.symbol, self.freq)
        ChanLog.log(self.freq, self.symbol, str(self.pivot_list[-1]) + ':' + str(start))
        while chan:
            tmp = False
            for i in range(-1, -len(chan.buy_list), -1):
                buy_dt = chan.buy_list[i]
                if buy_dt >= end and buy_dt < start:
                    tmp = True
                    break
            tmp = False
            for i in range(-1, -len(chan.sell_list), -1):
                sell_dt = chan.sell_list[i]
                if sell_dt >= end and sell_dt < start:
                    tmp = True
                    break
            ans = ans or tmp
            chan = chan.next
        return ans, qjt_pivot_list

    def qjt_pivot(self, data, type):
        chan_pivot = Chan_Class(freq=self.freq, symbol=self.symbol, sell=None, buy=None, include=self.include,
                                include_feature=self.include_feature, build_line_pivot=self.build_line_pivot, qjt=False)
        chan_pivot.macd = self.macd
        chan_pivot.k_list = self.chan_k_list
        new_data = []
        for d in data:
            new_data.append(d)
            chan_pivot.on_pivot(new_data, type)
        return chan_pivot.pivot_list

    def qjt_turn(self, start, end, type):
        """区间套验证（缠论第27课原文）

        缠论原文核心：区间套是"精确定位"机制，不是"否决"机制
        - 大级别背驰定方向
        - 中级别找买卖点结构
        - 小级别精确定位入场时机

        区间套未确认不代表买卖点无效，只是精度不够。

        Args:
            start: 背驰段开始时间
            end: 背驰段结束时间
            type: 'up' 或 'down'（中枢方向）

        Returns:
            tuple: (是否确认, 低级别中枢列表)
        """
        qjt_pivot_list = []
        chan = self.next
        if not chan:
            return True, qjt_pivot_list  # 无低级别数据，不阻挡

        ans = True
        ChanLog.log(self.freq, self.symbol, f'区间套验证: type={type}')

        while chan:
            tmp = False
            data = []
            if chan.build_line_pivot:
                for i in range(-1, -len(chan.line_list), -1):
                    d = chan.line_list[i]
                    if d[2] >= start:
                        if d[2] <= end:
                            data.append(d)
                    else:
                        if type == 'up' and d[3] == 'down':
                            data.append(d)
                        if type == 'down' and d[3] == 'up':
                            data.append(d)
                        break
            else:
                for i in range(-1, -len(chan.stroke_list), -1):
                    d = chan.stroke_list[i]
                    if d[2] >= start:
                        if d[2] <= end:
                            data.append(d)
                    else:
                        if type == 'up' and d[3] == 'down':
                            data.append(d)
                        if type == 'down' and d[3] == 'up':
                            data.append(d)
                        break
            data.reverse()
            chan_pivot_list = chan.qjt_pivot(data, type)
            qjt_pivot_list.append(chan_pivot_list)

            # ============================================================
            # 关键修正：区间套是确认机制，不是否决机制（缠论第27课原文）
            # ============================================================
            if chan_pivot_list and len(chan_pivot_list[-1][12]) > 0:
                # 有背驰段，精确确认
                ts_item = chan_pivot_list[-1][12][-1]
                start = ts_item[0]
                end = ts_item[1]
                tmp = True
                ChanLog.log(self.freq, self.symbol, f'区间套确认(背驰段): ts=[{start}, {end}]')
            else:
                # 无背驰段，标记为"未精确定位"但不否决
                # 缠论原文：区间套未确认不代表买卖点无效，只是精度不够
                ChanLog.log(self.freq, self.symbol, '区间套未精确定位: 无背驰段(买卖点仍有效)')
                tmp = True  # ← 关键修正：返回True，不否决

            ans = tmp and ans
            chan = chan.next

        return ans, qjt_pivot_list

    def qjt_trend0(self, start, end, type):
        # 区间套判断有无走势：判断有无中枢
        qjt_pivot_list = []
        if not self.qjt:
            return True, qjt_pivot_list
        ChanLog.log(self.freq, self.symbol, '区间套判断有无走势：')
        ChanLog.log(self.freq, self.symbol, str(start) + '--' + str(end))
        ChanLog.log(self.freq, self.symbol, str(self.pivot_list[-1]))
        chan = self.next
        if not chan:
            return True, qjt_pivot_list
        ans = False
        while chan:
            tmp = False
            for i in range(-1, -len(chan.pivot_list), -1):
                last_pivot = chan.pivot_list[i]
                if last_pivot[1] <= end and last_pivot[0] >= start:
                    tmp = True
                    break
            ans = ans or tmp
            ChanLog.log(self.freq, self.symbol, chan.freq + ':' + str(tmp))
            chan = chan.next
        return ans, qjt_pivot_list

    def qjt_trend(self, start, end, type):
        # 区间套判断有无走势：重新形成中枢
        qjt_pivot_list = []
        if not self.qjt:
            return True, qjt_pivot_list
        chan = self.next
        if not chan:
            return True, qjt_pivot_list
        ans = False
        ChanLog.log(self.freq, self.symbol, '区间套判断背驰：')
        ChanLog.log(self.freq, self.symbol, self.freq)

        while chan:
            tmp = False
            data = []
            if chan.build_line_pivot:
                for i in range(-1, -len(chan.line_list), -1):
                    d = chan.line_list[i]
                    if d[2] >= start:
                        if d[2] <= end:
                            data.append(d)
                    else:
                        if type == 'up' and d[3] == 'down':
                            data.append(d)
                        if type == 'down' and d[3] == 'up':
                            data.append(d)
                        break
            else:
                for i in range(-1, -len(chan.stroke_list), -1):
                    d = chan.stroke_list[i]
                    if d[2] >= start:
                        if d[2] <= end:
                            data.append(d)
                    else:
                        if type == 'up' and d[3] == 'down':
                            data.append(d)
                        if type == 'down' and d[3] == 'up':
                            data.append(d)
                        break
            data.reverse()
            chan_pivot_list = chan.qjt_pivot(data, type)
            ChanLog.log(self.freq, self.symbol, str(self.pivot_list[-1]) + ':' + str(start))
            ChanLog.log(self.freq, self.symbol, chan_pivot_list)
            qjt_pivot_list.append(chan_pivot_list)
            if not len(chan_pivot_list) > 0:
                chan = chan.next
            else:
                tmp = True
            ans = tmp or ans
            if ans:
                break

        return ans, qjt_pivot_list

    def on_gz(self):
        """共振处理：只关联上一个级别"""
        # 暂时 只处理买点B1
        chan = self.prev
        if not chan:
            return
        last_bs = None
        if len(chan.buy_list) > 0:
            last_bs = chan.buy_list[-1]
        # B1不成立
        if self.gz_delay_k_num >= self.gz_delay_k_max or (len(self.gz_tmp_bs) > 4 and self.gz_tmp_bs[0][5] == 0) or not \
                self.gz_tmp_bs[0]:
            self.gz_delay_k_num = 0
            self.gz_prev_last_bs = None
            self.gz_tmp_bs[0] = []
            self.gz_tmp_bs = None
        else:
            if last_bs and last_bs != self.gz_prev_last_bs and (
                    last_bs[1] == 'B2' or last_bs[2] == 'B3' or last_bs[2] == 'B1'):
                ChanLog.log(self.freq, self.symbol, 'gz:' + str(self.gz_delay_k_num) + ':')
                ChanLog.log(self.freq, self.symbol, last_bs)
                ChanLog.log(self.freq, self.symbol, self.gz_prev_last_bs)
                ChanLog.log(self.freq, self.symbol, self.gz_tmp_bs[0])
                if self.gz_tmp_bs[0]:
                    self.gz_tmp_bs[0][3] = self.k_list[-1].datetime
                    self.gz_tmp_bs[0][5] = 1
                    self.on_buy_sell(self.gz_tmp_bs[0])
                self.gz_delay_k_num = 0
                self.gz_prev_last_bs = None
                self.gz_tmp_bs = None

    def get_prev_last_bs(self):
        chan = self.prev
        if not chan or len(chan.buy_list) < 1:
            return None
        return chan.buy_list[-1]

    def check_next_level_bs(self, start_time, end_time):
        """
        P1: 检查下一级别在指定时间范围内是否有买卖点
        Args:
            start_time: 开始时间（datetime）
            end_time: 结束时间（datetime）
        Returns:
            True表示有买卖点确认，False表示无
        """
        if not self.next:
            return False

        next_chan = self.next
        # 检查下一级别的买入信号
        for buy_signal in next_chan.buy_list:
            signal_time = buy_signal[0]
            if start_time <= signal_time <= end_time:
                return True

        # 检查下一级别的卖出信号
        for sell_signal in next_chan.sell_list:
            signal_time = sell_signal[0]
            if start_time <= signal_time <= end_time:
                return True

        return False

    def check_next_level_divergence(self, start_time, end_time):
        """
        P1: 检查下一级别在指定时间范围内是否有背驰
        Args:
            start_time: 开始时间（datetime）
            end_time: 结束时间（datetime）
        Returns:
            True表示有背驰，False表示无
        """
        if not self.next:
            return False

        next_chan = self.next

        # 检查下一级别的背驰笔
        # 通过检查笔的结束时间来判断
        for i, pen in enumerate(next_chan.pens):
            pen_end_time = pen['end_fx'][2]  # 分型的datetime
            if start_time <= pen_end_time <= end_time:
                # 检查这笔是否背驰
                if next_chan.check_pen_divergence(i):
                    return True

        return False

    def check_multi_level_confirmation(self, signal_time, start_ref_time=None, end_ref_time=None):
        """
        P1: 多级别验证（增强版买卖点确认）
        Args:
            signal_time: 当前级别信号时间（datetime）
            start_ref_time: 参考开始时间（datetime），可选
            end_ref_time: 参考结束时间（datetime），可选
        Returns:
            '强': 多级别确认（30分+5分都有）
            '中': 下一级别确认
            '弱': 无确认
        """
        if not start_ref_time or not end_ref_time:
            # 默认时间范围：往前推20根笔的时间
            if len(self.pens) >= 20:
                start_ref_time = self.pens[-20]['end_fx'][2]
            elif len(self.pens) > 0:
                start_ref_time = self.pens[0]['end_fx'][2]
            else:
                start_ref_time = signal_time - timedelta(days=30)
            end_ref_time = signal_time

        if not self.next:
            return '弱'

        # 检查30分钟级别
        min30_has_bs = self.check_next_level_bs(start_ref_time, end_ref_time)
        min30_has_div = self.check_next_level_divergence(start_ref_time, end_ref_time)

        if not (min30_has_bs or min30_has_div):
            return '弱'

        # 检查5分钟级别
        if self.next and self.next.next:
            min5_has_bs = self.next.check_next_level_bs(start_ref_time, end_ref_time)
            min5_has_div = self.next.check_next_level_divergence(start_ref_time, end_ref_time)

            if min5_has_bs or min5_has_div:
                return '强'

        return '中'

    def on_trend(self, new_pivot, data):
        # 走势列表[[日期1，日期2，走势类型，[背驰点], [中枢]]]
        if not self.trend_list:
            type = 'pzup'
            if new_pivot[4] == 'down':
                type = 'pzdown'
            self.trend_list.append([new_pivot[0], new_pivot[1], type, [], [len(self.pivot_list) - 1]])
        else:
            last_trend = self.trend_list[-1]
            if last_trend[2] == 'up':
                if new_pivot[4] == 'up':
                    last_trend[1] = new_pivot[1]
                    last_trend[4].append(len(self.pivot_list) - 1)
                else:
                    self.trend_list.append([new_pivot[0], new_pivot[1], 'pzdown', [], [len(self.pivot_list) - 1]])
            if last_trend[2] == 'down':
                if new_pivot[4] == 'down':
                    last_trend[1] = new_pivot[1]
                    last_trend[4].append(len(self.pivot_list) - 1)
                else:
                    self.trend_list.append([new_pivot[0], new_pivot[1], 'pzup', [], [len(self.pivot_list) - 1]])
            if last_trend[2] == 'pzup':
                if new_pivot[4] == 'up':
                    last_trend[1] = new_pivot[1]
                    last_trend[4].append(len(self.pivot_list) - 1)
                    last_trend[2] = 'up'
                else:
                    self.trend_list.append([new_pivot[0], new_pivot[1], 'pzdown', [], [len(self.pivot_list) - 1]])
            if last_trend[2] == 'pzdown':
                if new_pivot[4] == 'down':
                    last_trend[1] = new_pivot[1]
                    last_trend[4].append(len(self.pivot_list) - 1)
                    last_trend[2] = 'down'
                else:
                    self.trend_list.append([new_pivot[0], new_pivot[1], 'pzup', [], [len(self.pivot_list) - 1]])

    def on_buy_sell(self, data, valid=True):
        """仅记录买卖信号，不执行交易（交易执行逻辑已移至market_open层）

        数据结构扩展:
        - 原有: [日期，值，类型, evaluation_time, 位置索引, valid, invalid_time, 类型, 强弱, qjt_pivot_list, qjt_depth]
        - 新增: [..., stop_loss, take_profit]
        """
        if not data:
            return

        signal_key = f"{data[3]}_{data[2]}_{data[1]}"

        # 买点列表[[日期，值，类型, evaluation_time, 买点位置=index of stroke/line, valid, invalid_time, 类型, 强弱, qjt_pivot_list, qjt_depth, stop_loss, take_profit]]
        # 卖点列表[[日期，值，类型, evaluation_time, 买点位置=index of stroke/line, valid, invalid_time, 类型, 强弱, qjt_pivot_list, qjt_depth, stop_loss, take_profit]]
        if valid and (signal_key not in self.executed_signals):
            # 计算止盈止损
            stop_loss = 0.0
            take_profit = 0.0
            if len(data) < 13:
                last_pivot = self.pivot_list[-1] if self.pivot_list else None
                cur_fx = None
                if len(data) > 4 and data[4] < len(self.stroke_list):
                    cur_fx = self.stroke_list[data[4]]
                bs_name = data[2]
                stop_loss, take_profit = self.calculate_stop_loss_target(bs_name, last_pivot, cur_fx)
                # 扩展数据结构
                if len(data) == 11:
                    data.extend([stop_loss, take_profit])
                elif len(data) == 12:
                    data.append(take_profit)
            else:
                # 已有止盈止损字段
                if len(data) >= 13:
                    stop_loss = data[11]
                    take_profit = data[12]

            # 统一记录所有买卖信号，不区分级别（交易执行逻辑在market_open层处理）
            if data[2].startswith('B'):
                ChanLog.log(self.freq, self.symbol, f'buy signal: {data[2]} SL={stop_loss:.2f} TP={take_profit:.2f}')
                self.buy_list.append(data)
                self.executed_signals.add(signal_key)
            elif data[2].startswith('S'):
                ChanLog.log(self.freq, self.symbol, f'sell signal: {data[2]} SL={stop_loss:.2f} TP={take_profit:.2f}')
                self.sell_list.append(data)
                self.executed_signals.add(signal_key)
