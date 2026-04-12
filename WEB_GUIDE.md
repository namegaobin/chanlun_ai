# ChanLun AI Web界面启动指南

## 🌐 Web界面架构

```
ChanLun AI Web
├── 后端API服务 (FastAPI)
│   ├── 端口: 8001
│   ├── 文件: api/server.py
│   └── 功能: 提供缠论分析API
│
└── 前端界面 (Vue 3 + Vite)
    ├── 端口: 5173
    ├── 目录: web/
    └── 功能: 可视化交互界面
```

---

## 🚀 快速启动

### 方法1：使用启动脚本（推荐）

```bash
cd ~/.openclaw/workspace/chanlun_ai

# 设置代理（如果需要）
export http_proxy=http://127.0.0.1:11090
export https_proxy=http://127.0.0.1:11090

# 启动Web界面
./start_web_simple.sh
```

**首次运行会自动安装前端依赖（npm install）**

### 方法2：手动启动

```bash
# 1. 设置环境
export PATH="/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw/bin:$PATH"
export http_proxy=http://127.0.0.1:11090
export https_proxy=http://127.0.0.1:11090

cd ~/.openclaw/workspace/chanlun_ai

# 2. 安装前端依赖（首次运行）
cd web
npm install
cd ..

# 3. 启动后端API（端口8001）
python api/server.py &

# 4. 启动前端界面（端口5173）
cd web && npm run dev
```

---

## 📡 访问地址

启动成功后，访问：

- **前端界面**: http://localhost:5173
- **后端API文档**: http://localhost:8001/docs
- **健康检查**: http://localhost:8001/health

---

## ⚙️ 依赖要求

### 后端（Python）
- ✅ 已在conda环境中安装
- FastAPI 0.104.1
- uvicorn 0.24.0

### 前端（Node.js）
- Node.js（需要npm）
- Vue 3.4.0
- Vite 5.0.0
- Element Plus 2.5.0
- ECharts 5.5.0

**首次运行会自动安装前端依赖**

---

## 🛑 停止服务

按 `Ctrl+C` 停止所有服务

---

## 🐛 常见问题

### 问题1：端口被占用
```bash
# 查看端口占用
lsof -i :8001  # 后端端口
lsof -i :5173  # 前端端口

# 杀死进程
kill -9 <PID>
```

### 问题2：npm安装失败
```bash
# 检查Node.js版本
node --version  # 需要 Node.js 16+

# 清除缓存
cd web
rm -rf node_modules package-lock.json
npm install
```

### 问题3：API连接失败
```bash
# 检查后端是否启动
curl http://localhost:8001/health

# 检查代理是否开启
echo $http_proxy
```

---

## 📊 Web界面功能

### 主要功能
1. **实时K线获取** - 从Binance获取实时数据
2. **缠论结构分析** - 自动识别笔、线段、中枢
3. **AI智能分析** - 使用DeepSeek进行市场分析
4. **可视化展示** - ECharts图表展示
5. **交互式操作** - Element Plus UI组件

### API端点
- `POST /analyze` - 执行缠论分析
- `GET /health` - 健康检查
- `GET /docs` - API文档

---

## 🔧 配置文件

### 后端配置
- `.env` - API配置（DeepSeek）
- `api/server.py` - FastAPI配置

### 前端配置
- `web/vite.config.ts` - Vite配置
- `web/package.json` - npm依赖

---

## 📚 相关文档

- `README.md` - 项目说明
- `DEPLOYMENT_GUIDE.md` - 部署指南
- `web/README.md` - 前端说明

---

**更新时间**: 2026-04-12 16:58 GMT+8
