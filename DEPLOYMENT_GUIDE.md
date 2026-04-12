# ChanLun AI 部署指南 (Conda版本)

## 📍 项目位置
```
/Users/alvingao/.openclaw/workspace/chanlun_ai
```

## ✅ 已完成

1. **克隆仓库** ✅
   ```bash
   git clone https://github.com/namegaobin/chanlun_ai.git
   ```

2. **使用现有Conda环境** ✅
   - 环境名称：`chanClaw`
   - 环境路径：`/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw`
   - Python版本：3.12.11
   - 已安装核心依赖：
     - numpy 2.4.4
     - pandas 3.0.1
     - matplotlib 3.10.8
     - fastapi 0.104.1
     - uvicorn 0.24.0
     - requests 2.33.0

3. **符号链接** ✅
   ```bash
   ln -sfn /opt/homebrew/Caskroom/miniforge/base/envs/chanClaw conda_env
   ```

4. **配置文件** ✅
   - 已创建 `.env` 文件
   - 已配置为使用 DeepSeek API

5. **快速启动脚本** ✅
   - 已更新为使用conda环境
   - 支持：analyze, structured, table, web, stats, info

## 🔑 配置API Key

### 方法1：手动编辑（推荐）

```bash
cd ~/.openclaw/workspace/chanlun_ai
nano .env
```

修改这一行：
```env
DEEPSEEK_API_KEY=你的API_Key
```

### 方法2：使用sed替换

```bash
cd ~/.openclaw/workspace/chanlun_ai
sed -i '' 's/YOUR_DEEPSEEK_KEY_HERE/你的实际API_Key/' .env
```

## 🚀 运行项目

### 使用快速启动脚本（推荐）

```bash
cd ~/.openclaw/workspace/chanlun_ai

# 查看环境信息
./quick_start.sh info

# 分析 BTC/USDT 1小时周期
./quick_start.sh analyze

# 结构化输出
./quick_start.sh structured

# Markdown表格格式
./quick_start.sh table

# 启动Web服务
./quick_start.sh web
```

### 手动运行

```bash
# 方法1：使用conda环境路径
cd ~/.openclaw/workspace/chanlun_ai
/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw/bin/python chanlun_ai.py BTCUSDT 1h --limit 200

# 方法2：设置PATH
export PATH="/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw/bin:$PATH"
python chanlun_ai.py BTCUSDT 1h --limit 200
```

## 📊 Conda环境信息

| 项目 | 值 |
|------|-----|
| 环境名称 | chanClaw |
| 环境路径 | /opt/homebrew/Caskroom/miniforge/base/envs/chanClaw |
| Python版本 | 3.12.11 |
| 符号链接 | conda_env -> chanClaw环境 |

### 已安装包

```
fastapi      0.104.1
matplotlib    3.10.8
numpy         2.4.4
pandas        3.0.1
requests      2.33.0
uvicorn       0.24.0
+ 其他依赖...
```

## 🌐 Web界面

```bash
./quick_start.sh web
```

访问：http://localhost:8000

## 🔧 常用命令

```bash
# 查看环境信息
./quick_start.sh info

# 分析BTC 1小时
./quick_start.sh analyze BTCUSDT 1h

# 分析ETH 15分钟
./quick_start.sh analyze ETHUSDT 15m

# 多级别分析
./quick_start.sh analyze BTCUSDT 4h
./quick_start.sh analyze BTCUSDT 1h
./quick_start.sh analyze BTCUSDT 15m

# 查看统计
./quick_start.sh stats
```

## 📝 环境管理

### 查看所有conda环境

```bash
conda env list
```

输出：
```
base                   /opt/homebrew/Caskroom/miniforge/base
chan                   /opt/homebrew/Caskroom/miniforge/base/envs/chan
chanClaw             *  /opt/homebrew/Caskroom/miniforge/base/envs/chanClaw  ← 当前使用
chan_backtest          /opt/homebrew/Caskroom/miniforge/base/envs/chan_backtest
chanlun                /opt/homebrew/Caskroom/miniforge/base/envs/chanlun
```

### 安装额外依赖

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw/bin/pip install 包名
```

### 更新依赖

```bash
/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw/bin/pip install --upgrade numpy pandas
```

## ⚠️ 注意事项

1. **环境位置**：使用的是已存在的 `chanClaw` conda环境
2. **符号链接**：`conda_env` 链接到实际的conda环境路径
3. **PATH设置**：快速启动脚本会自动设置正确的PATH
4. **API Key安全**：不要将 `.env` 文件提交到Git

## 🐛 故障排除

### 问题1：Python版本不对

```bash
# 检查Python版本
./quick_start.sh info

# 如果版本不对，检查conda环境
conda env list
```

### 问题2：缺少依赖

```bash
# 手动安装依赖
cd ~/.openclaw/workspace/chanlun_ai
/opt/homebrew/Caskroom/miniforge/base/envs/chanClaw/bin/pip install -r requirements.txt
```

### 问题3：环境不存在

```bash
# 检查所有环境
conda env list

# 如果 chanClaw 不在列表中，使用其他Python 3.12环境
# 或创建新环境（但conda create命令可能有问题）
```

## 📞 支持

- GitHub Issues: https://github.com/namegaobin/chanlun_ai/issues
- 项目作者：namegaobin

---

**更新时间**：2026-04-12 16:35 GMT+8
**部署状态**：✅ 使用Conda环境 (chanClaw)
**Python版本**：3.12.11