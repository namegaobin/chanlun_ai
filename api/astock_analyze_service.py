#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A 股 AI 分析服务 - 复用现有 AI 调用逻辑，数据源切换为 A 股"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from astock import get_klines
from astock_adapter import convert_to_chanlun_bars
from chanlun_icl import ICL
from chanlun_ai_exporter import ChanlunAIExporter
from prompt_builder import build_structured_prompt, build_table_format_prompt
from ai.llm import call_ai
from ai_output_schema import validate_ai_output
from dotenv import load_dotenv

import pandas as pd

# 复用 analyze_service 的 API 配置加载
from api.analyze_service import load_api_config

DEFAULT_KLINE_LIMIT = int(os.getenv("DEFAULT_KLINE_LIMIT", "500"))


def analyze_astock_chanlun(
    symbol: str,
    interval: str,
    limit: int = None,
    test_mode: bool = False,
    mode: str = "structured",
    ai_provider: str = None,
    ai_model: str = None,
    api_key: str = None,
    drill_context: dict = None,
):
    """执行 A 股缠论 AI 分析

    参数与 analyze_service.analyze_chanlun 完全一致，
    唯一区别是数据源从 Binance 切换为 A 股。
    """
    if limit is None:
        limit = DEFAULT_KLINE_LIMIT

    if test_mode:
        return {
            "mock_data": True,
            "analysis": "Test mode - A stock analysis (skipping AI call)",
            "meta": {"symbol": symbol, "interval": interval, "market": "astock"}
        }

    try:
        # 1. 获取 A 股 K 线数据
        klines = get_klines(symbol, interval, limit)
        if not klines or len(klines) < 10:
            return {"error": "Insufficient A-stock data"}

        # 2. 转换为缠论 bars（带真实 volume）
        bars = convert_to_chanlun_bars(klines)

        # 3. 缠论计算
        df = pd.DataFrame(bars)
        df = df.rename(columns={
            "date": "date",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "a": "volume",
        })

        # A 股周期映射
        from astock import PERIOD_FREQUENCY_MAP
        period = {"15m": "15", "60m": "60", "1d": "daily", "1w": "weekly", "1M": "monthly"}.get(interval, "daily")
        frequency = PERIOD_FREQUENCY_MAP.get(period, "1440m")

        # 显示符号
        display_symbol = symbol

        icl = ICL(code=display_symbol, frequency=frequency, config=None)
        icl = icl.process_klines(df)

        # 4. 导出 AI JSON
        exporter = ChanlunAIExporter()
        ai_json = exporter.export(
            icl=icl,
            symbol=display_symbol,
            interval=interval,
            klines=klines,
        )

        latest_price = klines[-1]["close"]

        # 4.5 区间套多级别分析：自动获取并计算父级缠论结构
        if drill_context:
            parent_interval = drill_context.get("parent_interval", "")
            if parent_interval:
                parent_period = {"15m": "15", "60m": "60", "1d": "daily", "1w": "weekly", "1M": "monthly"}.get(parent_interval, "daily")
                parent_freq = PERIOD_FREQUENCY_MAP.get(parent_period, "1440m")
                try:
                    parent_klines = get_klines(symbol, parent_interval, limit)
                    if parent_klines and len(parent_klines) >= 10:
                        parent_bars = convert_to_chanlun_bars(parent_klines)
                        parent_df = pd.DataFrame(parent_bars).rename(columns={
                            "date": "date", "o": "open", "h": "high",
                            "l": "low", "c": "close", "a": "volume",
                        })
                        parent_icl = ICL(code=display_symbol, frequency=parent_freq, config=None)
                        parent_icl = parent_icl.process_klines(parent_df)
                        parent_json = exporter.export(
                            icl=parent_icl,
                            symbol=display_symbol,
                            interval=parent_interval,
                            klines=parent_klines,
                        )
                        ai_json["multi_level"] = {
                            "current_level": {
                                "interval": interval,
                                "role": "child",
                                "focus_segment": {
                                    "type": drill_context.get("segment_type", ""),
                                    "index": drill_context.get("segment_index", ""),
                                },
                            },
                            "parent_level": {
                                "interval": parent_interval,
                                "role": "parent",
                                "data": parent_json,
                            },
                            "drill_chain": drill_context.get("drill_chain", []),
                            "drill_depth": drill_context.get("drill_depth", 1),
                        }
                        print(f"[DEBUG] Multi-level analysis (astock): parent={parent_interval}, child={interval}")
                except Exception as parent_err:
                    print(f"[WARN] Failed to compute parent level chanlun (astock): {parent_err}")

        # 5. 构建 AI Prompt
        if mode == "table":
            prompt = build_table_format_prompt(ai_json)
        else:
            prompt = build_structured_prompt(ai_json)

        # 6. 调用 AI
        api_key, provider, model, temperature, max_tokens = load_api_config(
            provider=ai_provider,
            model=ai_model,
            api_key_override=api_key
        )
        if not api_key:
            return {"error": "AI API key not configured"}

        analysis_result = call_ai(
            prompt=prompt,
            model=model,
            api_key=api_key,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # 7. 处理返回结果
        if mode == "table":
            return {
                "mode": "table",
                "content": analysis_result,
                "meta": {
                    "symbol": symbol,
                    "interval": interval,
                    "price": latest_price,
                    "market": "astock",
                }
            }
        else:
            import json
            import re
            clean_result = analysis_result.strip()

            if clean_result.startswith("```json"):
                clean_result = clean_result[7:]
            if clean_result.startswith("```"):
                clean_result = clean_result[3:]
            if clean_result.endswith("```"):
                clean_result = clean_result[:-3]
            clean_result = clean_result.strip()

            json_match = re.search(r'\{[\s\S]*\}', clean_result)
            if json_match and not clean_result.startswith('{'):
                clean_result = json_match.group(0)

            try:
                structured_output = json.loads(clean_result)
            except json.JSONDecodeError:
                return {"error": "Failed to parse AI response", "raw": clean_result[:500]}

            validated_output = validate_ai_output(structured_output)

            # 状态机转换
            try:
                from state_machine_converter import scenarios_to_state_machine
                state_machine = scenarios_to_state_machine(
                    validated_output,
                    latest_price,
                    historical_winrate=None
                )
                validated_output["state_machine"] = state_machine
                validated_output["output_mode"] = "state_machine"
                validated_output["version"] = "2.0"
            except Exception:
                pass

            if "meta" not in validated_output:
                validated_output["meta"] = {}
            validated_output["meta"]["price"] = latest_price
            validated_output["meta"]["symbol"] = symbol
            validated_output["meta"]["interval"] = interval
            validated_output["meta"]["market"] = "astock"
            validated_output["mode"] = "structured"

            return validated_output

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
