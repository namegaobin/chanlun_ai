# chanlun_ai_Binance 项目记忆

## 项目概述
- **名称**: 币安BTC缠论AI分析系统
- **功能**: BTC/USDT缠论技术分析 + AI策略建议
- **仓库**: `~/.openclaw/workspace/chanlun_ai_Binance`

---

## 服务配置

### 端口配置（2026-04-12更新）
| 服务 | 端口 | 说明 |
|------|------|------|
| **后端API** | 8003 | FastAPI服务 |
| **前端UI** | 5173 | Vue 3 + Vite |

### 访问地址
- 前端界面: http://localhost:5173
- 后端API: http://localhost:8003
- Web界面: http://localhost:8003/web

---

## 技术栈

### 后端
- **框架**: FastAPI
- **Python环境**: conda env `chanClaw`
- **缠论引擎**: chanlun_local (icl接口)
- **数据源**: Binance API

### 前端
- **框架**: Vue 3 + TypeScript
- **构建工具**: Vite
- **图表库**: ECharts
- **UI组件**: Element Plus

---

## AI模型配置

### DeepSeek（腾讯云托管）
```env
DEEPSEEK_API_KEY=YOUR_TENCENT_DEEPSEEK_KEY
DEEPSEEK_BASE_URL=https://your-tencent-cloud-endpoint/v1/
```

### 代理配置
```bash
# 访问Binance API需要代理
export http_proxy=http://127.0.0.1:11090
export https_proxy=http://127.0.0.1:11090
```

---

## 启动命令

### 后端
```bash
# 方式1: 使用conda环境
export http_proxy=http://127.0.0.1:11090
export https_proxy=http://127.0.0.1:11090
/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw/bin/python ~/.openclaw/workspace/chanlun_ai_Binance/api/server.py

# 方式2: 使用quick_start脚本
cd ~/.openclaw/workspace/chanlun_ai_Binance
./quick_start.sh
```

### 前端
```bash
cd ~/.openclaw/workspace/chanlun_ai_Binance/web
npm run dev
```

---

## API端点

### 核心API
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/kline/{symbol}/{interval}` | GET | K线数据+缠论分析 |
| `/api/analyze/{symbol}/{interval}` | GET | AI分析 |
| `/web` | GET | Web界面 |

### 支持的交易对
- `BTCUSDT` - BTC/USDT
- `ETHUSDT` - ETH/USDT
- 等主流币种

### 支持的时间周期
- `1m` - 1分钟
- `5m` - 5分钟
- `15m` - 15分钟
- `1h` - 1小时
- `4h` - 4小时
- `1d` - 日线

### 示例请求
```bash
# 获取K线和缠论数据
curl "http://localhost:8003/api/kline/BTCUSDT/1h?limit=500"

# AI分析
curl "http://localhost:8003/api/analyze/BTCUSDT/1h"
```

---

## 文件结构

```
chanlun_ai_Binance/
├── api/
│   ├── server.py            # FastAPI主服务（端口8003）
│   ├── analyze_service.py   # 分析服务
│   └── analyze_streaming.py # 流式分析
├── ai/
│   └── llm.py               # LLM客户端
├── chanlun_local/           # 缠论引擎
├── binance.py               # Binance数据获取
├── chanlun_adapter.py       # 缠论适配器
├── chanlun_ai.py            # 主程序
├── web/                     # Vue前端
│   ├── src/
│   │   ├── components/
│   │   │   └── TradingViewWidget.vue  # 图表组件
│   │   └── App.vue
│   └── vite.config.ts
├── quick_start.sh           # 快速启动脚本
├── start_web_simple.sh      # Web启动脚本
└── docs/
    └── PROJECT_MEMORY.md    # 本文件
```

---

## 缠论分析输出

### 返回格式
```json
{
  "meta": {
    "symbol": "BTCUSDT",
    "interval": "1h",
    "count": 500
  },
  "klines": [...],  // K线数据
  "bi": [...],      // 笔
  "xd": [...],      // 线段
  "zs": [...],      // 中枢
  "fx": [...]       // 分型
}
```

---

## 常见问题

### 1. Binance API无法访问
**原因**: 国内需要代理
**解决**: 
```bash
export http_proxy=http://127.0.0.1:11090
export https_proxy=http://127.0.0.1:11090
```

### 2. 前端图表无数据
**检查**: 
1. 后端是否在8003端口运行
2. TradingViewWidget.vue中的API地址是否正确

### 3. 缠论分析结果不准确
**原因**: K线数据不足或缠论参数需要调整
**解决**: 增加`limit`参数，如`?limit=1000`

---

## 端口变更记录

### 2026-04-12
- **后端**: 8001 → 8003
- **前端**: API调用端口从8001改为8003
- **修改文件**: `web/src/components/TradingViewWidget.vue`

---

## 更新日志

### 2026-04-12
- ✅ 后端端口从8001改为8003
- ✅ 更新前端API调用端口
- ✅ 确认服务正常运行
- ✅ 创建项目记忆文件

---

**最后更新**: 2026-04-12 19:47 GMT+8
