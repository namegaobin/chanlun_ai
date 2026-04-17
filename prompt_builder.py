"""Prompt 构造器

本模块的职责：
- 根据 AI JSON 构造完整的 Prompt
- 使用专门针对缠论分析的提示词模板
- 强制 AI 输出结构化 JSON，不是自由文本
- 支持 A2.5 统计提示注入
- 包含缠论术语解释和结构摘要
"""
import json
import os
from datetime import datetime, date
from typing import Dict, Any, Optional
from ai_output_schema import get_schema_template
from stat_hint import get_stat_hint


def _json_serializer(obj):
    """自定义 JSON 序列化器，处理 datetime/Timestamp 等类型"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    return str(obj)


# ============================================
# Token 管理机制（新增）
# ============================================

# Token 配置（从环境变量读取，默认2800）
MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "2800"))
SAFE_TOKENS = MAX_TOKENS - 200  # 保留200 tokens buffer

# 内容优先级配置
CONTENT_PRIORITY = {
    "critical": [  # 必需内容，不可裁剪
        "system_block",      # 系统约束
        "structure_block",   # 缠论结构数据
        "output_block",      # 输出格式约束
    ],
    "important": [  # 重要内容，优先保留
        "summary_block",    # 当前结构摘要
        "stat_block",       # 统计提示
        "drill_block",      # 区间套钻取上下文
        "multi_level_block", # 多级别区间套摘要
    ],
    "optional": [  # 可选内容，可裁剪
        "TERMINOLOGY_BLOCK", # 术语解释（较长）
        "learning_block",   # AI自我认知
        "history_block",    # 历史统计
        "similar_cases_block", # 相似案例
    ]
}


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量（粗略估算：中文≈0.7 token/字，英文≈0.25 token/字）"""
    import re
    # 统计中文字符
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    # 统计非中文字符
    non_chinese = len(text) - chinese_chars
    # 粗略估算
    return int(chinese_chars * 0.7 + non_chinese * 0.25)


def build_prompt_with_token_management(
    blocks: Dict[str, str],
    max_tokens: int = SAFE_TOKENS
) -> str:
    """根据 token 限制构建 Prompt

    参数：
    - blocks: 各个内容块的字典 {block_name: content}
    - max_tokens: 最大 token 数量

    返回：
    - 组装后的 Prompt
    """
    # 按优先级组装
    prompt_parts = []
    current_tokens = 0

    # 1. 添加必需内容
    for block_name in CONTENT_PRIORITY["critical"]:
        if block_name in blocks and blocks[block_name]:
            prompt_parts.append(blocks[block_name])
            current_tokens += estimate_tokens(blocks[block_name])

    # 2. 添加重要内容
    for block_name in CONTENT_PRIORITY["important"]:
        if block_name in blocks and blocks[block_name]:
            tokens = estimate_tokens(blocks[block_name])
            if current_tokens + tokens < max_tokens:
                prompt_parts.append(blocks[block_name])
                current_tokens += tokens

    # 3. 添加可选内容（按需裁剪）
    for block_name in CONTENT_PRIORITY["optional"]:
        if block_name in blocks and blocks[block_name]:
            tokens = estimate_tokens(blocks[block_name])
            if current_tokens + tokens < max_tokens:
                prompt_parts.append(blocks[block_name])
                current_tokens += tokens
            elif current_tokens < max_tokens:
                # 尝试添加裁剪后的版本
                content = blocks[block_name]
                # 裁剪到剩余空间
                remaining_tokens = max_tokens - current_tokens
                ratio = remaining_tokens / tokens
                # 简单裁剪：取前N%的内容
                lines = content.split('\n')
                keep_lines = int(len(lines) * ratio)
                trimmed = '\n'.join(lines[:keep_lines])
                if trimmed:
                    prompt_parts.append(trimmed)
                    current_tokens += estimate_tokens(trimmed)

    return "\n".join(prompt_parts)


def _format_strength_comparison(comparison: str) -> str:
    """格式化力度对比描述"""
    mapping = {
        "weakening": "力度减弱（可能背驰）",
        "strengthening": "力度增强（趋势延续）",
        "similar": "力度相当",
        "unknown": "无法判断",
    }
    return mapping.get(comparison, "未知")


# 缠论术语解释模板（完整版，依据缠中说禅原文）
TERMINOLOGY_BLOCK = """
【缠论核心术语（依据缠中说禅原文）】
笔（Bi）：顶分型与底分型之间连接的最小趋势单位，至少5根K线（顶底分型各1根+中间3根）。每笔有方向(up/down)、力度(strength)、起止价格和时间。
中枢（ZS）：至少3笔重叠的价格区间。三个关键价位：
  - ZG（中枢高点）= 所有笔高点中的最小值（上沿）
  - ZD（中枢低点）= 所有笔低点中的最大值（下沿）
  - GG（最高点）= 所有笔高点中的最大值（波动上界）
  - DD（最低点）= 所有笔低点中的最小值（波动下界）
中枢关系(relation)：new(新生)、extend(延伸/震荡)、up_trend(上涨离开)、down_trend(下跌离开)

【三类买卖点精解（缠论原文108课体系）】
第一类买卖点（1buy/1sell）—— 背驰引发的转折点：
  - 1买出现在下跌趋势的末端：当a+A+b+B+c结构中，c段（最后一个中枢的离开段）发生趋势背驰时的低点。
    也可能是盘整背驰（a+A+b结构中b段力度<a段）后的低点。
  - 1卖是1买的镜像，出现在上涨趋势末端。是最具确定性的转折信号。
  - 数据标识：bis中 mmds=["1buy"] 且 bcs=["bi"]（有背驰标记）

第二类买卖点（2buy/2sell）—— 回调不破前极值的次级点：
  - 2买：1买之后的第一次回调，不跌破1买的低点，然后重新向上。
    特殊情况：盘整背驰形成的次低点也可视为2买区域。
  - 2卖：1卖之后的第一次反弹，不突破1卖的高点，然后重新向下。
  - 关键风险：2买如果后续跌破1买低点，则2买宣告失效。

第三类买卖点（3buy/3sell）—— 中枢突破后的回踩确认点：
  - 3买：价格向上突破中枢ZG后，回踩不进入中枢区间（≥ZG）的低点。
    要求：必须在离开中枢的前提下回踩，且回踩笔不能触及ZD。
  - 3卖：价格向下突破中枢ZD后，回抽不进入中枢区间（≤ZD）的高点。
  - 特征：3类买卖点是"最安全"的入场点（因为趋势已确认离开中枢），但盈亏比通常较小。
  - 数据标识：bis中 mmds=["3buy"] 或 mmds=["3sell"]

【背驰判定（核心区分两种）】
背驰是缠论判断转折的唯一核心技术信号，严格分为两类：

1. 趋势背驰（标准背驰）：a+A+b+B+c 结构中，c段力度 < b段力度
   - 适用场景：两个及以上同级别中枢的趋势走势类型
   - 判定方法：比较最后中枢(B)的离开段(c)与前一个中枢(A)的离开段(b)的 strength
   - c.strength < b.strength → 趋势背驰确立 → 形成1类买卖点
   - 用数据中 bis 的 strength 字段比较相邻同方向笔的力度值

2. 盘整背驰（更常见、更实用）：a+A+b 结构中，b段力度 < a段力度
   - 适用场景：只有一个中枢的盘整走势，或中枢震荡中每一次离开
   - 判定方法：
     a) 从 bi_zss 找到目标中枢，定位 start_time 和 end_time
     b) 进入段(a) = 中枢 start_time 之前最后一笔同方向的笔
        ⚠️ 关键：必须找到中枢开始前【同方向】的笔！
        - 如果中枢是从向上笔开始的 → 进入段是前一笔向上笔
        - 如果中枢是从向下笔开始的 → 进入段是前一笔向下笔
        - 定位方法：在 bis 数组中，找到 start_time 之前、type与中枢内第一笔同方向的最后一笔
     c) 离开段(b) = 中枢 end_time 之后第一笔同方向的笔
        ⚠️ 关键：必须找到中枢结束后【同方向】的笔！
        - 如果中枢是以向上笔结束的 → 离开段是中枢后第一笔向上笔
        - 如果中枢是以向下笔结束的 → 离开段是中枢后第一笔向下笔
     d) 比较 b.strength 与 a.strength：b < a → 盘整背驰
   - 防错指南：
     ❌ 错误示例：中枢8(start=04-16 02:45)的进入段选为笔81(strength=973.5)
        正确：笔81的start_time=04-15 21:30，在中枢开始之前，但它是一笔向上笔(strength=973.5)。
        但真正的进入段应该看中枢内第一笔的方向。中枢8内第一笔(index=82, type=down)，
        所以进入段方向是down → 应找中枢前最后一笔down笔，即笔80(strength=1868.4)。
        中枢8最后一笔(index=93, type=up, strength=2570.4)，所以离开段方向是up →
        应找中枢后第一笔up笔，即笔93本身(strength=2570.4)。
        但注意：如果价格已在中枢上方运行且笔93的end_time等于中枢end_time，
        则笔93可能仍在定义中枢的边界内，需要看下一笔。
     ✅ 正确定位口诀："进入段=中枢前同方向最后一笔，离开段=中枢后同方向第一笔"

【盘整背驰操作要领】
- 中枢震荡中，每次笔离开中枢都必须与进入段比较力度（这是强制要求！）
- 盘整背驰 → 价格大概率回到中枢内，而非突破中枢
- 连续多次离开段 strength 递减 → 中枢震荡力度衰竭，方向选择临近
- 盘整背驰点常形成2类买卖点（如果前面已有1类买卖点）或加强1类买卖点的确认
"""


def enhance_learning_feedback(
    learning_feedback: str,
    current_direction: str = None,
    current_signal: str = None,
) -> str:
    """深度化AI自我认知反馈（Step2改进）

    参数：
    - learning_feedback: 原始自我认知文本
    - current_direction: 当前预测方向（up/down/range），用于针对性警告
    - current_signal: 当前信号类型（1buy/2buy等），用于针对性警告

    返回：
    - 分层次、结构化的自我认知文本
    """
    if not learning_feedback:
        return ""

    # 如果反馈已经是结构化的，直接返回
    if "整体表现" in learning_feedback or "分维度表现" in learning_feedback:
        # 根据当前方向/信号添加特定警告
        if current_direction and current_direction in ["up", "down", "range"]:
            dir_name = {"up": "看涨", "down": "看跌", "range": "震荡"}.get(current_direction, current_direction)
            learning_feedback += f"\n  ⚠️ 本次预测方向：{dir_name}"
        if current_signal:
            learning_feedback += f"\n  ⚠️ 本次信号类型：{current_signal}"
        return learning_feedback

    # 简单增强：添加结构化标题
    lines = []
    lines.append("\n【AI自我认知报告】")
    lines.append("-" * 40)

    # 逐行处理原始反馈
    for line in learning_feedback.split('\n'):
        line = line.strip()
        if not line:
            continue
        lines.append(f"  {line}")

    # 添加当前场景特定警告
    if current_direction and current_direction in ["up", "down", "range"]:
        dir_name = {"up": "看涨", "down": "看跌", "range": "震荡"}.get(current_direction, current_direction)
        lines.append(f"  本次预测方向：{dir_name}")
    if current_signal:
        lines.append(f"  本次信号类型：{current_signal}")

    lines.append("-" * 40)

    return "\n".join(lines)


def build_structured_prompt(
    ai_json: Dict[str, Any],
    stats_context: str = "",
    history_context: str = "",
    learning_feedback: str = "",
) -> str:
    """构造结构化输出 Prompt（强制 JSON 输出，含统计提示 + 历史表现 + 相似案例 + 自我认知）

    参数：
    - ai_json: 符合规范的 AI 输入 JSON
    - stats_context: 历史统计上下文（可选，整体表现）
    - history_context: 相似案例上下文（可选，P0新增）
    - learning_feedback: AI自我认知/学习反馈（可选，Step1新增）

    返回：
    - 强制约束的 Prompt 字符串
    """

    json_str = json.dumps(ai_json, ensure_ascii=False, indent=2, default=_json_serializer)
    schema = get_schema_template()

    meta = ai_json.get("meta", {})
    market = ai_json.get("market", {})
    symbol = meta.get("symbol", "Unknown")
    interval = meta.get("interval", "Unknown")
    latest_price = float(market.get("latest_price", 0.0))

    # 获取结构摘要（新增）
    structure_summary = ai_json.get("structure_summary", {})
    trend_desc = structure_summary.get("trend_description", "未知")
    position_desc = structure_summary.get("position_description", "未知")
    key_levels = structure_summary.get("key_levels", {})
    strength_comparison = structure_summary.get("strength_comparison", "unknown")
    price_position = structure_summary.get("price_position", "unknown")

    # 计算当前结构是否在中枢内
    in_zs = price_position == "inside_zs"

    # === A2.5 统计提示 ===
    stat = get_stat_hint(symbol=symbol, interval=interval, in_zs=in_zs)
    win_rate_str = (
        f"{stat['win_rate']}" if stat.get("win_rate") is not None else "N/A"
    )
    pos_label = "中枢内" if in_zs else "中枢外"

    stat_block = f"""
【统计提示 A2.5｜仅供参考】
交易对：{symbol}，周期：{interval}，结构位置：{pos_label}
样本数量：{stat["sample"]}
历史胜率：{win_rate_str}
结论：{stat["hint"]}
"""

    # === 当前结构摘要（新增）===
    summary_block = f"""
【当前结构摘要】
- 交易对：{symbol}，周期：{interval}
- 当前价格：{latest_price:.2f}
- 趋势判断：{trend_desc}
- 价格位置：{position_desc}
- 力度对比：{_format_strength_comparison(strength_comparison)}
- 中枢区间：ZG={key_levels.get('zg', 0):.0f}, ZD={key_levels.get('zd', 0):.0f}
- 中枢波动：GG={key_levels.get('gg', 0):.0f}, DD={key_levels.get('dd', 0):.0f}
"""

    # === 系统约束（强约束，精简版）===
    system_block = """
【系统约束】
你是【缠论多级别联立分析引擎】，目标：提高操作胜率和盈亏比。
【严禁】使用技术指标、引入外部数据、超出数据推断。

【多级别联立分析纪律】
1. 必须综合 multi_level 中所有级别进行判断，禁止只看单一级别
2. 大级别定方向：最大级别（如4h）的趋势方向是操作主方向，逆大级别方向的策略概率不应超过35%
3. 主分析级别找买卖点：multi_level.levels 中 interval 与主级别（meta.interval）匹配的那个级别，是买卖点研判的核心级别，必须逐笔扫描其 bis 数组中的 mmds/bcs 字段，作为 primary_scenario 的主要依据
4. 其余级别辅助：其他级别的买卖点用于验证主级别信号，不作为独立判断依据；如果与主级别矛盾，以主级别为准
5. 三级别趋势一致时，主策略概率应≥50%；趋势分化时，各策略概率应更均衡

【盈亏比纪律】
1. target_pct 必须大于 stop_pct（盈亏比 > 1.5:1 才值得操作）
2. 如果盈亏比 < 1.5:1，即使方向判断正确也不应给出高概率
3. 止损应设置在关键结构位（ZG/ZD/GG/DD）之外，而非随意百分比

【背驰判定纪律（核心）】
1. 必须明确区分"趋势背驰"和"盘整背驰"，禁止混为一谈
2. 盘整背驰判定方法：
   - 从 bi_zss 中枢列表和 bis 笔列表中，找到中枢的进入段和离开段
   - 进入段 = 中枢 start_time 之前的最后一笔同方向笔
   - 离开段 = 中枢 end_time 之后的第一笔同方向笔
   - 比较两者的 strength 值：离开段 strength < 进入段 strength → 盘整背驰
3. 趋势背驰判定方法：
   - 两个相邻同级别中枢B和A，比较A的离开段与B的离开段的力度
   - 后一个离开段 strength < 前一个离开段 strength → 趋势背驰
4. 盘整背驰的力度衰减模式：如果连续多个离开段 strength 递减，说明中枢震荡力度衰竭
5. 背驰结论必须引用具体的 strength 数值作为依据，禁止笼统说"力度减弱"

【买卖点评估纪律（核心｜依据缠中说禅原文）】

一、三类买卖点的精确定义与可靠性评级

1. **第一类买卖点（1buy/1sell）—— 趋势/盘整背驰点** ⭐⭐⭐ 最高优先级
   - 1买：下跌趋势中，最后一个中枢之后的离开段(c)发生背驰的转折点
     或：盘整走势中，中枢向下离开段盘整背驰后的低点
   - 1卖：上涨趋势中，最后一个中枢之后离开段(c)发生背驰的转折点
   - 特征：mmds字段含"1buy"/"1sell"标记 + bcs字段含背驰类型
   - 可靠性：★★★★★ | 确认条件：背驰后需形成反向分型+完成一笔确认
   - 仓位建议：主仓位50-60%（最高胜率的入场点）
   - 概率加成：对应方向概率 +12%

2. **第二类买卖点（2buy/2sell）—— 不破前低/前高的次低/次高点** ⭐⭐ 中高优先级
   - 2买：1买后的回调不破1买低点，再次转折向上的点（或盘整背驰形成的次低点）
   - 2卖：1卖后的反弹不破1卖高点，再次转折向下的点
   - 特征：回踩/回抽笔力度明显衰减（strength显著小于前一同方向笔）
   - 可靠性：★★★☆☆ | 风险：2买可能创出新低降级为新1买的观察点
   - 仓位建议：加仓至70%或独立建仓30-40%
   - 概率加成：对应方向概率 +8%
   - 失效判定：2买如果价格后续跌破1买低点 → 2买失效，重新寻找新的1买

3. **第三类买卖点（3buy/3sell）—— 中枢突破后回踩不进入中枢** ⭐ 最安全但盈亏比小
   - 3买：向上离开中枢(ZG被突破)后，回踩不跌入中枢内部(≥ZG)的点
   - 3卖：向下离开中枢(ZD被跌破)后，回抽不升入中枢内部(≤ZD)的点
   - 特征：mmds字段含"3buy"/"3sell"标记；必须发生在中枢关系=up_trend/down_trend时
   - 可靠性：★★★★☆（确认性最强，但空间可能已部分走出）
   - 仓位建议：轻仓试探20-30%，或作为加仓信号
   - 概率加成：对应方向概率 +5%
   - 失效判定：
     a) 3买形成后若价格跌回 ZG 以下 → 3买失效，可能回到中枢震荡
     b) 3卖形成后若价格涨回 ZD 以上 → 3卖失效，可能回到中枢震荡

二、区间套买卖点确认流程

步骤1 —— 大级别定位方向：
  - 大级别趋势向上 → 只关注主级别的买点（1buy/2buy/3buy），忽略卖点
  - 大级别趋势向下 → 只关注主级别的卖点（1sell/2sell/3sell），忽略买点
  - 大级别震荡 → 买卖点都参考，但逆大级别方向的概率上限35%

步骤2 —— 主级别（meta.interval）扫描买卖点（核心步骤！）：
  - 在主级别的 bis 数组中逐笔扫描 mmds 字段，找到带买卖点标记的笔
  - 对每个买卖点检查：是否伴随背驰(bcs非空)? 中枢关系是否支持?
  - 对最近的买卖点进行有效性评估：价格是否已突破该买卖点的极值？
  - ⚠️ 主级别的买卖点是 reasoning 的主要依据

步骤3 —— 其余级别验证确认（辅助步骤）：
  - 主级别出现买卖点候选 → 到其余级别找对应证据（背驰/分型）
    ✅ 确认成立：其余级别也出现同方向信号 → 可靠性提升，概率+10%
    ❌ 未确认/矛盾：其余级别信号反向 → 以主级别为准，不改变主判断
  - 其余级别的 mmds/bcs 信号仍需提取到 signals 字段，但不作为独立判断依据

三、中枢震荡操作框架

当价格处于中枢内部（inside_zs）或中枢关系=extend 时：

1. **中枢边界的操作意义**：
   - GG（最高点）：触及GG附近→ 做空机会（目标回归ZG），止损在GG上方
   - ZG（中枢上沿）：多空分界线。价格从下方接近ZG→ 关注是否能突破；从上方回落至ZG→ 支撑位
   - ZD（中枢下沿）：多空分界线。价格从上方回落至ZD→ 关注是否支撑住；从下方反弹至ZD→ 阻力位
   - DD（最低点）：触及DD附近→ 做多机会（目标回归ZD），止损在DD下方

2. **中枢震荡中的力度分析**：
   - 连续多次离开中枢的笔 strength 递减 → 力度衰竭，即将选择方向
   - 最后一次离开力度突然增大(strength > 前几次) → 可能是真突破的前兆
   - 如果最后一次离开段的 strength > 进入段 strength → 可能形成趋势突破

3. **中枢方向选择的判断**：
   - 中枢 relation = up_trend：偏多操作（沿ZD做多为主，GG做空为辅）
   - 中枢 relation = down_trend：偏空操作（沿ZG做空为主，DD做多为辅）
   - 中枢 relation = extend：严格双向操作（高抛低吸，不追涨杀跌）

四、资金管理原则

1. **分批建仓纪律**：
   - 第一类买卖点：可投入计划仓位的50-60%（主仓位）
   - 第二类买卖点：可投入30-40%（加仓位或独立仓）
   - 第三类买卖点：仅投入20-30%（试探仓）
   - 无明确买卖点：禁止开仓，只能观望

2. **加减仓的结构触发条件**：
   - 加仓触发：持仓方向上出现次级别2类/3类买卖点确认
   - 减仓触发：当前笔出现反向背驰(mmds+bcs同时提示反转)
   - 平仓触发：止损位被击穿 OR 方向性买卖点失效

3. **单笔最大亏损控制**：
   - 任何单笔交易亏损不超过总资金的2%
   - 止损必须设置在结构位之外（ZD之下/ZG之上/GG之上/DD之下）
   - 盈亏比 < 1.5:1 时不开新仓

【数据扫描纪律（强制执行）】
在分析开始前，你必须按以下步骤逐一扫描数据，禁止跳过或遗漏：

步骤1 —— 买卖点扫描（逐笔检查 mmds 字段）：
  - 遍历各级别 bis 数组中的每一笔，检查 mmds 字段是否非空
  - 将所有带 mmds 标记的笔记录下来，格式为："笔N(type=up/down, mmds=[...], bcs=[...], strength=X)"
  - 禁止只看最后一两笔！必须扫描数组中的所有笔
  - 特别注意：mmds中可能同时有多个信号（如同时有1buy和1sell的历史标记）
  - 最近的买卖点（数组末尾的）优先级最高

步骤2 —— 背驰扫描（逐笔检查 bcs 字段）：
  - 遍历各级别 bis 数组，检查 bcs 字段是否非空（通常为["bi"]）
  - 所有带 bcs 标记的笔都必须在 reasoning 中被引用和解释
  - bcs 非空的笔说明该笔存在背驰信号，必须判断是趋势背驰还是盘整背驰

步骤3 —— 中枢状态扫描（检查所有 bi_zss 的 relation）：
  - 遍历各级别的 bi_zss 数组，记录每个中枢的 relation 值
  - 如果任一中枢 relation=extend → 必须在分析中提及"存在延伸中枢，震荡概率增加"
  - 如果最后一个中枢非 extend → 按其 relation(up_trend/down_trend/new) 判断方向

步骤4 —— 信号汇总到 signals 字段：
  - signals.buy_sell_points 必须包含数据中所有 bis 的 mmds 并集（去重）
  - signals.divergences 必须包含数据中所有 bis 的 bcs 并集（去重）
  - 如果 bis 中存在 mmds=["1buy"] 或 mmds=["1sell"] → buy_sell_points 必须包含 "1buy" 或 "1sell"
  - 如果 bis 中存在 bcs=["bi"] → divergences 必须包含 "bi"
  - 禁止输出空的 buy_sell_points 或 divergences（除非数据中确实没有）

【数据截断说明】
- 为控制数据量，各级别的笔(bis)数组已按中枢覆盖范围截断，只保留最近N个中枢覆盖范围的笔
- 截断后 bis_count 反映数组实际长度，但每笔的 index 字段保留原始编号（可能不连续，如从80开始）
- 中级别和小级别会被截断，大级别保留全量笔
- 分析时请以数组实际内容和顺序为准，不要依赖 index 编号的连续性来推断缺失笔
"""

    # === 历史表现上下文（可选）===
    history_block = ""
    if stats_context:
        history_block = stats_context + "\n"

    # === 相似案例上下文（P0新增）===
    similar_cases_block = ""
    if history_context:
        similar_cases_block = history_context + "\n"

    # === 区间套钻取上下文（区间套分析时注入父级缠论结构）===
    drill_block = ""
    drill_context = ai_json.get("drill_context")
    if drill_context:
        parent_interval = drill_context.get("parent_interval", "未知")
        segment_type = drill_context.get("segment_type", "未知")
        segment_index = drill_context.get("segment_index", "未知")
        segment_type_label = "笔" if segment_type == "bi" else "线段"
        drill_depth = drill_context.get("drill_depth", 1)
        drill_chain = drill_context.get("drill_chain", [])

        chain_desc = ""
        if drill_chain and len(drill_chain) > 1:
            chain_labels = [f"{c.get('interval', '')} {c.get('label', '')}" for c in drill_chain]
            chain_desc = f"\n完整钻取路径：{' > '.join(chain_labels)} > {interval}"

        parent_bi = drill_context.get("parent_bi", [])
        parent_xd = drill_context.get("parent_xd", [])
        parent_zs = drill_context.get("parent_zs", [])

        drill_block = f"""
【区间套多级别分析上下文】
用户点击了 {parent_interval} 级别的{segment_type_label}{segment_index} 进行区间套钻取分析。
当前正在分析的是该{segment_type_label}内部的 {interval} 级别缠论结构。
这是第 {drill_depth} 级钻取。{chain_desc}

分析要求：
1. 结合父级别({parent_interval})的{segment_type_label}{segment_index}方向和力度，判断当前级别走势
2. 如果父级别{segment_type_label}向上且力度增强，当前级别做多概率应提高
3. 如果父级别{segment_type_label}出现背驰，注意反转风险
4. 区间套的核心是"大级别定方向，小级别找买卖点"
"""

        if parent_bi:
            drill_block += f"\n父级别({parent_interval})最近的笔：\n"
            for bi in parent_bi[-10:]:
                direction = "↑" if bi.get("type") == "up" else "↓"
                bp = bi.get("buy_sell_point") or ""
                bc = bi.get("divergence") or ""
                extra = ""
                if bp: extra += f" [{bp}]"
                if bc: extra += f" [背驰:{bc}]"
                drill_block += f"  笔{bi.get('index', '?')}: {direction} {bi.get('start_price', 0):.2f} → {bi.get('end_price', 0):.2f}{extra}\n"

        if parent_xd:
            drill_block += f"\n父级别({parent_interval})最近的线段：\n"
            for xd in parent_xd[-5:]:
                direction = "↗" if xd.get("type") == "up" else "↘"
                drill_block += f"  线段{xd.get('index', '?')}: {direction} {xd.get('start_price', 0):.2f} → {xd.get('end_price', 0):.2f}\n"

        if parent_zs:
            drill_block += f"\n父级别({parent_interval})中枢：\n"
            for i, zs in enumerate(parent_zs[-3:]):
                drill_block += f"  中枢{i+1}: ZG={zs.get('zg', 0):.2f} ZD={zs.get('zd', 0):.2f} GG={zs.get('gg', 0):.2f} DD={zs.get('dd', 0):.2f}\n"

        drill_block += "\n"

    # === 多级别区间套分析摘要（v3.0新增）===
    multi_level_block = ""
    multi_level = ai_json.get("multi_level")
    if multi_level and isinstance(multi_level, dict):
        ml_levels = multi_level.get("analyzed_levels", [])
        ml_levels_data = multi_level.get("levels", {})
        ml_summary = multi_level.get("analysis_summary", {})
        
        if ml_levels and len(ml_levels) > 1:
            multi_level_block = "\n【多级别区间套分析摘要】\n"
            multi_level_block += f"已分析级别：{' → '.join(ml_levels)}\n"
            
            for lvl in ml_levels:
                ld = ml_levels_data.get(lvl, {})
                if ld.get("error"):
                    multi_level_block += f"  {lvl}: 分析失败\n"
                    continue
                bi_cnt = ld.get("bis_count", 0)
                zs_cnt = ld.get("bi_zss_count", 0)
                price = ld.get("latest_price", 0)
                
                # bis_count 已是截断后的实际数量（由 multi_level_analyzer 保证）
                actual_bis = ld.get("bis", [])
                
                # 获取最近笔方向
                last_bi_dir = ""
                if actual_bis:
                    last_bi = actual_bis[-1]
                    last_bi_dir = "↑" if last_bi.get("type") == "up" else "↓"
                
                # 获取最近中枢
                zs_desc = ""
                bi_zss = ld.get("bi_zss", [])
                if bi_zss:
                    last_zs = bi_zss[-1]
                    zs_desc = f"ZG={last_zs.get('zg', 0):.2f} ZD={last_zs.get('zd', 0):.2f} ({last_zs.get('direction', '')})"
                
                multi_level_block += f"  {lvl}: {bi_cnt}笔 {zs_cnt}中枢 | 价格={price:.2f} 最近笔={last_bi_dir}"
                if zs_desc:
                    multi_level_block += f" | 中枢: {zs_desc}"
                multi_level_block += "\n"
            
            # 趋势一致性
            key_structures = ml_summary.get("key_structures", [])
            if key_structures:
                dirs = [ks.get("direction", "") for ks in key_structures]
                unique_dirs = list(set(d for d in dirs if d))
                if len(unique_dirs) == 1:
                    if unique_dirs[0] == "up":
                        multi_level_block += "趋势一致性：各级别方向一致看涨，信号可靠性高\n"
                    elif unique_dirs[0] == "down":
                        multi_level_block += "趋势一致性：各级别方向一致看跌，信号可靠性高\n"
                    else:
                        multi_level_block += "趋势一致性：各级别均为震荡\n"
                elif len(unique_dirs) > 1:
                    multi_level_block += "趋势一致性：各级别趋势分化，需谨慎\n"
            
            multi_level_block += "区间套核心原则：大级别定方向，小级别找买卖点\n"
            multi_level_block += "\n"

    # === AI自我认知（Step2改进：深度化）===
    learning_block = ""
    if learning_feedback:
        learning_block = enhance_learning_feedback(learning_feedback) + "\n"

    # === 缠论结构 JSON ===
    structure_block = f"""
【缠论结构 JSON】
{json_str}
"""

    # === 结构优先级说明（v2.1→v4.0增强版）===
    structure_priority_block = """
【缠论分析核心原则：结构优先｜v4.0增强】
在进行概率分配时，请严格遵循以下优先级：

1. **中枢关系 > 笔力度 > 买卖点信号**
   - extend 状态：优先判定为震荡（震荡概率应最高，通常≥40%）
   - up_trend/down_trend 状态：优先判定为趋势方向（对应方向概率应最高）
   - new 状态：谨慎判断，分布应更均衡（避免某一方向概率>50%）
   - ⚠️ 必须检查各级别的所有中枢，不能只看最后一个中枢！
     * 如果1h级别存在extend中枢，即使最新中枢是up_trend，也需考虑extend的影响
     * extend中枢的存在意味着该级别曾有长时间的震荡，趋势可能不稳定

2. **价格位置作为辅助判断**
   - 价格在中枢内部（inside_zs）：震荡概率增加
   - 价格在中枢上方（above_zs）：偏多头，但需警惕回落至ZG附近
   - 价格在中枢下方（below_zs）：偏空头，但需警惕反弹至ZD附近

3. **买卖点信号权重（含可靠性和失效判定）**
   - 主级别（meta.interval）的1类买卖点(带背驰确认): 对应方向 +12%
   - 主级别的2类买卖点: 对应方向 +8%
   - 主级别的3类买卖点: 对应方向 +5%
   - 其余级别的买卖点: 对应方向 +3%（仅辅助确认）
   - ⚠️ 买卖点失效时的处理：
     * 3买后价格<ZG → 3买失效，回到中枢震荡判断
     * 2买后创新低 → 2买失效
     * 失效的买卖点不应再作为加成依据
   - 注意：买卖点是入场时机信号，不应改变基于结构的主方向判断

4. **区间套共振加成**
   - 如果大级别趋势方向与中级别买卖点同向 → 额外+5%
   - 如果小级别也确认了背驰/分型（三级别共振）→ 再+5~10%
   - 如果大小级别矛盾（如大级别向下但小级别出现1buy）→ 以大级别为准，小级别信号降权50%

5. **背驰信号预警（结合中枢状态）**
   - 趋势背驰 + 中枢up_trend/down_trend → 高概率反转信号
   - 盘整背驰 + 中枢extend → 仅预示回归中枢，不改变震荡主判断
   - 力度递减模式（连续多次离开段strength↓）→ 中枢即将方向选择的前兆
   - 禁止仅凭背驰改变主方向，必须结合中枢关系综合判断

6. **错误示例避免**：
   - ❌ 中枢 extend + 价格 below_zs + 向下笔力度增强 → 给做空最高概率
     ✅ 正确：extend 状态优先震荡，震荡概率应最高
   - ❌ 只看非主级别买卖点而忽略主级别（meta.interval）的买卖点
     ✅ 正确：以主级别的mmds/bcs为核心判断依据，其余级别仅辅助
   - ❌ 发现1sell信号就给做空最高概率（忽略大级别向上趋势）
     ✅ 正确：逆大级别的卖点概率上限35%，必须说明矛盾风险
   - ❌ 3buy后价格已跌破ZG仍按有效3buy给出高做多概率
     ✅ 正确：3buy已失效，应按中枢震荡重新评估
   - ❌ signals字段遗漏各级别bis中的mmds/bcs信号
     ✅ 正确：signals必须包含各级别所有bis中mmds/bcs的并集
"""

    # === 输出格式约束（含 JSON Schema，增强版）===
    output_block = f"""
【输出格式】
⚠️ 重要：只输出纯 JSON 对象，不要任何解释、推理过程或 markdown 代码块标记！

1. 必须输出符合 Schema 的合法 JSON
2. scenarios 概率总和不超过 1.05
3. primary_scenario.direction 必须是 "up" 或 "down"，且 probability 应为最高
4. target_range 价格逻辑（⚠️ 这是当前价格的 {latest_price:.2f}）：
   - 做多(up): target_range[0] > 当前价格（目标区间应在价格上方）
   - 做空(down): target_range[1] < 当前价格（目标区间应在价格下方）
   - 震荡(range): target_range[0] < 当前价格 < target_range[1]（区间包含当前价格）
5. entry_range 入场逻辑：
   - 做多: entry_range 应在当前价格附近或略下方（等待回调入场）
   - 做空: entry_range 应在当前价格附近或略上方（等待反弹入场）
   - 震荡: entry_range 应在震荡区间内
6. 止损与盈亏比（核心风控）：
   - stop_pct（止损幅度）和 target_pct（目标幅度）都为正数
   - 盈亏比 = target_pct / stop_pct，必须 ≥ 1.5
   - 止损位应设置在缠论关键结构位：ZG/ZD/GG/DD 之外
   - 做多止损通常在 ZD 或 DD 下方，做空止损通常在 ZG 或 GG 上方
   - 如果盈亏比 < 1.5:1，对应策略 probability 不应超过 30%
7. primary_scenario.reasoning 必须包含多级别联立逻辑：
   - 必须提及大级别趋势方向及其对主分析级别的操作约束（顺/逆方向）
   - 必须在主级别（meta.interval对应的级别）的bis数组中扫描mmds/bcs，列出买卖点和背驰信号
   - 必须解释主级别的中枢状态（遍历所有bi_zss的relation，注意extend中枢的影响）
   - 必须说明其余级别笔结构对主级别买卖点的支持或阻碍
   - 必须明确进行盘整背驰判断：引用具体 strength 数值，比较进入段与离开段力度
   - 【买卖点确认/失效判断】（必填）：
     a) 列出主级别已识别的买卖点（从mmds字段提取）
     b) 对每个买卖点评估：是否有效？（检查失效条件：价格是否已突破极值？）
     c) 其余级别是否支持该买卖点？
     d) 如果主级别存在有效1类买卖点，它应成为 primary_scenario 的主要依据
     e) 如果主级别无有效买卖点，应在reasoning中明确说明"主级别无有效买卖点"
   - 【中枢震荡策略】（当价格在中枢内或extend状态时必填）：
     a) 当前价格在中枢中的相对位置（接近GG/ZG/ZD/DD哪个边界？）
     b) 沿哪个边界操作？（如：接近GG做空/接近DD做多）
     c) 最近离开中枢的笔力度是增强还是衰减？对方向选择的预示
8. scenarios 中每个场景的 logic 必须使用缠论术语，并明确背驰类型：
   - 如果依赖背驰判断，必须指明是"趋势背驰"还是"盘整背驰"
   - 盘整背驰逻辑格式："[某级别]中枢[N]进入段strength=X，离开段strength=Y，Y<X→盘整背驰"
   - 趋势背驰逻辑格式："[某级别]中枢[A]离开段strength=X，中枢[B]离开段strength=Y，Y<X→趋势背驰"
9. signals 字段必须从数据中提取（禁止自行推断或留空）：
   a) buy_sell_points = 所有级别 bis 中 mmds 字段的值的并集（去重）
      - 必须遍历各级别bis数组，收集所有非空mmds中的元素
      - 如15m的笔92有mmds=["1buy"] → buy_sell_points必须包含"1buy"
      - 如1h的笔20有mmds=["1buy"] → 同样加入
   b) divergences = 所有级别 bis 中 bcs 字段的值的并集（去重）
      - 如15m的笔89有bcs=["bi"] → divergences必须包含"bi"
   c) 禁止输出空的buy_sell_points或divergences，除非所有bis的mmds和bcs确实都为空数组
   d) 在reasoning中必须对每个提取到的买卖点进行有效性评估（见第7条）
10. analysis 字段必须包含（格式化给交易者看）：
   a) 当前结构判断（多级别联立：各级别趋势、中枢状态、笔力度）
   b) 背驰分析（逐级别检查盘整背驰和趋势背驰，引用strength数值）
   c) 关键价位 ZG/ZD/GG/DD 及其意义
   d) 【做多策略】（概率 XX%）：入场点位、目标、止损位、盈亏比、触发条件
   e) 【做空策略】（概率 XX%）：入场点位、目标、止损位、盈亏比、触发条件
   f) 【震荡策略】（概率 XX%）：价格区间、操作方式
   注：三种策略概率总和≈100%，与scenarios数组一致

【JSON Schema】
```json
{schema}
```
"""

    # === 使用 Token 管理（新增）===
    blocks = {
        "system_block": system_block,
        "structure_block": structure_block,
        "structure_priority_block": structure_priority_block,
        "output_block": output_block,
        "summary_block": summary_block,
        "stat_block": stat_block,
        "multi_level_block": multi_level_block,
        "TERMINOLOGY_BLOCK": TERMINOLOGY_BLOCK,
        "learning_block": learning_block,
        "history_block": history_block,
        "similar_cases_block": similar_cases_block,
        "drill_block": drill_block,
    }

    # 使用 Token 管理机制组装 Prompt
    return build_prompt_with_token_management(blocks, max_tokens=SAFE_TOKENS)


def build_prompt(
    ai_json: Dict[str, Any],
    stats_context: str = "",
    history_context: str = "",
    learning_feedback: str = "",
) -> str:
    """构造 AI 分析 Prompt（增强版，支持历史上下文注入）
    
    参数：
    - ai_json: 符合规范的 AI 输入 JSON
    - stats_context: 历史统计上下文（可选）
    - history_context: 相似案例上下文（可选）
    - learning_feedback: AI自我认知/学习反馈（可选）
    
    返回：
    - 完整的 Prompt 字符串
    """
    
    json_str = json.dumps(ai_json, ensure_ascii=False, indent=2, default=_json_serializer)
    
    # 构建历史上下文块
    context_blocks = []
    
    if learning_feedback:
        context_blocks.append(f"""【AI历史表现自我认知】
{learning_feedback}
请根据上述历史表现，在分析时保持适度谨慎，尤其注意你的弱项领域。
""")
    
    if history_context:
        context_blocks.append(f"""【相似案例历史参考】
{history_context}
请参考上述相似案例的历史表现，合理评估预测的可靠性。
""")
    
    if stats_context:
        context_blocks.append(f"""【历史统计提示】
{stats_context}
""")
    
    context_section = "\n".join(context_blocks) if context_blocks else ""
    
    return f"""你是一名精通缠论的数字货币交易分析师。

{context_section}
请根据以下【结构化缠论数据】，对后续走势进行判断。

【输出要求】
1. **当前市场结构判断**（1-2 段话，说明当前笔/线段/中枢状态）
2. **未来 2~3 种可能走势**（按概率排序，标注概率百分比）
3. **关键价格区间**（支撑位、阻力位、中枢区间）
4. **操作思路**（仅基于缠论结构逻辑，不做投资建议）

【严格规则】
- ❌ 禁止使用：均线、MACD、KDJ、RSI 等技术指标
- ❌ 禁止使用：消息面、情绪、舆论等非缠论因素
- ✅ 只能使用：笔、线段、中枢、买卖点、背驰、级别
- ✅ 输出格式：简洁、清晰、可直接给交易者看的分析文字
- ✅ 语言：中文
- ✅ 如有历史表现数据，请在分析中体现谨慎程度

【缠论结构数据】
```json
{json_str}
```

请开始你的分析："""


def build_simple_prompt(ai_json: Dict[str, Any]) -> str:
    """构造简化版 Prompt（用于快速分析）
    
    参数：
    - ai_json: 符合规范的 AI 输入 JSON
    
    返回：
    - 简化的 Prompt 字符串（要求输出更简洁）
    """
    
    # 提取关键信息
    meta = ai_json.get("meta", {})
    market = ai_json.get("market", {})
    signal = ai_json.get("signal", {})
    centers = ai_json.get("center", [])
    
    # 构造简化的上下文
    context = f"""交易对: {meta.get('symbol', 'Unknown')}
周期: {meta.get('interval', 'Unknown')}
当前价格: {market.get('latest_price', 0)}
笔数量: {meta.get('data_size', {}).get('bi', 0)}
线段数量: {meta.get('data_size', {}).get('segment', 0)}
中枢数量: {len(centers)}
买卖点: {', '.join(signal.get('buy_sell_points', [])) or '无'}
背驰: {', '.join(signal.get('divergences', [])) or '无'}
"""
    
    json_str = json.dumps(ai_json, ensure_ascii=False, indent=2, default=_json_serializer)
    
    return f"""作为缠论专家，基于以下数据做出简洁判断：

{context}

【要求】
- 用 3-5 句话总结当前结构状态
- 给出 2-3 种可能走势及概率
- 标注关键价格位
- 仅用缠论语言，不用指标

【完整数据】
```json
{json_str}
```

请简洁分析："""


def build_table_format_prompt(
    ai_json: Dict[str, Any],
    stats_context: str = "",
    history_context: str = "",
    learning_feedback: str = "",
) -> str:
    """构造表格格式的缠论分析 Prompt（增强版，支持历史上下文）
    
    这个 Prompt 专门用于处理包含表格数据的输入，
    要求 AI 输出结构化的 Markdown 分析报告。
    
    参数：
    - ai_json: 符合规范的 AI 输入 JSON
    - stats_context: 历史统计上下文（可选）
    - history_context: 相似案例上下文（可选）
    - learning_feedback: AI自我认知/学习反馈（可选）
    
    返回：
    - Markdown 格式的 Prompt
    """
    
    meta = ai_json.get("meta", {})
    market = ai_json.get("market", {})
    bi_list = ai_json.get("bi", [])
    segment_list = ai_json.get("segment", [])
    centers = ai_json.get("center", [])
    signals = ai_json.get("signal", {})
    
    # 构造表格数据
    bi_table = "起始时间\t结束时间\t方向\t起始值\t完成状态\t买点\t背驰\n"
    for bi in bi_list[-9:]:  # 只取最后9条
        start_time = bi.get('start_time', '').split('T')[0] + ' ' + bi.get('start_time', '').split('T')[1][:8] if 'T' in bi.get('start_time', '') else bi.get('start_time', '')
        end_time = bi.get('end_time', '').split('T')[0] + ' ' + bi.get('end_time', '').split('T')[1][:8] if 'T' in bi.get('end_time', '') else bi.get('end_time', '')
        direction = "向上" if bi.get('direction') == 'up' else "向下"
        price_range = f"{bi.get('start_price', 0):.2f} - {bi.get('end_price', 0):.2f}"
        is_done = "True" if bi.get('is_done') else "False"
        buy_sell = bi.get('buy_sell_point', '') or ''
        divergence = bi.get('divergence', '') or ''
        
        bi_table += f"{start_time}\t{end_time}\t{direction}\t{price_range}\t{is_done}\t{buy_sell}\t{divergence}\n"
    
    segment_table = "起始时间\t结束时间\t方向\t起始值\t完成状态\t买点\t背驰\n"
    for seg in segment_list[-3:]:  # 只取最后3条
        start_time = seg.get('start_time', '').split('T')[0] + ' ' + seg.get('start_time', '').split('T')[1][:8] if 'T' in seg.get('start_time', '') else seg.get('start_time', '')
        end_time = seg.get('end_time', '').split('T')[0] + ' ' + seg.get('end_time', '').split('T')[1][:8] if 'T' in seg.get('end_time', '') else seg.get('end_time', '')
        direction = "向上" if seg.get('direction') == 'up' else "向下"
        price_range = f"{seg.get('start_price', 0):.2f} - {seg.get('end_price', 0):.2f}"
        is_done = "True" if seg.get('is_done') else "False"
        buy_sell = seg.get('buy_sell_point', '') or ''
        divergence = seg.get('divergence', '') or ''
        
        segment_table += f"{start_time}\t{end_time}\t{direction}\t{price_range}\t{is_done}\t{buy_sell}\t{divergence}\n"
    
    # 中枢表格
    center_table = "起始时间\t结束时间\t类型\t最高值\t最低值\t级别\t关系\n"
    for zs in centers[-2:]:  # 只取最后2个
        start_time = zs.get('start_time', '').split('T')[0] + ' ' + zs.get('start_time', '').split('T')[1][:8] if 'T' in zs.get('start_time', '') else zs.get('start_time', '')
        end_time = zs.get('end_time', '').split('T')[0] + ' ' + zs.get('end_time', '').split('T')[1][:8] if 'T' in zs.get('end_time', '') else zs.get('end_time', '')
        zs_type = "笔中枢" if zs.get('type') == 'bi' else "线段中枢"
        high = f"{zs.get('high', 0):.2f}"
        low = f"{zs.get('low', 0):.2f}"
        level = zs.get('level', 1)
        relation = zs.get('relation', 'unknown')
        
        center_table += f"{start_time}\t{end_time}\t{zs_type}\t{high}\t{low}\t{level}\t{relation}\n"
    
    # 构建历史上下文块
    context_blocks = []
    
    if learning_feedback:
        context_blocks.append(f"""## AI历史表现自我认知

{learning_feedback}

> 请根据上述历史表现，在分析时保持适度谨慎，尤其注意弱项领域。
""")
    
    if history_context:
        context_blocks.append(f"""## 相似案例历史参考

{history_context}

> 请参考上述相似案例的历史表现，合理评估预测的可靠性。
""")
    
    if stats_context:
        context_blocks.append(f"""## 历史统计提示

{stats_context}
""")
    
    context_section = "\n---\n\n".join(context_blocks) if context_blocks else ""
    if context_section:
        context_section = "\n---\n\n" + context_section
    
    return f"""# 缠论技术分析：{meta.get('symbol', 'Unknown')} 走势分析

请根据以下缠论数据，分析后续可能走势，并按照**标准格式**输出。
{context_section}
---

## 输入数据

### 当前品种
- **代码/名称**：{meta.get('symbol', 'Unknown')}
- **数据周期**：{meta.get('interval', 'Unknown')}
- **当前时间**：{meta.get('timestamp', '')}
- **最新价格**：{market.get('latest_price', 0):.2f}

### 最新的 9 条缠论笔数据
{bi_table}

### 最新的 3 条缠论线段数据
{segment_table}

### 中枢信息
**最新两个中枢的位置关系**：{centers[-1].get('relation', 'unknown') if centers else '无'}

{center_table}

**数据说明**：中枢级别的意思，1表示是本级别，根据中枢内的线段数量计算，小于等于9表示本级别，大于1表示中枢内的线段大于9，中枢级别升级。

---

## 输出要求

请严格按照以下格式输出 Markdown 分析报告：

### 一、技术形态概述
根据提供的缠论数据，对 {meta.get('symbol', 'Unknown')} {meta.get('interval', 'Unknown')} 周期的走势进行分析如下：

### 二、当前市场状态
- 最新价格：[具体价格]
- 处于什么级别的中枢内/外
- 中枢范围变化情况
- 最后一笔的状态（向上/向下，是否完成）

### 三、关键技术信号
- 买卖点信号：{', '.join(signals.get('buy_sell_points', [])) or '无'}
- 背驰信号：{', '.join(signals.get('divergences', [])) or '无'}
- 中枢关系：[中枢的扩展/收缩/移动情况]

### 四、可能走势分析（概率排序）

#### 走势一：[走势描述]（概率：X%）
**技术依据**：
- [依据1]
- [依据2]
- [依据3]

**预期走势**：
- [短期预期]
- [目标位置]
- [关键价格位]

#### 走势二：[走势描述]（概率：Y%）
**技术依据**：
- [依据1]
- [依据2]

**预期走势**：
- [短期预期]
- [目标位置]
- [触发条件]

#### 走势三：[走势描述]（概率：Z%）
**技术依据**：
- [依据1]
- [依据2]

**预期走势**：
- [横盘/震荡预期]
- [价格区间]

### 五、操作建议

**多头策略**：
- 入场点位区间：[价格低点 - 价格高点]
- 止损位：[具体价格]
- 目标位：[价格区间]

**空头策略**：
- 入场点位区间：[价格低点 - 价格高点]
- 止损位：[具体价格]
- 目标位：[价格区间]

**震荡策略**：
- 上沿做空：[具体价格]
- 下沿做多：[具体价格]
- 止损止盈设置：[建议]

### 六、风险提示
- [风险因素1]
- [风险因素2]
- [风险因素3]
- 请结合其他分析工具和市场消息综合判断，不建议单纯依据本分析进行交易决策。

---

**严格约束**：
- ❌ 禁止使用技术指标（均线、MACD、RSI、KDJ等）
- ❌ 禁止引入外部消息、舆论、情绪分析
- ❌ 禁止超出提供数据进行推断
- ✅ 只能基于提供的缠论结构数据（笔、线段、中枢、买卖点、背驰）
- ✅ 使用缠论专业术语和逻辑
- ✅ 输出格式必须完全符合上述结构
- ✅ 概率总和应为 100%

请严格按照上述格式输出分析报告：
"""


def build_structured_table_prompt(ai_json: Dict[str, Any]) -> str:
    """构造表格格式 + 结构化 JSON 输出的 Prompt
    
    这个 Prompt 要求 AI 根据表格数据输出结构化 JSON
    
    参数：
    - ai_json: 符合规范的 AI 输入 JSON
    
    返回：
    - 强制 JSON 输出的 Prompt
    """
    
    # 重用表格格式构建逻辑
    table_content = build_table_format_prompt(ai_json)
    schema = get_schema_template()
    
    return f"""{table_content}

---

## 输出要求

你是一个【缠论结构分析引擎】，不是聊天机器人。

**严格按照以下 JSON Schema 输出，不允许有任何额外文字：**

```json
{schema}
```

请直接输出符合 Schema 的 JSON，不要有任何其他内容：
"""


def build_multi_level_prompt(multi_level_data: Dict[str, Any]) -> str:
    """构造多级别联立分析 Prompt
    
    参数：
    - multi_level_data: 多级别分析数据，包含 large/medium/small 三个级别
    
    返回：
    - 多级别分析的结构化 Prompt
    """
    
    schema = get_schema_template()
    symbol = multi_level_data.get("symbol", "Unknown")
    latest_price = multi_level_data.get("latest_price", 0)
    levels = multi_level_data.get("levels", {})
    
    # 提取各级别摘要
    large = levels.get("large", {})
    medium = levels.get("medium", {})
    small = levels.get("small", {})
    
    large_summary = large.get("summary", {})
    medium_summary = medium.get("summary", {})
    small_summary = small.get("summary", {})
    
    # 构造级别摘要表格
    def format_level_summary(name: str, interval: str, summary: Dict) -> str:
        trend = summary.get("trend", "unknown")
        trend_map = {"up_trend": "上升趋势", "down_trend": "下降趋势", "consolidation": "震荡盘整", "unknown": "未知"}
        pos = summary.get("price_vs_zs", "unknown")
        pos_map = {"above": "中枢上方", "below": "中枢下方", "inside": "中枢内部", "unknown": "无中枢"}
        
        zs_info = ""
        if summary.get("latest_zs"):
            zs = summary["latest_zs"]
            zs_info = f"ZG={zs['zg']:.0f}, ZD={zs['zd']:.0f}"
        
        signals = ", ".join(summary.get("recent_mmds", [])) or "无"
        
        return f"""### {name} ({interval})
- 趋势: {trend_map.get(trend, trend)}
- 价格位置: {pos_map.get(pos, pos)}
- 中枢: {zs_info or '无'}
- 买卖点信号: {signals}
- 笔数量: {summary.get('bi_count', 0)}, 线段数量: {summary.get('xd_count', 0)}, 中枢数量: {summary.get('zs_count', 0)}
"""
    
    large_text = format_level_summary(large.get("name", "大级别"), large.get("interval", "4h"), large_summary)
    medium_text = format_level_summary(medium.get("name", "中级别"), medium.get("interval", "1h"), medium_summary)
    small_text = format_level_summary(small.get("name", "小级别"), small.get("interval", "15m"), small_summary)
    
    # 详细数据（中级别的完整 JSON）
    medium_json = json.dumps(medium.get("ai_json", {}), ensure_ascii=False, indent=2, default=_json_serializer)
    
    return f"""# 缠论多级别联立分析

你是一名精通缠论的数字货币交易分析师。请根据以下【多级别缠论数据】进行综合分析。

{TERMINOLOGY_BLOCK}

## 多级别分析核心原则

1. **大级别定方向**：大级别趋势决定主要操作方向
2. **中级别找买卖点**：中级别结构确定买卖点位置
3. **小级别精入场**：小级别结构确定精确入场时机

## 当前品种
- **交易对**: {symbol}
- **当前价格**: {latest_price:.2f}

---

## 多级别结构摘要

{large_text}
{medium_text}
{small_text}

---

## 中级别详细数据

```json
{medium_json}
```

---

## 输出要求

【系统约束】
你是一个【缠论多级别联立分析引擎】。
必须综合三个级别的结构进行分析，不能只看单一级别。

【分析重点】
1. 三级别趋势是否一致？（一致性越高，信号越可靠）
2. 大级别处于什么位置？（决定操作方向）
3. 中级别有无买卖点？（确定交易信号）
4. 小级别是否可以入场？（确定入场时机）

【严禁事项】
- 禁止使用技术指标（均线、MACD、RSI 等）
- 禁止引入外部行情、消息、情绪
- 禁止只分析单一级别

【输出格式】
严格按照以下 JSON Schema 输出：

```json
{schema}
```

【特殊要求】
1. analysis 字段必须包含多级别联立分析内容：
   - 大级别趋势判断
   - 中级别买卖点分析
   - 小级别入场时机
   - 三级别一致性评估
2. primary_scenario 的 reasoning 必须说明多级别配合关系
3. 概率评估需要考虑多级别趋势一致性

请直接输出符合 Schema 的 JSON：
"""


def build_state_machine_prompt(
    ai_json: Dict[str, Any],
    stats_context: str = "",
    history_context: str = "",
    learning_feedback: str = "",
) -> str:
    """
    构建状态机模式的 Prompt（v2.0 新增）

    强制 AI 输出状态机格式，而非多场景并列模式

    参数：
    - ai_json: 缠论结构 JSON
    - stats_context: 历史统计上下文
    - history_context: 相似案例上下文
    - learning_feedback: AI 自我认知

    返回：
    - 状态机模式的 Prompt
    """
    from ai_output_schema import get_state_machine_schema_template

    json_str = json.dumps(ai_json, ensure_ascii=False, indent=2, default=_json_serializer)
    schema = get_state_machine_schema_template()

    meta = ai_json.get("meta", {})
    market = ai_json.get("market", {})
    symbol = meta.get("symbol", "Unknown")
    interval = meta.get("interval", "Unknown")
    latest_price = float(market.get("latest_price", 0.0))

    # 获取结构摘要
    structure_summary = ai_json.get("structure_summary", {})
    trend_desc = structure_summary.get("trend_description", "未知")
    position_desc = structure_summary.get("position_description", "未知")
    key_levels = structure_summary.get("key_levels", {})
    price_position = structure_summary.get("price_position", "unknown")

    # 统计提示
    in_zs = price_position == "inside_zs"
    stat = get_stat_hint(symbol=symbol, interval=interval, in_zs=in_zs)
    win_rate_str = f"{stat['win_rate']}" if stat.get("win_rate") is not None else "N/A"

    stat_block = f"""
【统计提示】
交易对：{symbol}，周期：{interval}，结构位置：{"中枢内" if in_zs else "中枢外"}
样本数量：{stat["sample"]}
历史胜率：{win_rate_str}
"""

    # 历史上下文块
    history_block = ""
    if history_context:
        history_block = history_context + "\n"

    # 学习反馈块
    learning_block = ""
    if learning_feedback:
        learning_block = learning_feedback + "\n"

    # 系统约束（状态机专用）
    system_block = """
【系统约束】
你是一个"交易决策状态机生成器"，不是分析师。

【强制规则】
1. 任意时刻，只能有一个 active_strategy
2. active_strategy 必须有明确状态（WAIT / READY / ACTIVE）
3. entry 必须是"结构触发 + 价格区间"，不能只有价格
4. 必须定义 invalidation 条件（什么情况下放弃当前策略）
5. 如果历史胜率 < 30%，必须输出 WAIT_CONFIRMATION 或 OBSERVE_ONLY 状态
6. 禁止同时给出做多 / 做空 / 震荡的完整策略（只能有一个激活）
"""

    # 缠论结构 JSON
    structure_block = f"""
【缠论结构 JSON】
{json_str}
"""

    # 输出格式约束
    output_block = f"""
【输出格式】
1. 必须输出符合 Schema 的合法 JSON
2. state_machine.current_state 必须是 STRATEGY_ACTIVE / WAIT_CONFIRMATION / OBSERVE_ONLY 之一
3. state_machine.active_strategy 必须包含：
   - direction: 策略方向（up/down）
   - status: 策略状态（WAIT/READY/ACTIVE/INVALIDATED）
   - entry_gate: 入场门槛（必须包含 price_zone 和 structure_required）
   - execution: 执行参数（stop_loss, target, rr）
4. structure_required 不能为空，必须是具体的缠论术语条件
5. 必须定义 invalidation.invalidate_active_if（至少1个条件）
6. 如果历史胜率低，自动降级状态：
   - 胜率 < 25% → OBSERVE_ONLY
   - 胜率 25-35% → WAIT_CONFIRMATION
   - 胜率 > 35% → STRATEGY_READY

【JSON Schema】
```json
{schema}
```
"""

    # 组装 Prompt
    blocks = {
        "system_block": system_block,
        "structure_block": structure_block,
        "output_block": output_block,
        "stat_block": stat_block,
        "TERMINOLOGY_BLOCK": TERMINOLOGY_BLOCK,
        "learning_block": learning_block,
        "history_block": history_block,
    }

    prompt = build_prompt_with_token_management(blocks, max_tokens=SAFE_TOKENS)

    return prompt

