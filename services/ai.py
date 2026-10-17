"""DeepSeek 调用封装。全站只有"温柔传话"会用到这里。

- 真正发请求的只有 _chat() 一个函数，测试时用 monkeypatch 把它换掉，不会真的调用 API
- API key 由调用方从数据库读出来传进来；这里不读取环境变量里的任何 key
- 日志只记录"做了什么、结果类型、耗时"，不记录任何聊天内容
"""

import json
import re
import time
from dataclasses import dataclass

import openai
from flask import current_app
from openai import OpenAI

from services.prompts import (
    KEY_TEST_MESSAGE,
    SOFTEN_EXAMPLES,
    SOFTEN_RETRY_REMINDER,
    SOFTEN_SYSTEM_PROMPT,
    example_answer,
    soften_user_message,
)

BASE_URL = "https://api.deepseek.com"

MAX_ORIGINAL_LENGTH = 500  # 原话最长 500 字
SOFTEN_TEMPERATURE = 0.3  # 改写要稳定：同一句话每次改出来差不多（0.7 时差别太大）

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


def _chat(api_key, messages, max_tokens, temperature, json_mode=False):
    """调用 DeepSeek 的唯一入口，返回模型回复的文字。出错时抛出 openai 的异常。
    json_mode=True 时要求模型只输出一个 JSON 对象（温柔传话用）。"""
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
        **({"response_format": {"type": "json_object"}} if json_mode else {}),
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
_OPEN_QUOTES = "\"“「『'‘"
# 模型偶尔会加的前缀，例如"改写后：""温柔版：""Rewritten:"
_PREFIX = re.compile(r"^(改写后?|优化后?|温柔版本?|传话)\s*[:：]\s*|^(rewritten|softened)( version)?\s*:\s*", re.I)
_CJK = re.compile(r"[\u3400-\u9fff]")
# 站在被说的人的角度、在回应对方说过的话，例如"你这样说让我有点难受""听到你这么说"
_REPLY_ZH = re.compile(r"你(这样|这么|那样|那么)?说|你说(的|了|过)?(这|那)?(话|句)|听(到|见)?你(这样|这么|那样)?说|你的话|这(句)?话让我|被你(说|骂|嫌)")
_REPLY_EN = re.compile(r"\b(when|that) you (say|said)\b|\byou said\b|\bhearing you\b|\byour words\b", re.I)
_MENTIONS_SPEECH = re.compile(r"说|话|讲|骂|\b(say|said|tell|told|words?)\b", re.I)
_LATIN = re.compile(r"[A-Za-z]")


def detect_lang(text):
    """原话的语言：有汉字 → "zh"；没有汉字但有英文字母 → "en"；只有数字、符号、表情 → None（不限制）。"""
    if _CJK.search(text or ""):
        return "zh"
    if _LATIN.search(text or ""):
        return "en"
    return None


def problem_with(original, softened, lang):
    """检查改写结果有没有已知的毛病，返回原因（日志用，不含内容），没有问题返回 None：
    - wrong_lang：中文原话改成了英文，或英文原话改成了中文
    - echo：在改写里引用了原话（通常是站在被说的人的角度回应，例如"你说'你是头猪'的时候……"）
    - reply：人称反了，在回应对方说过的话（例如原话"你好丑"被改成"你这样说让我有点难受"）。
      原话本身提到"说 / 话"时不检查（例如"你说过会早点回来"），避免误判"""
    if lang == "zh" and not _CJK.search(softened):
        return "wrong_lang"
    if lang == "en" and _CJK.search(softened):
        return "wrong_lang"
    core = original.strip().rstrip("。！？!?.~～ ")
    if len(core) >= 3 and any(q + core in softened for q in _OPEN_QUOTES):
        return "echo"
    if not _MENTIONS_SPEECH.search(original) and (_REPLY_ZH.search(softened) or _REPLY_EN.search(softened)):
        return "reply"
    return None


def _from_json(text):
    """模型按要求输出 JSON：{"speaker_feeling": ..., "rewrite": ...} 或 {"unsafe": true}。
    返回 ("unsafe", None) / ("rewrite", 文字) / (None, None)（不是 JSON，按普通文字处理）。"""
    try:
        data = json.loads(text)
    except ValueError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    if data.get("unsafe") is True:
        return "unsafe", None
    rewrite = data.get("rewrite")
    return "rewrite", rewrite if isinstance(rewrite, str) else ""


def parse_soften_output(raw):
    """解析模型的回复：
    - JSON {"unsafe": true}，或任何位置含有 [UNSAFE] → UNSAFE（不发送）
    - JSON 里的 rewrite 字段就是改写（speaker_feeling 只是让模型先想清楚，不给用户看）；
      不是 JSON 时把整段当成改写（兼容）
    - 去掉首尾空白、前缀、标签和成对引号；结果为空 → ERROR
    - 否则 → OK + 改写后的文字"""
    text = (raw or "").strip()
    if "[UNSAFE]" in text.upper():
        return SoftenResult(UNSAFE)
    kind, rewrite = _from_json(text)
    if kind == "unsafe":
        return SoftenResult(UNSAFE)
    if kind == "rewrite":
        text = rewrite.strip()
    text = text.replace("<原话>", "").replace("</原话>", "").strip()  # 偶尔把标签也抄出来
    text = _PREFIX.sub("", text).strip()
    for left, right in _QUOTE_PAIRS:
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            text = text[1:-1].strip()
            break
    if not text:
        return SoftenResult(ERROR)
    return SoftenResult(OK, text)


def soften_messages(original, retry=False):
    """发给模型的完整消息：系统提示词 + 示例对话 + 用标签包好的原话（写明输出语言）。
    示例里助手的回答是 JSON：先写说话的人的情绪，再写改写。"""
    messages = [{"role": "system", "content": SOFTEN_SYSTEM_PROMPT}]
    for example, feeling, rewritten in SOFTEN_EXAMPLES:
        messages.append({"role": "user", "content": soften_user_message(example, detect_lang(example))})
        messages.append({"role": "assistant", "content": example_answer(feeling, rewritten)})
    content = soften_user_message(original, detect_lang(original))
    if retry:
        content += SOFTEN_RETRY_REMINDER
    messages.append({"role": "user", "content": content})
    return messages


def soften(api_key, original):
    """把原话改写成更温柔的说法，返回 SoftenResult。
    模型先写说话的人的情绪、再写改写（JSON），人称不容易反；
    结果语言不对、人称反了、或者引用了原话时自动重试一次（加一句提醒）；
    第二次还是这样就返回 ERROR，让用户再试或直接发送，不把错误的改写给用户。"""
    started = time.monotonic()
    lang = detect_lang(original)
    result = SoftenResult(ERROR)
    for attempt in range(2):
        try:
            raw = _chat(api_key, soften_messages(original, retry=attempt > 0),
                        max_tokens=400, temperature=SOFTEN_TEMPERATURE, json_mode=True)
        except Exception as exc:  # noqa: BLE001
            result = SoftenResult(classify_error(exc))
            break
        result = parse_soften_output(raw)
        if result.status != OK:
            break
        problem = problem_with(original, result.text, lang)
        if problem is None:
            break
        # 只记录原因，不记录内容
        current_app.logger.info("deepseek soften retry reason=%s attempt=%d", problem, attempt + 1)
        result = SoftenResult(ERROR)
    _log("soften", result.status, started)
    return result
