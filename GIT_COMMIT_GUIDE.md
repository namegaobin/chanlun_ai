# 安全提交指南 - 过滤大模型 API Key

## 🚨 关键原则

**永远不要提交包含真实 API Key、密码等敏感信息的文件！**

---

## ✅ 提交前检查清单

### 1. 检查 .gitignore 配置

确保以下文件/目录已被过滤：

```bash
# 查看当前 .gitignore
cat .gitignore

# 应该包含以下内容：
.env                # ⚠️ 环境变量文件（最重要！）
*.log               # 日志文件
logs/               # 日志目录
node_modules/       # 前端依赖
venv/               # Python 虚拟环境
*.db                # 数据库文件
chanlun_ai.db       # 项目的 SQLite 数据
*.sqlite*           # SQLite 文件
config.yaml         # 如果包含敏感配置
```

### 2. 检查是否有 .env 文件被跟踪

```bash
# 检查 .env 是否被 git 跟踪
git ls-files | grep "\.env$"

# 如果有输出，说明 .env 已经被提交，需要立即移除（见下方"清理历史"部分）
```

### 3. 搜索代码中硬编码的密钥

```bash
# 搜索可能泄露的 API Key
grep -r "sk-" --include="*.py" --include="*.ts" --include="*.js" . | grep -v node_modules

# 搜索常见的密钥变量名
grep -r "api_key\|API_KEY\|secret\|SECRET" --include="*.py" --include="*.ts" . | \
  grep -v "os.getenv\|os.environ\|getenv\|environ" | \
  grep -v node_modules
```

---

## 📝 正确的提交流程（当前项目）

### 步骤 1: 查看当前修改

```bash
cd /root/.openclaw/workspace/chanlun_ai
git status
git diff --stat
```

### 步骤 2: 安全检查

```bash
# 确认没有 .env 文件被跟踪
git ls-files | grep "\.env$"  # 应该无输出 ✅

# 确认没有硬编码密钥
git diff | grep -E "(sk-|api_key.*[a-zA-Z0-9]{20,})"  # 应该无输出 ✅
```

### 步骤 3: 添加文件（安全）

```bash
# 添加所有修改（.env 会被 .gitignore 自动过滤）
git add .
```

### 步骤 4: 再次检查

```bash
# 查看待提交文件
git status

# 检查暂存区
git diff --cached --name-only
```

### 步骤 5: 提交

```bash
git commit -m "fix: 配置代理 + 修复前端 API 调用 + 默认市场改为 BTC

- 修复 binance.py 代理配置，硬编码默认代理地址避免环境变量丢失
- API 服务改为绑定 127.0.0.1:8003（仅本地访问）
- 前端服务改为绑定 0.0.0.0:5173（支持外网访问）
- 前端 API 调用改为相对路径，通过 Vite 代理转发
- 首页默认市场改为加密货币（BTCUSDT 15m）
- 更新 DEPLOYMENT_GUIDE.md 文档"
```

### 步骤 6: 推送

```bash
git push origin main
```

---

## 🔐 当前项目的安全状态

### ✅ 已配置的 .gitignore 规则

- `.env` - 环境变量文件（包含 DEEPSEEK_API_KEY）
- `*.log` - 日志文件
- `logs/` - 日志目录
- `node_modules/` - 前端依赖
- `venv/` - 虚拟环境
- `*.db` - 数据库文件
- `chanlun_ai.db` - 项目数据库

### ✅ 代码中的 Key 使用方式

**安全实践：**
```python
# binance.py - 使用环境变量 + 硬编码默认值
_PROXY = os.environ.get("HTTP_PROXY") or \
         os.environ.get("http_proxy") or \
         os.environ.get("HTTPS_PROXY") or \
         os.environ.get("https_proxy") or \
         "http://127.0.0.1:11090"  # 默认代理地址
```

**安全实践：**
```python
# analyze_service.py - 从前端传入或环境变量读取
api_key = data.get("api_key")  # 前端传递
# 或
api_key = os.getenv("DEEPSEEK_API_KEY")  # 环境变量
```

### ⚠️ 本地存在的 .env 文件

本地有 `.env` 文件包含真实 API Key，但：
- ✅ 已在 .gitignore 中配置
- ✅ 未被 git 跟踪
- ✅ 不会被提交

---

## 📌 当前修改文件

```
DEPLOYMENT_GUIDE.md                      | 修改
api/server.py                            | 修改（host 127.0.0.1）
binance.py                               | 修改（硬编码代理）
chanlun_ai.py                            | 修改
web/src/App.vue                          | 修改（默认市场 crypto）
web/src/components/TradingViewWidget.vue | 修改（相对路径）
web/vite.config.ts                       | 修改（host 0.0.0.0）
```

所有修改均**不包含敏感信息** ✅

---

## ⚠️ 如果不小心提交了 API Key

### 紧急处理步骤

```bash
# 1. 立即删除敏感文件
git rm --cached .env
echo "DEEPSEEK_API_KEY=your-key-here" > .env

# 2. 提交删除
git commit -m "security: 移除 .env 文件"
git push

# 3. 在 API 提供商处撤销泄露的 Key，生成新的 Key

# 4. 如果需要清理历史（危险操作）
# git filter-branch --force --index-filter \
#   'git rm --cached --ignore-unmatch .env' \
#   --prune-empty --tag-name-filter cat -- --all
# git push --force
```

---

## 📚 参考资源

- [GitHub 官方文档：Removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
- [git-filter-branch 官方文档](https://git-scm.com/docs/git-filter-branch)

---

**最后提醒**：每次提交前，永远检查是否有敏感信息被包含！
