#!/usr/bin/env python3
"""测试腾讯云 DeepSeek API 连接"""

import os
from dotenv import load_dotenv
import requests

# 加载环境变量
load_dotenv()

api_key = os.getenv("DEEPSEEK_API_KEY")
base_url = os.getenv("DEEPSEEK_BASE_URL")
model = os.getenv("AI_MODEL", "deepseek-chat")

print("🔍 检查配置:")
print(f"  API Key: {api_key[:20]}..." if api_key else "  ❌ API Key 未配置")
print(f"  Base URL: {base_url}" if base_url else "  ❌ Base URL 未配置")
print(f"  Model: {model}")
print()

if not api_key or not base_url:
    print("❌ 配置不完整，请检查 .env 文件")
    exit(1)

# 测试API连接
print("📡 测试 API 连接...")

url = base_url.rstrip("/") + "/chat/completions"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

payload = {
    "model": model,
    "messages": [
        {"role": "user", "content": "你好，请简单回复一下"}
    ],
    "max_tokens": 50
}

try:
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    print(f"  状态码: {response.status_code}")

    if response.ok:
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"  ✅ API 连接成功！")
        print(f"  回复: {content[:100]}...")
    else:
        print(f"  ❌ API 调用失败")
        print(f"  响应: {response.text[:200]}")
except Exception as e:
    print(f"  ❌ 连接失败: {e}")
