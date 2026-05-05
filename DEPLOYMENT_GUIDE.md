# ChanLun AI 部署指南 (Linux VPS版)

## 📍 项目位置
```
/root/.openclaw/workspace/chanlun_ai
```

## ✅ 已完成

1. **克隆仓库** ✅
   ```bash
   git clone https://github.com/namegaobin/chanlun_ai.git
   ```

2. **创建虚拟环境** ✅
   - 环境路径：`/root/.openclaw/workspace/chanlun_ai/venv`
   - Python版本：3.12.3
   - 已安装核心依赖：
     - numpy 2.4.4
     - pandas 3.0.2
     - matplotlib 3.10.9
     - mplfinance 0.12.10b0
     - fastapi 0.136.1
     - uvicorn 0.46.0
     - requests 2.33.1

3. **配置文件** ✅
   - 已创建 `.env` 文件
   - 默认配置使用 DeepSeek API

## 🔑 配置API Key

### 方法1：手动编辑（推荐）

```bash
cd ~/.openclaw/workspace/chanlun_ai
nano .env
```

修改这一行：
```env
DEEPSEEK_API_KEY=你的实际DeepSeek_API_Key
```

或者如果是腾讯云 DeepSeek：
```env
DEEPSEEK_API_KEY=你的腾讯云DeepSeek_API_Key
```

## 🚀 运行项目

### 使用虚拟环境运行

```bash
cd /root/.openclaw/workspace/chanlun_ai

# 分析 BTC/USDT 1小时周期
./venv/bin/python chanlun_ai.py BTCUSDT 1h --limit 200

# 结构化输出（保存到数据库）
./venv/bin/python chanlun_ai.py BTCUSDT 1h --structured --limit 200

# Markdown表格格式
./venv/bin/python chanlun_ai.py BTCUSDT 1h --table --limit 200

# 启动Web服务
./venv/bin/python api/server.py
```

或者激活虚拟环境：

```bash
cd /root/.openclaw/workspace/chanlun_ai
source venv/bin/activate

# 激活后可以直接用 python 命令
python chanlun_ai.py BTCUSDT 1h --limit 200
```

## 📊 虚拟环境信息

| 项目 | 值 |
|------|-----|
| 环境路径 | /root/.openclaw/workspace/chanlun_ai/venv |
| Python版本 | 3.12.3 |

### 已安装包

```
fastapi      0.136.1
matplotlib    3.10.9
numpy         2.4.4
pandas        3.0.2
requests      2.33.1
uvicorn       0.46.0
mplfinance    0.12.10b0
+ 其他依赖...
```

## 🌐 Web界面

```bash
./quick_start.sh web
```

访问：http://localhost:8000

## 🔧 常用命令

```bash
# 激活虚拟环境
source venv/bin/activate

# 分析BTC 1小时
python chanlun_ai.py BTCUSDT 1h

# 分析ETH 15分钟
python chanlun_ai.py ETHUSDT 15m

# 多级别分析
python chanlun_ai.py BTCUSDT 4h
python chanlun_ai.py BTCUSDT 1h
python chanlun_ai.py BTCUSDT 15m

# 查看统计
python query_stats.py
```

## 📝 环境管理

### 安装额外依赖

```bash
./venv/bin/pip install 包名
```

### 更新依赖

```bash
./venv/bin/pip install --upgrade numpy pandas
```

## ⚠️ 注意事项

1. **网络访问**：如果服务器需要代理访问外网，在 `.env` 中配置：
   ```
   HTTP_PROXY=http://127.0.0.1:端口
   HTTPS_PROXY=http://127.0.0.1:端口
   ```
2. **API Key安全**：不要将 `.env` 文件提交到Git
3. **虚拟环境**：使用 venv 而不是 conda

## 🐛 故障排除

### 问题1：Python版本不对

```bash
./venv/bin/python --version
```

### 问题2：缺少依赖

```bash
cd /root/.openclaw/workspace/chanlun_ai
./venv/bin/pip install -r requirements.txt
```

### 问题3：网络无法访问外网

如果 curl https://api.binance.com/api/v3/ping 超时：

1. 检查是否有代理需要启动
2. 或者直接通过内网测试功能
3. 配置 `.env` 中的代理设置

## 📞 支持

- GitHub Issues: https://github.com/namegaobin/chanlun_ai/issues
- 项目作者：namegaobin

---

**更新时间**：2026-05-01 00:45 GMT+8
**部署状态**：✅ 使用虚拟环境 (venv)
**Python版本**：3.12.3
**服务器**：VM-0-9-ubuntu (腾讯云)
**项目路径**：/root/.openclaw/workspace/chanlun_ai