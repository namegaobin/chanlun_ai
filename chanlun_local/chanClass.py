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
        # 启用日志输出，方便调试买卖点生成
        # chan_logger.debug(f"[{freq}][{symbol}] {message}")
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
        if len(data) > 2:
            flag = False
            if data[-2].high_price >= data[-1].high_price and data[-2].high_price >= data[-3].high_price:
                # 形成顶分型 [high_price, low, dt, direction, index of k_list]
                self.fx_list.append([data[-2].high_price, data[-2].low_price, data[-2].datetime, 'up', len(data) - 2])
                flag = True

            if data[-2].low_price <= data[-1].low_price and data[-2].low_price <= data[-3].low_price:
                # 形成底分型
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
                    ZD = max(data[-3][1], data[-5][1])
                    ZG = min(data[-2][0], data[-4][0])
                    DD = min(data[-3][1], data[-5][1])
                    GG = max(data[-2][0], data[-4][0])
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
                    ZD = max(data[-2][1], data[-4][1])
                    ZG = min(data[-3][0], data[-5][0])
                    DD = min(data[-2][1], data[-4][1])
                    GG = max(data[-3][0], data[-5][0])
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
                    # stroke_change导致的笔减少了
                    if len(data) > start + 3:
                        last_pivot[2] = max(data[start + 1][1], data[start + 3][1])
                        last_pivot[3] = min(data[start][0], data[start + 2][0])
                        last_pivot[8] = max(data[start][0], data[start + 2][0])
                        last_pivot[9] = min(data[start + 1][1], data[start + 3][1])
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
                        # 判断背驰
                        if self.on_turn(enter, exit, ee_data, last_pivot[4]) and cur_fx[0] > last_pivot[8]:
                            ts.append([last_fx[2], cur_fx[2]])
                            if not sell[0]:
                                # 形成一卖
                                ans, qjt_pivot_list = self.qjt_turn(last_fx[2], cur_fx[2], 'up')
                                if ans:
                                    sell[0] = [cur_fx[2], cur_fx[0], 'S1', self.k_list[-1].datetime, len(data) - 1, 1,
                                               None, self.cal_bs_type(), None, qjt_pivot_list]
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
                            # 形成三卖
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
                    # stroke_change导致的笔减少了
                    if len(data) > start + 3:
                        last_pivot[2] = max(data[start][1], data[start + 2][1])
                        last_pivot[3] = min(data[start + 1][0], data[start + 3][0])
                        last_pivot[8] = max(data[start + 1][0], data[start + 3][0])
                        last_pivot[9] = min(data[start][1], data[start + 2][1])
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

                        if pen_diverged and cur_fx[1] < last_pivot[9]:
                            ts.append([last_fx[2], cur_fx[2]])
                            if not buy[0]:
                                # 形成一买
                                ans, qjt_pivot_list = self.qjt_turn(last_fx[2], cur_fx[2], 'down')
                                if ans:
                                    buy[0] = [cur_fx[2], cur_fx[1], 'B1', self.k_list[-1].datetime, len(data) - 1, 1,
                                              None, self.cal_bs_type(), self.cal_b1_strength(cur_fx[1], cur_fx, last_pivot), qjt_pivot_list]
                                    if self.gz:
                                        self.gz_prev_last_bs = self.get_prev_last_bs()
                                        self.gz_tmp_bs = buy
                                        buy[0][5] = 0
                                    else:
                                        self.on_buy_sell(buy[0])

                        if buy[0] and buy[0][5] == 1 and not buy[1]:
                            pos_buy1 = buy[0][4]
                            if len(data) > pos_buy1 + 2:
                                pos_fx = data[pos_buy1 + 2]
                                if pos_fx[3] == 'down':
                                    if pos_fx[1] > buy[0][1]:
                                        # 形成二买
                                        ans, qjt_pivot_list = self.qjt_trend(last_fx[2], cur_fx[2], 'down')
                                        if ans:
                                            sth_pivot = last_pivot
                                            # if len(self.pivot_list) > 1:
                                            #     sth_pivot = self.pivot_list[-2]
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

                        if cur_fx[1] > last_pivot[3] and not buy[2] and not sell[0]:
                            # 形成三买
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

    def cal_bs_type(self):
        if len(self.pivot_list) > 1 and self.pivot_list[-1][4] == self.pivot_list[-2][4]:
            return '趋势'
        return '盘整'

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
        # ee_data: 笔/段列表 [[start, end]]
        # 判断背驰
        start_macd = None
        if start in self.macd:
            start_macd = self.macd[start]
        end_macd = None
        if end in self.macd:
            end_macd = self.macd[end]
        if start_macd and end_macd:
            # 兼容字典格式和数值格式
            if isinstance(start_macd, dict):
                start_macd_val = start_macd.get('total', 0)
            else:
                start_macd_val = start_macd
            if isinstance(end_macd, dict):
                end_macd_val = end_macd.get('total', 0)
            else:
                end_macd_val = end_macd
                
            if math.isnan(start_macd_val) or math.isnan(end_macd_val):
                if len(ee_data) > 1:
                    if type == 'down':
                        enter_slope = (ee_data[0][0][0] - ee_data[0][1][1]) / (ee_data[0][1][4] - ee_data[0][0][4] + 1)
                        exit_slope = (ee_data[1][0][0] - ee_data[1][1][1]) / (ee_data[1][1][4] - ee_data[1][0][4] + 1)
                        return abs(enter_slope) > abs(exit_slope)
                    else:
                        enter_slope = (ee_data[0][0][1] - ee_data[0][1][0]) / (ee_data[0][1][4] - ee_data[0][0][4] + 1)
                        exit_slope = (ee_data[1][0][1] - ee_data[1][1][0]) / (ee_data[1][1][4] - ee_data[1][0][4] + 1)
                        return abs(enter_slope) > abs(exit_slope)
            else:
                # 核心修改：添加MACD面积缩小比例阈值判断
                # 背驰条件：离开段面积 / 进入段面积 < 0.4 (缩小至少60%)
                if start_macd_val > 0:
                    ratio = end_macd_val / start_macd_val
                    is_divergence = ratio < self.divergence_ratio_threshold
                    
                    # 添加日志，记录背驰判断详情
                    ChanLog.log(self.freq, self.symbol, 
                               f'背驰判断: 进入段面积={start_macd_val:.2f}, 离开段面积={end_macd_val:.2f}, '
                               f'比例={ratio:.2%}, 阈值={self.divergence_ratio_threshold:.2%}, '
                               f'结果={"背驰" if is_divergence else "非背驰"}')
                    
                    return is_divergence
                return False
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
        # 区间套判断背驰：重新形成新的中枢和买卖点
        qjt_pivot_list = []
        # if not self.qjt:
        #     return True, qjt_pivot_list
        chan = self.next
        if not chan:
            return True, qjt_pivot_list
        ans = True
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
            if chan_pivot_list and len(chan_pivot_list[-1][12]) > 0:
                ts_item = chan_pivot_list[-1][12][-1]
                start = ts_item[0]
                end = ts_item[1]
                tmp = True
                chan = chan.next

            ans = tmp and ans
            if not ans:
                break

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
        """仅记录买卖信号，不执行交易（交易执行逻辑已移至market_open层）"""
        if not data:
            return

        signal_key = f"{data[3]}_{data[2]}_{data[1]}"
        
        ###print(f"key={signal_key}")
        #print(data)
        # 买点列表[[日期，值，类型, evaluation_time, 买点位置=index of stroke/line, valid, invalid_time, 类型, 强弱, qjt_pivot_list]]
        # 卖点列表[[日期，值，类型, evaluation_time, 买点位置=index of stroke/line, valid, invalid_time, 类型, 强弱, qjt_pivot_list]]
        if valid and (signal_key not in self.executed_signals):
            # 统一记录所有买卖信号，不区分级别（交易执行逻辑在market_open层处理）
            if data[2].startswith('B'):
                ChanLog.log(self.freq, self.symbol, 'buy signal recorded:')
                ChanLog.log(self.freq, self.symbol, data)
                self.buy_list.append(data)
                self.executed_signals.add(signal_key)
            elif data[2].startswith('S'):
                ChanLog.log(self.freq, self.symbol, 'sell signal recorded:')
                ChanLog.log(self.freq, self.symbol, data)
                self.sell_list.append(data)
                self.executed_signals.add(signal_key)
