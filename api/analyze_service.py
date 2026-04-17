#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AI 分析服务 - 为 Web API 提供缠论 AI 分析功能"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from binance import get_klines
from chanlun_adapter import convert_to_chanlun_bars
from chanlun_icl import ICL
from chanlun_ai_exporter import ChanlunAIExporter
from prompt_builder import build_structured_prompt, build_table_format_prompt, build_structured_table_prompt
from ai.llm import call_ai
from ai_output_schema import validate_ai_output
from dotenv import load_dotenv

import pandas as pd


def load_api_config(provider: str = None, model: str = None, api_key_override: str = None):
    """
    加载 AI API 配置

    参数:
        provider: AI 服务提供商（从前端传入，优先使用）
        model: AI 模型（从前端传入，优先使用）
        api_key_override: API Key（从前端传入，优先使用，空字符串时忽略）

    返回:
        (api_key, provider, model, temperature, max_tokens)
    """
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # 优先使用传入的参数，否则使用环境变量
    _provider = provider or os.getenv("AI_PROVIDER", "siliconflow")
    _model = model or os.getenv("AI_MODEL", "Pro/deepseek-ai/DeepSeek-V3.2")
    temperature = float(os.getenv("AI_TEMPERATURE", "0.3"))
    max_tokens = int(os.getenv("AI_MAX_TOKENS", "4096"))

    # 获取 API Key（优先使用传入的，但空字符串时使用环境变量）
    if api_key_override and api_key_override.strip():
        api_key = api_key_override
    elif _provider == "siliconflow":
        api_key = os.getenv("SILICONFLOW_API_KEY")
    elif _provider == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
    elif _provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
    elif _provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
    else:
        api_key = None

    return api_key, _provider, _model, temperature, max_tokens


# 从环境变量读取默认K线数量
DEFAULT_KLINE_LIMIT = int(os.getenv("DEFAULT_KLINE_LIMIT", "2500"))


def analyze_chanlun(
    symbol: str,
    interval: str,
    limit: int = None,
    test_mode: bool = False,
    mode: str = "structured",
    ai_provider: str = None,
    ai_model: str = None,
    api_key: str = None,
    drill_context: dict = None,
    enable_multi_level: bool = True,  # 新增：是否启用多级别分析
):
    # 使用环境变量默认值
    if limit is None:
        limit = DEFAULT_KLINE_LIMIT
    """
    执行缠论 AI 分析

    参数:
        symbol: 交易对，如 BTCUSDT
        interval: 周期，如 1h
        limit: K线数量
        test_mode: 测试模式，跳过 AI 调用
        mode: 输出模式，"structured" (JSON) 或 "table" (Markdown)
        ai_provider: AI 服务提供商（从前端传入）
        ai_model: AI 模型（从前端传入）
        api_key: API Key（从前端传入）
        drill_context: 区间套钻取上下文（从前端传入，包含父级缠论结构数据）
        enable_multi_level: 是否启用多级别区间套分析（从前端传入）

    返回:
        dict: AI 分析结果 (structured 或 table 格式)
    """
    # Check for test mode (uses parameter instead of global env var)
    if test_mode:
        return {
            "mock_data": True,
            "analysis": "Test mode - skipping AI call",
            "meta": {"symbol": symbol, "interval": interval}
        }

    try:
        # 1. 获取 K线数据
        klines = get_klines(symbol, interval, limit)
        if not klines or len(klines) < 10:
            return {"error": "Insufficient data"}

        # 2. 转换为缠论 bars
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

        # 周期映射
        frequency_map = {
            "1m": "1m", "5m": "5m", "15m": "15m",
            "1h": "60m", "4h": "240m", "1d": "1440m"
        }
        frequency = frequency_map.get(interval, interval)

        # 显示符号
        display_symbol = f"{symbol[:3]}/{symbol[3:]}" if len(symbol) > 3 else symbol

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

        # 4.5 多级别区间套分析
        if enable_multi_level:
            try:
                from multi_level_analyzer import MultiLevelChanlunAnalyzer
                
                # 创建多级别分析器
                analyzer = MultiLevelChanlunAnalyzer()
                
                # 执行多级别分析
                multi_level_result = analyzer.analyze_multi_level_chanlun(
                    symbol, interval, klines
                )
                
                # 将多级别分析结果添加到AI JSON
                ai_json["multi_level"] = multi_level_result
                
                # 根节点的 bi 与 multi_level 中最小级别(base_interval)重复，去掉避免冗余
                if interval in multi_level_result.get("levels", {}):
                    ai_json["bi"] = []
                
                # 将主分析级别设为中间级别（找买卖点的级别），使AI聚焦该级别进行买卖点研判
                analyzed_levels = multi_level_result.get("analyzed_levels", [])
                if len(analyzed_levels) >= 3:
                    mid_level = analyzed_levels[len(analyzed_levels) // 2]  # 取中间级别，如 ["15m","1h","4h"] → "1h"
                    ai_json["meta"]["interval"] = mid_level
                
                print(f"✅ 多级别区间套分析完成: {len(multi_level_result['analyzed_levels'])} 个级别")
                
            except Exception as multi_err:
                print(f"⚠️ 多级别分析失败，继续单级别分析: {multi_err}")
                # 多级别分析失败不影响主流程
        
        # 4.6 区间套钻取分析（兼容旧版本）
        if drill_context:
            parent_interval = drill_context.get("parent_interval", "")
            if parent_interval:
                parent_freq = frequency_map.get(parent_interval, parent_interval)
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
                        
                        # 如果已经有multi_level，则合并数据
                        if "multi_level" not in ai_json:
                            ai_json["multi_level"] = {}
                        
                        ai_json["multi_level"]["drill_context"] = {
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
                        print(f"[DEBUG] 钻取分析: parent={parent_interval}, child={interval}")
                except Exception as parent_err:
                    print(f"[WARN] Failed to compute parent level chanlun: {parent_err}")

        # 5. 构建 AI Prompt (根据 mode 选择)
        if mode == "table":
            # 表格模式：输出 Markdown 格式
            prompt = build_table_format_prompt(ai_json)
        else:
            # 结构化模式：输出 JSON 格式
            prompt = build_structured_prompt(ai_json)

        # 5.1 完整打印 Prompt 日志
        print("=" * 80)
        print(f"[PROMPT] {symbol} {interval} | mode={mode} | provider={ai_provider or 'env'} model={ai_model or 'env'}")
        print(f"[PROMPT] Prompt 长度: {len(prompt)} 字符")
        print("-" * 80)
        print(prompt)
        print("-" * 80)
        print(f"[PROMPT] END")
        print("=" * 80)

        # 6. 调用 AI
        # 优先使用前端传入的配置，否则使用环境变量
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
        print(f"[DEBUG] AI response length: {len(analysis_result)} chars, max_tokens={max_tokens}")
        print("=" * 80)
        print(f"[AI RESPONSE] {symbol} {interval} | provider={provider} model={model}")
        print("-" * 80)
        print(analysis_result)
        print("-" * 80)
        print(f"[AI RESPONSE] END")
        print("=" * 80)

        # 7. 根据 mode 处理返回结果
        if mode == "table":
            # 表格模式：直接返回 Markdown 文本
            return {
                "mode": "table",
                "content": analysis_result,  # Markdown 格式的分析文本
                "meta": {
                    "symbol": symbol,
                    "interval": interval,
                    "price": latest_price
                }
            }
        else:
            # 结构化模式：解析 JSON
            import json
            import re
            clean_result = analysis_result.strip()
            
            # 尝试从响应中提取 JSON
            # 方法1: 移除 markdown 代码块标记
            if clean_result.startswith("```json"):
                clean_result = clean_result[7:]
            if clean_result.startswith("```"):
                clean_result = clean_result[3:]
            if clean_result.endswith("```"):
                clean_result = clean_result[:-3]
            clean_result = clean_result.strip()
            
            # 方法2: 如果不是纯 JSON，尝试找到 JSON 对象
            json_match = re.search(r'\{[\s\S]*\}', clean_result)
            if json_match and not clean_result.startswith('{'):
                clean_result = json_match.group(0)

            try:
                structured_output = json.loads(clean_result)
            except json.JSONDecodeError:
                return {"error": "Failed to parse AI response", "raw": clean_result[:500]}

            # 验证
            validated_output = validate_ai_output(structured_output)

            # ⭐ v2.0 新增：状态机转换
            try:
                from state_machine_converter import scenarios_to_state_machine
                state_machine = scenarios_to_state_machine(
                    validated_output,
                    latest_price,
                    historical_winrate=None  # API 模式下暂不获取历史胜率
                )
                validated_output["state_machine"] = state_machine
                validated_output["output_mode"] = "state_machine"
                validated_output["version"] = "2.0"
            except Exception as sm_err:
                # 状态机转换失败不影响主流程
                pass

            # 添加多级别分析信息
            if "multi_level" in ai_json:
                validated_output["multi_level"] = ai_json["multi_level"]

            # 添加当前价格信息
            if "meta" not in validated_output:
                validated_output["meta"] = {}
            validated_output["meta"]["price"] = latest_price
            validated_output["meta"]["symbol"] = symbol
            validated_output["meta"]["interval"] = interval
            validated_output["mode"] = "structured"

            return validated_output

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
