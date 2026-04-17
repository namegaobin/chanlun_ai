#!/bin/bash

# ChanLun AI 重启服务脚本
# 使用方法: ./restart_services.sh

cd "$(dirname "$0")"

# Conda环境路径
CONDA_ENV="/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw"

# 日志目录
LOG_DIR="./logs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
API_LOG="$LOG_DIR/api_${TIMESTAMP}.log"
WEB_LOG="$LOG_DIR/web_${TIMESTAMP}.log"

echo "🔄 ChanLun AI 服务重启"
echo "================================"
echo ""

# 检查conda环境
if [ ! -d "$CONDA_ENV" ]; then
    echo "❌ Conda环境不存在: $CONDA_ENV"
    exit 1
fi

export PATH="$CONDA_ENV/bin:$PATH"
PYTHON="$CONDA_ENV/bin/python"

# ========================================
# 第一步：停止现有服务
# ========================================

echo "🛑 停止现有服务..."

# 查找并停止后端API服务（server.py）
API_PIDS=$(ps aux | grep "python.*server.py" | grep -v grep | awk '{print $2}')
if [ -n "$API_PIDS" ]; then
    echo "  停止后端API服务 (PID: $API_PIDS)..."
    kill $API_PIDS 2>/dev/null
    sleep 2
    # 强制杀死残留进程
    kill -9 $API_PIDS 2>/dev/null
    echo "  ✓ 后端API服务已停止"
else
    echo "  ℹ️  后端API服务未运行"
fi

# 查找并停止前端服务（vite）
VITE_PIDS=$(ps aux | grep "vite" | grep -v grep | awk '{print $2}')
if [ -n "$VITE_PIDS" ]; then
    echo "  停止前端服务 (PID: $VITE_PIDS)..."
    kill $VITE_PIDS 2>/dev/null
    sleep 2
    # 强制杀死残留进程
    kill -9 $VITE_PIDS 2>/dev/null
    echo "  ✓ 前端服务已停止"
else
    echo "  ℹ️  前端服务未运行"
fi

# 查找并停止npm进程
NPM_PIDS=$(ps aux | grep "npm.*run.*dev" | grep -v grep | awk '{print $2}')
if [ -n "$NPM_PIDS" ]; then
    echo "  停止npm进程 (PID: $NPM_PIDS)..."
    kill $NPM_PIDS 2>/dev/null
    sleep 1
    kill -9 $NPM_PIDS 2>/dev/null
    echo "  ✓ npm进程已停止"
fi

echo ""
echo "等待端口释放..."
sleep 3

# ========================================
# 第二步：启动服务
# ========================================

echo ""
echo "🚀 启动服务..."
echo ""

# 启动后端API服务
echo "📡 启动后端 API 服务..."
echo "  📝 日志文件: $API_LOG"
$PYTHON api/server.py > "$API_LOG" 2>&1 &
API_PID=$!
echo "  ✓ API 服务已启动 (PID: $API_PID)"
sleep 2

# 启动前端开发服务器
echo "🎨 启动前端开发服务器..."
echo "  📝 日志文件: $WEB_LOG"
cd web
npm run dev > "../$WEB_LOG" 2>&1 &
WEB_PID=$!
cd ..
echo "  ✓ 前端服务已启动 (PID: $WEB_PID)"

echo ""
echo "================================"
echo "✅ 服务重启完成！"
echo ""
echo "📡 后端API: http://localhost:8003"
echo "🌐 前端界面: http://localhost:5173"
echo ""
echo "📝 日志文件:"
echo "  后端: $API_LOG"
echo "  前端: $WEB_LOG"
echo "  实时查看: tail -f $API_LOG"
echo ""
echo "PID文件:"
echo "  后端PID: $API_PID"
echo "  前端PID: $WEB_PID"
echo ""
echo "按 Ctrl+C 停止服务"
echo "================================"
echo ""

# 等待用户按Ctrl+C
trap "echo ''; echo '🛑 正在停止服务...'; kill $API_PID $WEB_PID 2>/dev/null; exit 0" INT TERM

# 保持脚本运行
wait
