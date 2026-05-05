#!/usr/bin/env python3
import os
from pathlib import Path
from dotenv import load_dotenv

# 清除 NO_PROXY
if os.getenv('NO_PROXY') == '*':
    os.environ.pop('NO_PROXY', None)
if os.getenv('no_proxy') == '*':
    os.environ.pop('no_proxy', None)

# 加载 .env
env_path = Path('.') / '.env'
load_dotenv(env_path, override=True)

# 导入并测试
from binance import get_klines
print('正在获取 Binance K线数据...')
klines = get_klines('BTCUSDT', '1h', 50)
print(f'成功获取 {len(klines)} 根K线')
print(f'第一根: {klines[0]}')
print(f'最后一根: {klines[-1]}')
