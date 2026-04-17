#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""多级别区间套分析模块

基于缠论多级别分析原理，实现相邻3个级别的K线合并和缠论计算
"""

from typing import List, Dict, Any, Optional
import pandas as pd
from datetime import datetime, timedelta

from chanlun_adapter import convert_to_chanlun_bars
from chanlun_local.engine_new import ICL, SimpleICL


class MultiLevelKlineGenerator:
    """多级别K线生成器
    
    基于 BarGenerator 的思想，实现从低级别K线生成高级别K线
    """
    
    def __init__(self):
        self.interval_map = {
            "1m": "1分钟", "5m": "5分钟", "15m": "15分钟",
            "1h": "1小时", "4h": "4小时", "1d": "1日"
        }
        
        # 级别顺序（从小到大）
        self.level_sequence = ["1m", "5m", "15m", "1h", "4h", "1d"]
        
        # 级别转换比例
        self.conversion_ratios = {
            ("1m", "5m"): 5,
            ("5m", "15m"): 3,
            ("15m", "1h"): 4,
            ("1h", "4h"): 4,
            ("4h", "1d"): 6
        }
    
    def get_adjacent_levels(self, current_interval: str) -> List[str]:
        """获取当前级别及向上2个更高级别（共3个级别）

        当请求 15m 时，返回 [15m, 1h, 4h]
        当请求 1h 时，返回 [1h, 4h, 1d]
        当请求 5m 时，返回 [5m, 15m, 1h]
        以此类推，确保始终有3个级别用于多级别区间套分析。
        如果当前级别接近最大级别，可用级别不足3个时返回所有可用级别。
        """
        if current_interval not in self.level_sequence:
            return [current_interval]

        current_index = self.level_sequence.index(current_interval)

        # 当前级别 + 向上2个更高级别
        levels = [current_interval]

        for offset in range(1, 3):
            higher_index = current_index + offset
            if higher_index < len(self.level_sequence):
                levels.append(self.level_sequence[higher_index])

        return levels
    
    def _merge_group(self, group: List[Dict], target_interval: str) -> Dict:
        """通用K线合并：将一组K线合并为一根"""
        open_price = group[0]["open"]
        high_price = max(k["high"] for k in group)
        low_price = min(k["low"] for k in group)
        close_price = group[-1]["close"]
        volume = sum(k.get("volume", 0) for k in group)
        # 兼容 timestamp 和 open_time 两种字段名
        open_time = group[-1].get("timestamp") or group[-1].get("open_time")
        close_time = group[-1].get("close_time", open_time)

        return {
            "timestamp": open_time,
            "open_time": open_time,
            "close_time": close_time,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
            "interval": target_interval
        }

    def merge_klines_to_higher_level(self, klines: List[Dict], current_interval: str, 
                                   target_interval: str) -> List[Dict]:
        """将当前级别的K线合并到目标更高级别"""
        if current_interval == target_interval:
            return klines
        
        # 检查是否可以转换
        conversion_key = (current_interval, target_interval)
        if conversion_key not in self.conversion_ratios:
            raise ValueError(f"不支持从 {current_interval} 转换到 {target_interval}")
        
        ratio = self.conversion_ratios[conversion_key]
        
        # 按时间分组并合并
        merged_klines = []
        for i in range(0, len(klines), ratio):
            group = klines[i:i+ratio]
            if len(group) < 1:
                continue
            merged_klines.append(self._merge_group(group, target_interval))
        
        return merged_klines
    
    def generate_multi_level_klines(self, base_klines: List[Dict], 
                                   base_interval: str) -> Dict[str, List[Dict]]:
        """生成多级别K线数据

        从 base_interval 开始，递归向上合并生成更高级别K线。
        例如：15m → 1h（4根合一）→ 4h（4根合一），共3个级别。
        """
        levels = self.get_adjacent_levels(base_interval)

        multi_level_klines = {}

        # 当前级别
        multi_level_klines[base_interval] = base_klines

        # 逐级向上生成更高级别K线（链式合并）
        current_interval = base_interval
        current_klines = base_klines

        for target_interval in levels:
            if target_interval == base_interval:
                continue

            # 确保目标级别比当前级别更高，且相邻（中间无跳级）
            target_idx = self.level_sequence.index(target_interval)
            current_idx = self.level_sequence.index(current_interval)

            if target_idx == current_idx + 1:
                try:
                    merged_klines = self.merge_klines_to_higher_level(
                        current_klines, current_interval, target_interval
                    )
                    multi_level_klines[target_interval] = merged_klines
                    current_interval = target_interval
                    current_klines = merged_klines
                    print(f"📊 K线合并: {base_interval} → {target_interval} "
                          f"({len(current_klines)} 根)")
                except ValueError as e:
                    print(f"⚠️ 无法生成 {target_interval} 级别K线: {e}")
                    break  # 中间级别失败则无法继续向上生成

        return multi_level_klines


class MultiLevelChanlunAnalyzer:
    """多级别缠论分析器"""
    
    # 各级别角色配置：基于中枢位置截断
    # role="large": 大级别，全量不截断（定方向）
    # role="medium": 中级别，最近2个中枢覆盖范围（找买卖点）
    # role="small": 小级别，最近1个中枢覆盖范围（精入场）
    LEVEL_ROLE_CONFIG = {
        "large":  {"zs_count": None, "label": "大级别-定方向"},
        "medium": {"zs_count": 2,    "label": "中级别-找买卖点"},
        "small":  {"zs_count": 1,    "label": "小级别-精入场"},
    }
    
    def __init__(self):
        self.kline_generator = MultiLevelKlineGenerator()
        
    def _get_level_role(self, interval: str, analyzed_levels: List[str]) -> str:
        """根据级别在3级结构中的位置确定角色
        
        analyzed_levels 按小到大排序（如 ["15m", "1h", "4h"]），
        第一个是大级别(定方向)，中间是中级别(找买卖点)，最后是小级别(精入场)。
        
        注意：级别从时间维度看，15m 最小但排在 analyzed_levels 的第一个位置，
        因为它是 base_interval。所以：
        - analyzed_levels[0] = base_interval = 小级别
        - analyzed_levels[1] = 中级别
        - analyzed_levels[2] = 大级别（全量）
        """
        if len(analyzed_levels) <= 1:
            return "large"  # 只有一个级别时给全量
        
        if interval == analyzed_levels[-1]:
            return "large"    # 最大级别 → 全量
        elif interval == analyzed_levels[-2]:
            return "medium"   # 中间级别 → 2个中枢
        else:
            return "small"    # 最小级别 → 1个中枢
    
    def _find_item_index_by_time(self, items: List, target_time) -> int:
        """在笔/线段列表中，找到 start_time <= target_time 的最早那条的列表下标
        
        因为中枢开始时间对应的是某笔的结束时间附近，
        所以我们要找的是 start_time 最接近且不超过 target_time 的条目。
        """
        best_idx = 0
        for i, item in enumerate(items):
            item_time = item.get("start_time") if isinstance(item, dict) else getattr(item, "start_time", None)
            if item_time is None:
                continue
            # 统一为字符串比较（ISO格式字符串可直接比较）
            item_time_str = item_time if isinstance(item_time, str) else str(item_time)
            target_time_str = target_time if isinstance(target_time, str) else str(target_time)
            if item_time_str <= target_time_str:
                best_idx = i
            else:
                break  # 已经过了目标时间，不再继续
        return best_idx
    
    def _truncate_by_zs_range(self, items: List, zss: List, zs_count: Optional[int]) -> List:
        """基于中枢位置截断数据
        
        保留最近 N 个中枢覆盖范围内的笔/线段，
        并往前多取3条作为背景参考。
        
        通过中枢的 start_time 在笔/线段列表中定位，而非依赖中枢的 index 序号。
        """
        if zs_count is None or not zss:
            return items  # 不截断
        
        # 取最近 N 个中枢
        recent_zss = zss[-zs_count:] if len(zss) >= zs_count else zss
        
        # 找到这些中枢中最早的 start_time
        earliest_time = None
        for zs in recent_zss:
            zs_time = zs.get("start_time") if isinstance(zs, dict) else getattr(zs, "start_time", None)
            if zs_time is None:
                continue
            if earliest_time is None:
                earliest_time = zs_time
            else:
                zs_time_str = zs_time if isinstance(zs_time, str) else str(zs_time)
                earliest_time_str = earliest_time if isinstance(earliest_time, str) else str(earliest_time)
                if zs_time_str < earliest_time_str:
                    earliest_time = zs_time
        
        if earliest_time is None:
            return items
        
        # 用时间在 items 列表中找到对应的下标
        start_idx = self._find_item_index_by_time(items, earliest_time)
        
        # 往前多取3条作为背景
        start_idx = max(0, start_idx - 3)
        
        return items[start_idx:]
    
    def analyze_multi_level_chanlun(self, symbol: str, base_interval: str, 
                                   base_klines: List[Dict]) -> Dict[str, Any]:
        """执行多级别缠论分析"""
        
        # 1. 生成多级别K线数据
        multi_level_klines = self.kline_generator.generate_multi_level_klines(
            base_klines, base_interval
        )
        
        # 2. 对每个级别进行缠论计算
        multi_level_results = {}
        
        for interval, klines in multi_level_klines.items():
            if len(klines) < 10:
                print(f"警告：{interval} 级别K线数量不足 ({len(klines)})，跳过分析")
                continue
            
            try:
                # 转换为缠论bars
                bars = convert_to_chanlun_bars(klines)
                
                # 创建DataFrame
                df = pd.DataFrame(bars)
                df = df.rename(columns={
                    "date": "date",
                    "o": "open",
                    "h": "high",
                    "l": "low",
                    "c": "close",
                    "a": "volume",
                })
                
                # 频率映射
                frequency_map = {
                    "1m": "1m", "5m": "5m", "15m": "15m",
                    "1h": "60m", "4h": "240m", "1d": "1440m"
                }
                frequency = frequency_map.get(interval, interval)
                
                # 显示符号
                display_symbol = f"{symbol[:3]}/{symbol[3:]}" if len(symbol) > 3 else symbol
                
                # 缠论计算
                icl = ICL(code=display_symbol, frequency=frequency, config=None)
                icl = icl.process_klines(df)
                
                # 获取缠论结构（只需笔和笔中枢，线段不做分析依据）
                bis = icl.get_bis()
                bi_zss = icl.get_bi_zss()
                
                # 全量格式化（用于后续截断）
                all_bis = self._format_bis(bis)
                all_bi_zss = self._format_zss(bi_zss)
                
                multi_level_results[interval] = {
                    "interval": interval,
                    "klines_count": len(klines),
                    "bis_count": len(bis),
                    "bi_zss_count": len(bi_zss),
                    "latest_price": klines[-1]["close"] if klines else 0,
                    "bis": all_bis,
                    "bi_zss": all_bi_zss,
                }
                
                print(f"✅ {interval} 级别分析完成: {len(bis)}笔, {len(bi_zss)}笔中枢")
                
            except Exception as e:
                print(f"❌ {interval} 级别分析失败: {e}")
                multi_level_results[interval] = {
                    "interval": interval,
                    "error": str(e),
                    "klines_count": len(klines)
                }
        
        # 3. 基于中枢位置截断各级别的笔
        analyzed_levels = list(multi_level_results.keys())
        for interval, level_data in multi_level_results.items():
            if "error" in level_data:
                continue
            
            role = self._get_level_role(interval, analyzed_levels)
            config = self.LEVEL_ROLE_CONFIG[role]
            zs_count = config["zs_count"]
            
            bi_zss = level_data.get("bi_zss", [])
            
            # 基于笔中枢截断笔
            if zs_count is not None and bi_zss:
                truncated_bis = self._truncate_by_zs_range(
                    level_data["bis"], bi_zss, zs_count
                )
                trunc_count = len(level_data["bis"]) - len(truncated_bis)
                level_data["bis"] = truncated_bis
                # 截断后同步更新计数，确保与实际数组长度一致
                level_data["bis_count"] = len(truncated_bis)
                if trunc_count > 0:
                    print(f"  🔹 {interval} ({config['label']}): 笔截断 {len(truncated_bis)+trunc_count} → {len(truncated_bis)} (保留最近{zs_count}个笔中枢范围)")
        
        # 4. 构建多级别分析结果
        result = {
            "symbol": symbol,
            "base_interval": base_interval,
            "analyzed_levels": analyzed_levels,
            "levels": multi_level_results,
            "analysis_summary": self._build_analysis_summary(multi_level_results)
        }
        
        return result
    
    def _format_bis(self, bis: List) -> List[Dict]:
        """格式化笔数据"""
        formatted = []
        for bi in bis:
            formatted.append({
                "index": bi.index,
                "type": bi.type,
                "start_price": bi.start_price,
                "end_price": bi.end_price,
                "start_time": bi.start_time,
                "end_time": bi.end_time,
                "strength": bi.strength,
                "is_done": bi.is_done(),
                "mmds": [mmd.name for mmd in bi.mmds],
                "bcs": [bc.type for bc in bi.bcs if bc.bc]
            })
        return formatted
    
    def _format_zss(self, zss: List) -> List[Dict]:
        """格式化中枢数据"""
        formatted = []
        for zs in zss:
            formatted.append({
                "index": zs.index,
                "type": zs.zs_type,
                "direction": zs.direction,
                "zg": zs.zg,
                "zd": zs.zd,
                "gg": zs.gg,
                "dd": zs.dd,
                "start_time": zs.start_time,
                "end_time": zs.end_time,
                "bi_count": zs.bi_count,
                "relation": zs.relation
            })
        return formatted
    
    def _build_analysis_summary(self, multi_level_results: Dict) -> Dict:
        """构建多级别分析摘要"""
        summary = {
            "total_levels": len(multi_level_results),
            "levels_info": {},
            "trend_alignment": "",
            "key_structures": []
        }
        
        for interval, result in multi_level_results.items():
            if "error" in result:
                summary["levels_info"][interval] = {"status": "error", "error": result["error"]}
                continue
            
            summary["levels_info"][interval] = {
                "status": "success",
                "bis_count": result["bis_count"],
                "bi_zss_count": result["bi_zss_count"],
                "latest_price": result["latest_price"]
            }
            
            # 记录关键结构
            if result["bi_zss_count"] > 0:
                latest_zs = result["bi_zss"][-1] if result["bi_zss"] else None
                if latest_zs:
                    summary["key_structures"].append({
                        "level": interval,
                        "type": "bi_zs",
                        "zg": latest_zs["zg"],
                        "zd": latest_zs["zd"],
                        "direction": latest_zs["direction"]
                    })
        
        return summary