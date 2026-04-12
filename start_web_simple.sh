#!/bin/bash

# ChanLun AI Web界面启动脚本
# 使用方法: ./start_web_simple.sh

cd "$(dirname "$0")"

# Conda环境路径
CONDA_ENV="/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw"

echo "🌐 ChanLun AI Web 界面启动"
echo "================================"
echo ""

# 检查conda环境
if [ ! -d "$CONDA_ENV" ]; then
    echo "❌ Conda环境不存在: $CONDA_ENV"
    exit 1
fi

export PATH="$CONDA_ENV/bin:$PATH"
PYTHON="$CONDA_ENV/bin/python"

# 设置代理（如果需要）
export http_proxy=http://127.0.0.1:11090
export https_proxy=http://127.0.0.1:11090

# 检查前端依赖
echo "📦 检查前端依赖..."
if [ ! -d "web/node_modules" ]; then
    echo "  正在安装前端依赖（首次运行需要）..."
    cd web
    npm install
    cd ..
    echo "  ✓ 前端依赖安装完成"
else
    echo "  ✓ 前端依赖已安装"
fi
echo ""

# 启动后端API服务
echo "🚀 启动后端 API 服务 (端口 8001)..."
$PYTHON api/server.py &
API_PID=$!
echo "  ✓ API 服务已启动 (PID: $API_PID)"
sleep 2
echo ""

# 启动前端开发服务器
echo "🎨 启动前端开发服务器 (端口 5173)..."
cd web
npm run dev &
WEB_PID=$!
cd ..
echo "  ✓ 前端服务已启动 (PID: $WEB_PID)"
echo ""

echo "================================"
echo "✅ Web界面已启动！"
echo ""
echo "📡 后端API: http://localhost:8001"
echo "🌐 前端界面: http://localhost:5173"
echo ""
echo "按 Ctrl+C 停止服务"
echo "================================"
echo ""

# 等待用户按Ctrl+C
trap "echo ''; echo '🛑 正在停止服务...'; kill $API_PID $WEB_PID 2>/dev/null; exit 0" INT TERM

# 保持脚本运行
wait
