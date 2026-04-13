# 黄金实时价格 API 使用指南

本项目已集成黄金（XAUUSD）实时价格获取功能，提供 REST API 端点。

## 数据源

系统支持多个数据源，按优先级自动切换：

1. **yfinance** (GC=F) - Yahoo Finance 黄金期货价格（美元/盎司）
   - 免费但有速率限制（约 15-20 分钟延迟）
   - 自动重试机制应对限流

2. **xxapi_gold** - 国内金价（人民币/克）转换
   - 免费，QPS 限制 50 次/秒
   - 使用美元兑人民币汇率转换为美元/盎司
   - **注意：国内金价与国际金价存在溢价，价格可能偏高**

## API 端点

### 1. 获取实时价格
```
GET /api/gold/price[?source=yfinance]
```

**参数：**
- `source` (可选)：指定数据源，可选值：`yfinance`, `xxapi_gold`

**响应示例：**
```json
{
  "success": true,
  "price": 2315.50,
  "currency": "USD",
  "unit": "ounce",
  "timestamp": "2026-04-12T15:45:30.123456+00:00",
  "source": "yfinance",
  "cached": false
}
```

**错误响应：**
```json
{
  "success": false,
  "error": "所有数据源都失败，最后错误: ...",
  "price": null,
  "currency": null,
  "unit": null,
  "timestamp": null,
  "source": null,
  "cached": false
}
```

### 2. 获取历史 K 线数据（支持缠论分析）
```
GET /api/gold/kline/{interval}[?limit=500]
```

**参数：**
- `interval`：K 线周期，支持：`15m`, `1h`, `4h`, `1d`, `1w`, `1M`
- `limit` (可选)：返回的 K 线数量，默认 500

**响应示例：**
与现有加密货币/A股 K 线端点格式一致，包含：
- `meta`：元数据
- `klines`：K 线数据
- `bi`：笔列表
- `xd`：线段列表
- `zs`：中枢列表
- `fx`：分型列表

## 使用示例

### Python 示例
```python
import requests

# 获取实时价格
price_resp = requests.get("http://localhost:8003/api/gold/price")
price_data = price_resp.json()
if price_data["success"]:
    print(f"黄金价格: {price_data['price']} USD/盎司")
    print(f"数据源: {price_data['source']}")
    print(f"时间: {price_data['timestamp']}")

# 获取历史 K 线
kline_resp = requests.get("http://localhost:8003/api/gold/kline/1h", params={"limit": 100})
kline_data = kline_resp.json()
print(f"获取到 {len(kline_data['klines'])} 条K线数据")
```

### JavaScript 示例
```javascript
// 使用 fetch API
async function getGoldPrice() {
  const response = await fetch('/api/gold/price');
  const data = await response.json();
  if (data.success) {
    console.log(`黄金价格: ${data.price} USD/盎司`);
  }
}

// 每30秒更新一次价格
setInterval(getGoldPrice, 30000);
```

## 配置与缓存

### 缓存机制
- 实时价格缓存 60 秒（避免频繁请求）
- 历史 K 线数据根据周期有不同的缓存时间
- 缓存目录：`.cache/gold_realtime/`

### 数据源配置
如需修改数据源优先级或添加新数据源，请编辑 `gold_realtime.py` 中的 `SOURCES` 列表。

## 注意事项

1. **yfinance 速率限制**：频繁请求可能导致暂时性限流，系统已实现指数退避重试
2. **国内金价差异**：xxapi_gold 提供的是国内金价，与国际金价存在溢价，仅供参考
3. **汇率转换**：xxapi_gold 使用 yfinance 获取实时汇率，如失败则使用固定汇率 7.0
4. **数据延迟**：yfinance 数据延迟约 15-20 分钟，适合非实时场景

## 故障排除

### 常见问题

1. **所有数据源都失败**
   - 检查网络连接
   - 查看服务器日志
   - 等待 yfinance 限流恢复

2. **价格明显偏高/偏低**
   - 可能是国内金价溢价导致
   - 可指定 `source=yfinance` 使用国际价格

3. **API 返回 404**
   - 确认服务器已启动并运行在正确端口
   - 检查 API 路径是否正确

### 日志查看
```bash
# 查看服务器日志中的黄金价格相关日志
tail -f server.log | grep -i gold
```

## 扩展功能

如需添加新的数据源，请实现相应的获取函数并添加到 `SOURCES` 列表中。

---

**最后更新：** 2026-04-12  
**版本：** 1.0.0