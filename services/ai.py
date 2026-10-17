"""DeepSeek 调用封装。全站只有"温柔传话"会用到这里。

- 真正发请求的只有 _chat() 一个函数，测试时用 monkeypatch 把它换掉，不会真的调用 API
- API key 由调用方从数据库读出来传进来；这里不读取环境变量里的任何 key
- 日志只记录"做了什么、结果类型、耗时"，不记录任何聊天内容
"""

import time
from dataclasses import dataclass

import openai
from flask import current_app
from openai import OpenAI

from services.prompts import KEY_TEST_MESSAGE, SOFTEN_SYSTEM_PROMPT

BASE_URL = "https://api.deepseek.com"

MAX_ORIGINAL_LENGTH = 500  # 原话最长 500 字

# 结果类型（前端按它显示不同的提示）
OK = "ok"
UNSAFE = "unsafe"  # 模型判断原话有安全风险：不发送，显示安全卡片
INVALID_KEY = "invalid_key"  # 401：key 不正确
NO_BALANCE = "no_balance"  # 402：余额不足
NETWORK = "network"  # 超时 / 网络不通
RATE_LIMITED = "rate_limited"  # 429：请求太频繁
ERROR = "error"  # 其他错误（包括模型返回空内容）


@dataclass
class SoftenResult:
    status: str
    text: str = ""


def _chat(api_key, messages, max_tokens, temperature):
    """调用 DeepSeek 的唯一入口，返回模型回复的文字。出错时抛出 openai 的异常。"""
    client = OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        timeout=current_app.config["AI_TIMEOUT"],
        max_retries=0,  # 不自动重试，失败就直接告诉用户
    )
    response = client.chat.completions.create(
        model=current_app.config["DEEPSEEK_MODEL"],
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


def classify_error(exc):
    """把异常归类成上面的结果类型。"""
    # 超时也属于连接错误（APITimeoutError 是 APIConnectionError 的子类）
    if isinstance(exc, (openai.APIConnectionError, TimeoutError, ConnectionError)):
        return NETWORK
    status = getattr(exc, "status_code", None)
    if status == 401:
        return INVALID_KEY
    if status == 402:
        return NO_BALANCE
    if status == 429:
        return RATE_LIMITED
    return ERROR


def _log(action, result, started):
    """只记录结果类型和耗时，不记录内容。"""
    ms = int((time.monotonic() - started) * 1000)
    current_app.logger.info("deepseek %s result=%s ms=%d", action, result, ms)


def check_key(api_key):
    """用一个极小的请求测试 key 是否可用，返回结果类型（OK 表示可用）。"""
    started = time.monotonic()
    try:
        _chat(api_key, [{"role": "user", "content": KEY_TEST_MESSAGE}], max_tokens=5, temperature=0)
        result = OK
    except Exception as exc:  # noqa: BLE001 —— 任何错误都要转成友好提示，不能让页面报 500
        result = classify_error(exc)
    _log("key_test", result, started)
    return result


# 模型偶尔会给整句话加上引号，去掉成对的引号
_QUOTE_PAIRS = [('"', '"'), ("“", "”"), ("「", "」"), ("『", "』"), ("'", "'"), ("‘", "’")]


def parse_soften_output(raw):
    """解析模型的回复：
    - 含有 [UNSAFE] → UNSAFE（不发送）
    - 去掉首尾空白和成对引号；结果为空 → ERROR
    - 否则 → OK + 改写后的文字"""
    text = (raw or "").strip()
    if "[UNSAFE]" in text.upper():
        return SoftenResult(UNSAFE)
    for left, right in _QUOTE_PAIRS:
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            text = text[1:-1].strip()
            break
    if not text:
        return SoftenResult(ERROR)
    return SoftenResult(OK, text)


def soften(api_key, original):
    """把原话改写成更温柔的说法，返回 SoftenResult。"""
    started = time.monotonic()
    try:
        raw = _chat(
            api_key,
            [
                {"role": "system", "content": SOFTEN_SYSTEM_PROMPT},
                {"role": "user", "content": original},
            ],
            max_tokens=300,
            temperature=0.7,
        )
        result = parse_soften_output(raw)
    except Exception as exc:  # noqa: BLE001
        result = SoftenResult(classify_error(exc))
    _log("soften", result.status, started)
    return result
