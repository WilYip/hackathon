"""中英文切换（i18n）。

- 界面文字放在 i18n/zh.json 和 i18n/en.json，键可以用点号分层，例如 t('welcome.title')
- 内容数据（任务、动物等）使用 {"zh": ..., "en": ...} 结构，用 tr(obj) 取当前语言
- 当前语言的来源：登录用户的数据库偏好（M2 起）> Cookie > 默认中文
"""

import json
from pathlib import Path

from flask import g, request

SUPPORTED_LANGS = ("zh", "en")
DEFAULT_LANG = "zh"
LANG_COOKIE = "lang"

I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"

# 启动时把两份语言文件读入内存
_translations = {}


def load_translations():
    for lang in SUPPORTED_LANGS:
        path = I18N_DIR / f"{lang}.json"
        _translations[lang] = json.loads(path.read_text(encoding="utf-8"))


def _lookup(data, key):
    """按 'a.b.c' 逐层查找，找不到返回 None。"""
    for part in key.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data if isinstance(data, str) else None


def get_lang():
    """当前请求使用的语言。"""
    # M2 之后：登录用户的语言偏好会在 before_request 中写入 g.user_lang
    user_lang = g.get("user_lang")
    if user_lang in SUPPORTED_LANGS:
        return user_lang
    cookie_lang = request.cookies.get(LANG_COOKIE)
    if cookie_lang in SUPPORTED_LANGS:
        return cookie_lang
    return DEFAULT_LANG


def t(key, **kwargs):
    """取界面文字。找不到时先退回中文，再退回键名本身（方便发现漏翻译）。
    支持占位符：t('hello', name='小雨') 对应 "你好，{name}"。"""
    lang = get_lang()
    text = _lookup(_translations.get(lang, {}), key)
    if text is None:
        text = _lookup(_translations.get(DEFAULT_LANG, {}), key)
    if text is None:
        return key
    return text.format(**kwargs) if kwargs else text


def tr(obj):
    """从 {"zh": ..., "en": ...} 里取出当前语言的内容。"""
    if isinstance(obj, dict):
        return obj.get(get_lang()) or obj.get(DEFAULT_LANG) or ""
    return obj


def format_date(dt):
    """按语言格式化日期：中文 2026年10月16日，英文 16 Oct 2026。"""
    if dt is None:
        return ""
    if get_lang() == "zh":
        return f"{dt.year}年{dt.month}月{dt.day}日"
    return f"{dt.day} {dt.strftime('%b')} {dt.year}"


def init_app(app):
    """注册到 Flask：模板中可以直接使用 t()、tr()、lang 和 format_date 过滤器。"""
    load_translations()
    app.jinja_env.globals["t"] = t
    app.jinja_env.globals["tr"] = tr
    app.jinja_env.filters["format_date"] = format_date

    @app.context_processor
    def inject_lang():
        return {"lang": get_lang()}
