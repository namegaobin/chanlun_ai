# 🎯 下一步操作指南

## 当前状态

✅ **项目已克隆**
✅ **虚拟环境已创建** (Python 3.12)
✅ **依赖已安装**
✅ **配置文件已创建** (.env)
✅ **快速启动脚本已创建** (quick_start.sh)

## 🔑 关键步骤：配置API Key

你需要配置DeepSeek API Key才能运行项目。

### 方法1：手动编辑（推荐）

```bash
cd ~/.openclaw/workspace/chanlun_ai
nano .env
```

修改这一行：
```
DEEPSEEK_API_KEY=你的API_Key
```

### 方法2：直接替换

```bash
cd ~/.openclaw/workspace/chanlun_ai
sed -i '' 's/YOUR_DEEPSEEK_KEY_HERE/你的实际API_Key/' .env
```

## 🚀 测试运行

配置好API Key后，运行：

```bash
cd ~/.openclaw/workspace/chanlun_ai
./quick_start.sh analyze
```

或者：

```bash
cd ~/.openclaw/workspace/chanlun_ai
source venv/bin/activate
python chanlun_ai.py BTCUSDT 1h --limit 200
```

## 📊 预期输出

```
============================================================
📝 AI 市场分析
============================================================
  当前BTC/USDT处于1小时周期的缠论结构中...
  【做多策略（概率55%）】：入场91xxx，目标92xxx，止损90xxx
  【做空策略（概率25%）】：入场90xxx，目标89xxx，止损91xxx
  【震荡策略（概率20%）】：区间90xxx-91xxx
============================================================
```

## 🌐 启动Web界面

```bash
./quick_start.sh web
```

访问：http://localhost:8000

## 📚 查看完整文档

- 部署指南：`DEPLOYMENT_GUIDE.md`
- 项目README：`README.md`
- 命令文档：`COMMANDS.md`

---

**需要帮助？**
- GitHub Issues: https://github.com/namegaobin/chanlun_ai/issues
