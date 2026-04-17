#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FastAPI Server - ChanLun Analysis API Service"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.staticfiles import StaticFiles
import uvicorn
import json
import typing
import asyncio
from datetime import datetime, date, timezone


class _JSONEncoder(json.JSONEncoder):
    """自定义 JSON 编码器，处理 datetime/Timestamp 类型"""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


class _CustomJSONResponse(JSONResponse):
    """支持 datetime/Timestamp 序列化的 JSONResponse"""
    def render(self, content: typing.Any) -> bytes:
        return json.dumps(content, cls=_JSONEncoder, ensure_ascii=False).encode("utf-8")

# Import project modules
from binance import get_klines
from chanlun_adapter import convert_to_chanlun_bars
from chanlun_local.engine_new import ChanlunEngine, EngineConfig
from astock import get_klines as astock_get_klines
from astock_adapter import convert_to_chanlun_bars as astock_convert_to_chanlun_bars
from gold import get_klines as gold_get_klines
from gold_adapter import convert_to_chanlun_bars as gold_convert_to_chanlun_bars
from gold_realtime import get_realtime_price

app = FastAPI()

# 全局存储分析结果（用于 SSE 流式端点）
analysis_progress = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

web_dir = Path(__file__).parent.parent / "web"


@app.get("/")
async def root():
    return {"service": "ChanLun Analysis API", "version": "1.0.0"}


@app.get("/web")
async def web_index():
    html_file = web_dir / "index.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return {"error": "Web interface not found"}


@app.get("/api/kline/{symbol}/{interval}")
async def get_kline(symbol: str, interval: str, limit: int = 2500):
    try:
        raw_klines = get_klines(symbol, interval, limit)

        if not raw_klines or len(raw_klines) < 3:
            return {"error": "Insufficient data"}

        # Prepare klines in the format expected by ChanlunEngine
        # Engine expects: date, open, high, low, close, volume
        engine_klines = [
            {
                "date": k["open_time"],
                "open": k["open"],
                "high": k["high"],
                "low": k["low"],
                "close": k["close"],
                "volume": 0.0,  # Binance data doesn't include volume in our simplified format
            }
            for k in raw_klines
        ]

        config = EngineConfig()
        engine_wrapper = ChanlunEngine(config)
        icl_result = engine_wrapper.analyze_klines(
            code=symbol,
            frequency=interval,
            klines=engine_klines
        )

        bi_list = icl_result.get_bis()
        xd_list = icl_result.get_xds()
        bi_zs_list = icl_result.get_bi_zss()
        fx_list = icl_result.get_fx_list()

        # Convert to frontend format (o/h/l/c) for the chart
        frontend_bars = convert_to_chanlun_bars(raw_klines)

        result = {
            "meta": {"symbol": symbol, "interval": interval, "count": len(frontend_bars)},
            "klines": frontend_bars,
            "bi": [
                {
                    "index": bi.index,
                    "type": bi.type,
                    "start_price": bi.start_price,
                    "end_price": bi.end_price,
                    "start_date": str(bi.start_time),
                    "end_date": str(bi.end_time),
                    "buy_sell_point": bi.mmds[0].name if bi.mmds and len(bi.mmds) > 0 else None
                }
                for bi in bi_list
            ],
            "xd": [
                {"index": xd.index, "type": xd.type, "start_price": xd.start_price,
                 "end_price": xd.end_price, "start_date": str(xd.start_time),
                 "end_date": str(xd.end_time)}
                for xd in xd_list
            ],
            "zs": [
                {
                    "zg": zs.zg,
                    "zd": zs.zd,
                    "gg": zs.gg,
                    "dd": zs.dd,
                    "start_date": str(zs.start_time),
                    "end_date": str(zs.end_time)
                }
                for zs in bi_zs_list
            ],
            "fx": [
                {"index": fx.index, "type": fx.type, "price": fx.val,
                 "date": str(fx.time)}
                for fx in fx_list
            ]
        }
        return result

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.post("/api/analyze")
async def analyze(request: Request):
    try:
        # Get JSON data from request
        data = await request.json()

        symbol = data.get("symbol")
        interval = data.get("interval")
        mode = data.get("mode", "structured")
        test = data.get("test", False)

        # 新增：从前端获取 AI 配置
        ai_provider = data.get("ai_provider")
        ai_model = data.get("ai_model")
        api_key = data.get("api_key")

        # 区间套钻取上下文（包含父级缠论结构数据）
        drill_context = data.get("drill_context")

        # 多级别区间套分析开关
        enable_multi_level = data.get("enable_multi_level", True)

        if not symbol or not interval:
            return _CustomJSONResponse(content={"error": "Missing symbol or interval"}, status_code=400)

        from api.analyze_service import analyze_chanlun

        # Execute AI analysis (pass test parameter, mode, and AI config)
        result = analyze_chanlun(
            symbol, interval,
            limit=data.get("limit", 2500),
            test_mode=test,
            mode=mode,
            ai_provider=ai_provider,
            ai_model=ai_model,
            api_key=api_key,
            drill_context=drill_context,
            enable_multi_level=enable_multi_level,
        )

        # Use JSONResponse to ensure proper encoding
        return _CustomJSONResponse(content=result)

    except Exception as e:
        import traceback
        return _CustomJSONResponse(content={"error": str(e), "traceback": traceback.format_exc()})


@app.post("/api/analyze/stream")
async def analyze_stream(request: Request):
    """流式分析端点 - SSE（Server-Sent Events）"""
    try:
        data = await request.json()
        symbol = data.get("symbol")
        interval = data.get("interval")
        mode = data.get("mode", "structured")
        test = data.get("test", False)

        if not symbol or not interval:
            return _CustomJSONResponse(content={"error": "Missing symbol or interval"}, status_code=400)

        # 生成唯一任务ID
        task_id = f"{symbol}_{interval}_{int(asyncio.get_event_loop().time() * 1000)}"

        async def event_generator():
            """SSE 事件生成器"""
            try:
                # 导入流式分析模块
                from api.analyze_streaming import analyze_streaming_async

                # 发送开始事件
                yield f"event: start\ndata: {json.dumps({'task_id': task_id}, ensure_ascii=False)}\n\n"

                # 流式执行分析并发送日志
                async for log_event in analyze_streaming_async(symbol, interval, mode, test, task_id):
                    yield f"event: log\ndata: {json.dumps(log_event, ensure_ascii=False)}\n\n"

                # 发送完成事件
                yield f"event: complete\ndata: {json.dumps({'task_id': task_id}, ensure_ascii=False)}\n\n"

            except Exception as e:
                import traceback
                yield f"event: error\ndata: {json.dumps({'error': str(e), 'traceback': traceback.format_exc()}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
            }
        )

    except Exception as e:
        import traceback
        return _CustomJSONResponse(content={"error": str(e), "traceback": traceback.format_exc()})


@app.get("/api/analyze/{task_id}/result")
async def get_analysis_result(task_id: str):
    """获取分析结果（用于 SSE 完成后获取最终结果）"""
    # 从流式模块获取存储
    from api.analyze_streaming import get_analysis_progress
    progress_storage = get_analysis_progress()
    if task_id in progress_storage:
        result = progress_storage[task_id]
        # 可选：返回后删除以节省内存
        # del progress_storage[task_id]
        return result
    return {"error": "Task not found"}


# ─── A 股端点（独立于 Binance，不影响现有功能）────────────────────────────

@app.get("/api/astock/kline/{symbol}/{interval}")
async def get_astock_kline(symbol: str, interval: str, limit: int = 500):
    try:
        raw_klines = astock_get_klines(symbol, interval, limit)

        if not raw_klines or len(raw_klines) < 3:
            return {"error": "Insufficient A-stock data"}

        engine_klines = [
            {
                "date": k["open_time"],
                "open": k["open"],
                "high": k["high"],
                "low": k["low"],
                "close": k["close"],
                "volume": k.get("volume", 0),
            }
            for k in raw_klines
        ]

        config = EngineConfig()
        engine_wrapper = ChanlunEngine(config)
        icl_result = engine_wrapper.analyze_klines(
            code=symbol,
            frequency=interval,
            klines=engine_klines
        )

        bi_list = icl_result.get_bis()
        xd_list = icl_result.get_xds()
        bi_zs_list = icl_result.get_bi_zss()
        fx_list = icl_result.get_fx_list()

        frontend_bars = astock_convert_to_chanlun_bars(raw_klines)

        result = {
            "meta": {"symbol": symbol, "interval": interval, "count": len(frontend_bars), "market": "astock"},
            "klines": frontend_bars,
            "bi": [
                {
                    "index": bi.index,
                    "type": bi.type,
                    "start_price": bi.start_price,
                    "end_price": bi.end_price,
                    "start_date": str(bi.start_time),
                    "end_date": str(bi.end_time),
                    "buy_sell_point": bi.mmds[0].name if bi.mmds and len(bi.mmds) > 0 else None
                }
                for bi in bi_list
            ],
            "xd": [
                {"index": xd.index, "type": xd.type, "start_price": xd.start_price,
                 "end_price": xd.end_price, "start_date": str(xd.start_time),
                 "end_date": str(xd.end_time)}
                for xd in xd_list
            ],
            "zs": [
                {
                    "zg": zs.zg,
                    "zd": zs.zd,
                    "gg": zs.gg,
                    "dd": zs.dd,
                    "start_date": str(zs.start_time),
                    "end_date": str(zs.end_time)
                }
                for zs in bi_zs_list
            ],
            "fx": [
                {"index": fx.index, "type": fx.type, "price": fx.val,
                 "date": str(fx.time)}
                for fx in fx_list
            ]
        }
        return result

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.post("/api/astock/analyze")
async def analyze_astock(request: Request):
    try:
        data = await request.json()

        symbol = data.get("symbol")
        interval = data.get("interval")
        mode = data.get("mode", "structured")
        test = data.get("test", False)
        ai_provider = data.get("ai_provider")
        ai_model = data.get("ai_model")
        api_key = data.get("api_key")
        drill_context = data.get("drill_context")

        if not symbol or not interval:
            return _CustomJSONResponse(content={"error": "Missing symbol or interval"}, status_code=400)

        from api.astock_analyze_service import analyze_astock_chanlun

        result = analyze_astock_chanlun(
            symbol, interval,
            limit=500,
            test_mode=test,
            mode=mode,
            ai_provider=ai_provider,
            ai_model=ai_model,
            api_key=api_key,
            drill_context=drill_context,
        )

        return _CustomJSONResponse(content=result)

    except Exception as e:
        import traceback
        return _CustomJSONResponse(content={"error": str(e), "traceback": traceback.format_exc()})


# ─── 黄金端点（XAUUSD）────────────────────────────────────────────

@app.get("/api/gold/price")
async def get_gold_price(source: str = None):
    """获取黄金实时价格"""
    try:
        result = get_realtime_price(preferred_source=source)
        return result
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.get("/api/gold/kline/{interval}")
async def get_gold_kline(interval: str, limit: int = 500):
    """获取黄金历史K线数据"""
    try:
        raw_klines = gold_get_klines(interval=interval, limit=limit)

        if not raw_klines or len(raw_klines) < 3:
            return {"error": "Insufficient gold data"}

        engine_klines = [
            {
                "date": k["open_time"],
                "open": k["open"],
                "high": k["high"],
                "low": k["low"],
                "close": k["close"],
                "volume": 0.0,
            }
            for k in raw_klines
        ]

        config = EngineConfig()
        engine_wrapper = ChanlunEngine(config)
        icl_result = engine_wrapper.analyze_klines(
            code="XAUUSD",
            frequency=interval,
            klines=engine_klines
        )

        bi_list = icl_result.get_bis()
        xd_list = icl_result.get_xds()
        bi_zs_list = icl_result.get_bi_zss()
        fx_list = icl_result.get_fx_list()

        frontend_bars = gold_convert_to_chanlun_bars(raw_klines)

        result = {
            "meta": {"symbol": "XAUUSD", "interval": interval, "count": len(frontend_bars), "market": "gold"},
            "klines": frontend_bars,
            "bi": [
                {
                    "index": bi.index,
                    "type": bi.type,
                    "start_price": bi.start_price,
                    "end_price": bi.end_price,
                    "start_date": str(bi.start_time),
                    "end_date": str(bi.end_time),
                    "buy_sell_point": bi.mmds[0].name if bi.mmds and len(bi.mmds) > 0 else None
                }
                for bi in bi_list
            ],
            "xd": [
                {"index": xd.index, "type": xd.type, "start_price": xd.start_price,
                 "end_price": xd.end_price, "start_date": str(xd.start_time),
                 "end_date": str(xd.end_time)}
                for xd in xd_list
            ],
            "zs": [
                {
                    "zg": zs.zg,
                    "zd": zs.zd,
                    "gg": zs.gg,
                    "dd": zs.dd,
                    "start_date": str(zs.start_time),
                    "end_date": str(zs.end_time)
                }
                for zs in bi_zs_list
            ],
            "fx": [
                {"index": fx.index, "type": fx.type, "price": fx.val,
                 "date": str(fx.time)}
                for fx in fx_list
            ]
        }
        return result

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.post("/api/gold/analyze")
async def analyze_gold(request: Request):
    try:
        data = await request.json()
        symbol = data.get("symbol", "XAUUSD")
        interval = data.get("interval")
        mode = data.get("mode", "structured")
        test = data.get("test", False)
        ai_provider = data.get("ai_provider")
        ai_model = data.get("ai_model")
        api_key = data.get("api_key")

        if not interval:
            return _CustomJSONResponse(content={"error": "Missing interval"}, status_code=400)

        # 模拟 AI 分析结果（开发中）
        import time
        result = {
            "primary_scenario": {
                "direction": "range",
                "probability": 0.65,
                "entry_zone": [2300, 2350],
                "targets": [2400, 2450],
                "stop_loss": 2250,
                "valid_until": int(time.time()) + 86400,
                "confidence": "medium",
                "reasoning": "黄金目前处于震荡区间，等待突破方向。"
            },
            "alternative_scenarios": [
                {
                    "direction": "up",
                    "probability": 0.25,
                    "entry_zone": [2350, 2380],
                    "targets": [2450, 2500],
                    "stop_loss": 2300,
                    "valid_until": int(time.time()) + 86400,
                    "confidence": "low",
                    "reasoning": "若突破阻力位，可能开启上涨趋势。"
                },
                {
                    "direction": "down",
                    "probability": 0.10,
                    "entry_zone": [2280, 2300],
                    "targets": [2200, 2250],
                    "stop_loss": 2350,
                    "valid_until": int(time.time()) + 86400,
                    "confidence": "low",
                    "reasoning": "若跌破支撑位，可能继续下行。"
                }
            ],
            "market_context": {
                "trend": "range",
                "volatility": "medium",
                "sentiment": "neutral"
            },
            "risk_notes": ["黄金受美元指数影响较大，注意晚间美国数据公布"],
            "version": "2.0",
            "output_mode": "scenarios"
        }
        return _CustomJSONResponse(content=result)

    except Exception as e:
        import traceback
        return _CustomJSONResponse(content={"error": str(e), "traceback": traceback.format_exc()})

# ─── 区间套钻取：带时间范围的 K 线查询端点 ───────────────────────────

def _run_chanlun_analysis(engine_klines: list, code: str, frequency: str):
    """通用缠论分析：输入 engine 格式 K 线，返回 (bi_list, xd_list, bi_zs_list, fx_list)"""
    config = EngineConfig()
    engine_wrapper = ChanlunEngine(config)
    icl_result = engine_wrapper.analyze_klines(
        code=code,
        frequency=frequency,
        klines=engine_klines
    )
    return (
        icl_result.get_bis(),
        icl_result.get_xds(),
        icl_result.get_bi_zss(),
        icl_result.get_fx_list(),
    )


def _build_chanlun_result(bi_list, xd_list, bi_zs_list, fx_list, frontend_bars, symbol: str, interval: str, market: str = "crypto"):
    """通用结果格式化"""
    return {
        "meta": {"symbol": symbol, "interval": interval, "count": len(frontend_bars), "market": market},
        "klines": frontend_bars,
        "bi": [
            {
                "index": bi.index, "type": bi.type,
                "start_price": bi.start_price, "end_price": bi.end_price,
                "start_date": str(bi.start_time), "end_date": str(bi.end_time),
                "buy_sell_point": bi.mmds[0].name if bi.mmds and len(bi.mmds) > 0 else None
            }
            for bi in bi_list
        ],
        "xd": [
            {
                "index": xd.index, "type": xd.type,
                "start_price": xd.start_price, "end_price": xd.end_price,
                "start_date": str(xd.start_time), "end_date": str(xd.end_time)
            }
            for xd in xd_list
        ],
        "zs": [
            {
                "zg": zs.zg, "zd": zs.zd, "gg": zs.gg, "dd": zs.dd,
                "start_date": str(zs.start_time), "end_date": str(zs.end_time)
            }
            for zs in bi_zs_list
        ],
        "fx": [
            {"index": fx.index, "type": fx.type, "price": fx.val, "date": str(fx.time)}
            for fx in fx_list
        ]
    }


def _filter_by_time_range(raw_klines: list, start_time_ms: int, end_time_ms: int):
    """按时间范围（毫秒时间戳）过滤 K 线数据，保留 start_time >= start_time_ms 且 open_time <= end_time_ms 的记录"""
    start_dt = datetime.fromtimestamp(start_time_ms / 1000.0, tz=timezone.utc) if start_time_ms else None
    end_dt = datetime.fromtimestamp(end_time_ms / 1000.0, tz=timezone.utc) if end_time_ms else None
    filtered = raw_klines
    if start_dt:
        filtered = [k for k in filtered if k["open_time"] >= start_dt]
    if end_dt:
        filtered = [k for k in filtered if k["open_time"] <= end_dt]
    return filtered


@app.get("/api/kline/{symbol}/{interval}/range")
async def get_kline_range(symbol: str, interval: str, start_time: int, end_time: int):
    """加密货币 K 线时间范围查询（区间套钻取用）"""
    try:
        raw_klines = get_klines(symbol, interval, 1000, start_time=start_time)
        if not raw_klines or len(raw_klines) < 3:
            return {"error": "Insufficient data in range"}

        raw_klines = _filter_by_time_range(raw_klines, start_time, end_time)
        if len(raw_klines) < 3:
            return {"error": "Insufficient data after filtering"}

        engine_klines = [
            {"date": k["open_time"], "open": k["open"], "high": k["high"],
             "low": k["low"], "close": k["close"], "volume": 0.0}
            for k in raw_klines
        ]
        bi_list, xd_list, bi_zs_list, fx_list = _run_chanlun_analysis(engine_klines, symbol, interval)
        frontend_bars = convert_to_chanlun_bars(raw_klines)
        return _build_chanlun_result(bi_list, xd_list, bi_zs_list, fx_list, frontend_bars, symbol, interval)
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.get("/api/astock/kline/{symbol}/{interval}/range")
async def get_astock_kline_range(symbol: str, interval: str, start_time: int, end_time: int):
    """A 股 K 线时间范围查询（区间套钻取用）"""
    try:
        raw_klines = astock_get_klines(symbol, interval, 1000)
        if not raw_klines or len(raw_klines) < 3:
            return {"error": "Insufficient A-stock data"}

        raw_klines = _filter_by_time_range(raw_klines, start_time, end_time)
        if len(raw_klines) < 3:
            return {"error": "Insufficient A-stock data in range"}

        engine_klines = [
            {"date": k["open_time"], "open": k["open"], "high": k["high"],
             "low": k["low"], "close": k["close"], "volume": k.get("volume", 0)}
            for k in raw_klines
        ]
        bi_list, xd_list, bi_zs_list, fx_list = _run_chanlun_analysis(engine_klines, symbol, interval)
        frontend_bars = astock_convert_to_chanlun_bars(raw_klines)
        return _build_chanlun_result(bi_list, xd_list, bi_zs_list, fx_list, frontend_bars, symbol, interval, "astock")
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.get("/api/gold/kline/{interval}/range")
async def get_gold_kline_range(interval: str, start_time: int, end_time: int):
    """黄金 K 线时间范围查询（区间套钻取用）"""
    try:
        raw_klines = gold_get_klines(interval=interval, limit=1000)
        if not raw_klines or len(raw_klines) < 3:
            return {"error": "Insufficient gold data"}

        raw_klines = _filter_by_time_range(raw_klines, start_time, end_time)
        if len(raw_klines) < 3:
            return {"error": "Insufficient gold data in range"}

        engine_klines = [
            {"date": k["open_time"], "open": k["open"], "high": k["high"],
             "low": k["low"], "close": k["close"], "volume": 0.0}
            for k in raw_klines
        ]
        bi_list, xd_list, bi_zs_list, fx_list = _run_chanlun_analysis(engine_klines, "XAUUSD", interval)
        frontend_bars = gold_convert_to_chanlun_bars(raw_klines)
        return _build_chanlun_result(bi_list, xd_list, bi_zs_list, fx_list, frontend_bars, "XAUUSD", interval, "gold")
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")


if __name__ == "__main__":
    print("Starting ChanLun Analysis API Server...")
    print("API: http://0.0.0.0:8001")
    print("Web: http://0.0.0.0:8001/web")
    uvicorn.run(app, host="0.0.0.0", port=8003)
