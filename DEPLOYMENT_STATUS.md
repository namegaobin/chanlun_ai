# ChanLun AI 部署状态

**部署时间**：2026-05-01 00:49 GMT+8
**服务器**：VM-0-9-ubuntu (腾讯云)

## ✅ 已完成

1. **项目克隆**
   - 位置：`/root/.openclaw/workspace/chanlun_ai`
   - 源：https://github.com/namegaobin/chanlun_ai.git

2. **虚拟环境创建**
   - 路径：`/root/.openclaw/workspace/chanlun_ai/venv`
   - Python 版本：3.12.3
   - 包管理器：pip

3. **依赖安装**
   ```
   numpy 2.4.4
   pandas 3.0.2
   matplotlib 3.10.9
   mplfinance 0.12.10b0
   fastapi 0.136.1
   uvicorn 0.46.0
   requests 2.33.1
   python-dotenv 1.2.2
   PyYAML 6.0.3
   + 其他依赖
   ```

4. **配置文件**
   - ✅ 已生成 `.env` 文件（从 `.env.example` 复制）

5. **数据库初始化**
   - ✅ 数据库已创建：`chanlun_ai.db`
   - 表结构：`analysis_snapshot`, `analysis_outcome`
   - 当前记录数：0

6. **工具测试**
   - ✅ CLI 帮助命令正常
   - ✅ Python 导入测试通过

## ⚠️ 待配置项

### 1. DeepSeek API Key（必需）

在 `.env` 文件中配置：

```bash
cd /root/.openclaw/workspace/chanlun_ai
nano .env
```

修改以下行之一：
- DeepSeek 官方：`DEEPSEEK_API_KEY=sk-你的key`
- 腾讯云 DeepSeek：`DEEPSEEK_API_KEY=你的腾讯云key`

### 2. 网络访问（可选）

当前服务器网络状态：
- ❌ 无法直接访问外网（curl/google ping 超时）
- ❌ 网关不可达（10.6.0.1 100% 丢包）
- ❌ 11090 端口代理服务未运行

**选项 A：配置代理**

如果有代理服务，在 `.env` 中配置：
```env
HTTP_PROXY=http://127.0.0.1:端口
HTTPS_PROXY=http://127.0.0.1:端口
```

**选项 B：使用内网/本地数据**

如果不需要实时 Binance 数据，可以用历史数据测试。

**选项 C：忽略网络问题**

如果 DeepSeek API 可以直接访问（可能通过国内节点），可以先测试 AI 功能。

## 🚀 使用方法

### 激活虚拟环境
```bash
cd /root/.openclaw/workspace/chanlun_ai
source venv/bin/activate
```

### 基础运行
```bash
# 标准分析
python chanlun_ai.py BTCUSDT 1h --limit 200

# 结构化输出（推荐）
python chanlun_ai.py BTCUSDT 1h --structured --limit 200

# 仅缠论结构（无需AI）
python chanlun_ai.py BTCUSDT 1h --no-ai --limit 50
```

### 快速启动（不激活环境）
```bash
cd /root/.openclaw/workspace/chanlun_ai
./venv/bin/python chanlun_ai.py BTCUSDT 1h --structured --limit 200
```

### Web 服务
```bash
# 后端 API
./venv/bin/python api/server.py

# 访问：http://服务器IP:8001
# 或如果有前端：
cd web && npm run dev  # 需要安装前端依赖
```

## 📋 下一步检查清单

- [ ] 配置 DeepSeek API Key
- [ ] 测试 `python chanlun_ai.py BTCUSDT 1h --no-ai --limit 50`
- [ ] 测试完整 AI 分析（配置 API Key 后）
- [ ] （可选）配置网络代理
- [ ] （可选）设置定时任务（ cron 或 systemd）

## 📄 相关文件

- **部署文档**：`DEPLOYMENT_GUIDE.md`（已更新 Linux 版本）
- **配置文件**：`.env`（需填入 API Key）
- **主程序**：`chanlun_ai.py`
- **数据库**：`chanlun_ai.db`
- **依赖**：`requirements.txt`

---

**部署状态**：🟡 基本完成，等待 API Key 配置
**可用性**：CLI 可用，AI 功能需配置 API Key 后可用
