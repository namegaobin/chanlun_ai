#!/bin/bash

# ChanLun AI 快速启动脚本 (Conda版本)
# 使用方法: ./quick_start.sh [命令]

cd "$(dirname "$0")"

# Conda环境路径
CONDA_ENV="/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw"

# 检查conda环境
if [ ! -d "$CONDA_ENV" ]; then
    echo "❌ Conda环境不存在: $CONDA_ENV"
    echo "请先运行: conda create -n chanClaw python=3.12"
    exit 1
fi

# 设置Python路径
export PATH="$CONDA_ENV/bin:$PATH"
PYTHON="$CONDA_ENV/bin/python"

# 检查.env文件
if [ ! -f ".env" ]; then
    echo "❌ .env 文件不存在，正在创建..."
    cp .env.example .env
    echo "⚠️  请编辑 .env 文件配置你的API Key"
    exit 1
fi

# 执行命令
case "$1" in
    "analyze"|"a")
        # 快速分析
        SYMBOL=${2:-BTCUSDT}
        INTERVAL=${3:-1h}
        LIMIT=${4:-200}
        echo "📊 分析 $SYMBOL $INTERVAL (K线数: $LIMIT)"
        echo "🐍 Python: $($PYTHON --version)"
        $PYTHON chanlun_ai.py $SYMBOL $INTERVAL --limit $LIMIT
        ;;
    "structured"|"s")
        # 结构化分析
        SYMBOL=${2:-BTCUSDT}
        INTERVAL=${3:-1h}
        LIMIT=${4:-200}
        echo "📊 结构化分析 $SYMBOL $INTERVAL"
        $PYTHON chanlun_ai.py $SYMBOL $INTERVAL --structured --limit $LIMIT
        ;;
    "table"|"t")
        # Markdown表格
        SYMBOL=${2:-BTCUSDT}
        INTERVAL=${3:-1h}
        LIMIT=${4:-200}
        echo "📊 生成Markdown报告 $SYMBOL $INTERVAL"
        $PYTHON chanlun_ai.py $SYMBOL $INTERVAL --table --limit $LIMIT
        ;;
    "web"|"w")
        # 启动Web服务
        echo "🌐 启动Web服务..."
        echo "使用简化启动脚本..."
        exec ./start_web_simple.sh
        ;;
    "restart"|"r")
        # 重启服务
        exec ./restart_services.sh
        ;;
    "stats")
        # 统计报告
        echo "📈 生成统计报告..."
        $PYTHON stats_report.py
        ;;
    "info"|"i")
        # 显示环境信息
        echo "🐍 Python版本:"
        $PYTHON --version
        echo ""
        echo "📦 已安装的核心包:"
        $PYTHON -m pip list | grep -E "(numpy|pandas|matplotlib|fastapi|uvicorn|requests)"
        echo ""
        echo "🔑 API配置:"
        grep -E "^AI_PROVIDER|^AI_MODEL" .env 2>/dev/null || echo "未配置"
        ;;
    "help"|"h"|*)
        echo "🤖 ChanLun AI 快速启动 (Conda版本)"
        echo ""
        echo "使用方法:"
        echo "  ./quick_start.sh [命令] [参数]"
        echo ""
        echo "命令:"
        echo "  analyze (a)   - 快速分析 (默认: BTCUSDT 1h)"
        echo "  structured (s) - 结构化分析"
        echo "  table (t)     - Markdown报告"
        echo "  web (w)       - 启动Web界面"
        echo "  restart (r)   - 重启后端和前端服务"
        echo "  stats         - 统计报告"
        echo "  info (i)      - 显示环境信息"
        echo "  help (h)      - 显示帮助"
        echo ""
        echo "Conda环境: $CONDA_ENV"
        echo ""
        echo "示例:"
        echo "  ./quick_start.sh analyze BTCUSDT 1h 200"
        echo "  ./quick_start.sh web"
        echo "  ./quick_start.sh restart"
        echo ""
        ;;
esac
