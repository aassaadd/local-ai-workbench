"""本地大模型适配器（oMLX / OpenAI 兼容接口）。

未配置 OMLX_BASE_URL 或请求失败时返回 None，由协调员回退到内置规则引擎，
保证「纯本地、开箱即用」，不影响整体流程。
"""
import asyncio
import json
from typing import List, Optional

import requests

from . import config


def _post_chat(messages: List[dict], temperature: float) -> str:
    url = config.OMLX_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if config.OMLX_API_KEY:
        headers["Authorization"] = f"Bearer {config.OMLX_API_KEY}"
    payload = {
        "model": config.OMLX_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload),
                         timeout=config.LLM_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


async def chat(messages: List[dict], temperature: float = 0.3) -> Optional[str]:
    if not config.OMLX_BASE_URL:
        return None
    try:
        return await asyncio.to_thread(_post_chat, messages, temperature)
    except Exception:
        return None


def available() -> bool:
    return bool(config.OMLX_BASE_URL)
