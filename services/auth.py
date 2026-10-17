"""账号相关的工具函数：读取小岛和成员、登录状态、邀请码、PIN 锁定、
修改 PIN、忘记 PIN 的重置码、重建自己的角色。

其他功能（温柔传话、约会选选选……）需要"必须登录"时：
    from services.auth import login_required
    @bp.get("/xxx")
    @login_required
    def xxx(): ...
登录后，当前成员在 g.user，小岛在 g.island。
"""

import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import g, jsonify, redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db

MAX_MEMBERS = 2
MAX_FAILED_ATTEMPTS = 5  # PIN 连续错误 5 次……
LOCK_MINUTES = 5  # ……锁定 5 分钟

# 邀请码字符：大写字母 + 数字，去掉容易看错的 0 / O / 1 / I
INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
INVITE_LENGTH = 6

# 忘记 PIN：另一半生成的重置码，8 位（字符和邀请码一样），30 分钟内有效，用一次就作废
RESET_CODE_LENGTH = 8
RESET_CODE_MINUTES = 30

PIN_PATTERN = re.compile(r"^\d{4,6}$")
ISLAND_NAME_MAX = 30
NICKNAME_MAX = 20


# ---------- 读取数据 ----------


def get_island():
    """返回小岛（没有则返回 None）。一个实例最多只有一座小岛，id 固定为 1。"""
    return get_db().execute("SELECT * FROM island WHERE id = 1").fetchone()


def get_members():
    """按加入顺序返回所有成员（最多两人）。"""
    return get_db().execute("SELECT * FROM members ORDER BY id").fetchall()


def get_member(member_id):
    return get_db().execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()


def get_partner(member_id):
    """返回另一半（还没加入时返回 None）。"""
    return get_db().execute("SELECT * FROM members WHERE id != ? ORDER BY id LIMIT 1", (member_id,)).fetchone()


# ---------- 邀请码与校验 ----------


def generate_invite_code():
    """生成 6 位邀请码，例如 K7MPQ2。使用 secrets 保证随机性足够安全。"""
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))


def normalize_invite_code(code):
    """用户输入的邀请码：去掉空格和横线，转成大写。"""
    return re.sub(r"[\s-]", "", code or "").upper()


def is_valid_pin(pin):
    return bool(PIN_PATTERN.match(pin or ""))


def hash_pin(pin):
    return generate_password_hash(pin)


# ---------- 登录状态 ----------


def load_current_user():
    """每个请求开始时调用：根据 session 读取当前登录成员，放到 g.user。"""
    g.user = None
    g.island = None
    member_id = session.get("member_id")
    if member_id is not None:
        member = get_member(member_id)
        if member is None:
            # 成员已不存在（例如数据库被重置），清掉旧的登录状态
            session.clear()
        else:
            g.user = member
            g.island = get_island()
            # 登录用户的语言偏好优先于 Cookie
            g.user_lang = member["lang"]


def log_in(member_id):
    """登录：先清空旧 session（防止会话固定攻击），再记录成员 id。"""
    session.clear()
    session["member_id"] = member_id
    session.permanent = True  # 关掉浏览器后仍保持登录（有效期见 config.py）


def log_out():
    session.clear()


def login_required(view):
    """装饰器：未登录时跳转到首页（首页会再引导到登录/创建页）。"""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("island.index"))
        return view(*args, **kwargs)

    return wrapped


def api_login_required(view):
    """给 /api/ 接口用的装饰器：未登录时返回 401 JSON（而不是跳转到网页）。"""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return jsonify({"error": "login_required"}), 401
        return view(*args, **kwargs)

    return wrapped


# ---------- PIN 错误锁定 ----------


def _now():
    return datetime.now(timezone.utc)


def locked_minutes_left(member):
    """如果该成员被锁定，返回还剩几分钟（向上取整）；没锁定返回 0。"""
    if not member["locked_until"]:
        return 0
    until = datetime.fromisoformat(member["locked_until"])
    seconds = (until - _now()).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 60) + (1 if seconds % 60 else 0)


def check_pin(member, pin):
    """校验 PIN 并处理锁定计数。
    返回 ("ok", 0) / ("locked", 剩余分钟) / ("wrong", 剩余可尝试次数)。"""
    return _check_secret(member, lambda: check_password_hash(member["pin_hash"], pin or ""))


def _check_secret(member, is_correct):
    """PIN 和重置码共用的锁定计数：连续错 5 次锁 5 分钟。is_correct 是一个返回 True / False 的函数。"""
    db = get_db()

    minutes = locked_minutes_left(member)
    if minutes:
        return "locked", minutes

    if is_correct():
        db.execute("UPDATE members SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (member["id"],))
        db.commit()
        return "ok", 0

    # 锁定时计数已清零，所以锁定过期后会重新从 0 开始数
    failed = member["failed_attempts"] + 1
    if failed >= MAX_FAILED_ATTEMPTS:
        until = (_now() + timedelta(minutes=LOCK_MINUTES)).isoformat()
        db.execute("UPDATE members SET failed_attempts = 0, locked_until = ? WHERE id = ?", (until, member["id"]))
        db.commit()
        return "locked", LOCK_MINUTES

    db.execute("UPDATE members SET failed_attempts = ?, locked_until = NULL WHERE id = ?", (failed, member["id"]))
    db.commit()
    return "wrong", MAX_FAILED_ATTEMPTS - failed


# ---------- 修改 PIN / 忘记 PIN ----------


def set_pin(member_id, pin):
    """把 PIN 换成新的：同时清掉错误计数、锁定和没用过的重置码。"""
    db = get_db()
    db.execute(
        "UPDATE members SET pin_hash = ?, failed_attempts = 0, locked_until = NULL, "
        "reset_code_hash = NULL, reset_code_expires = NULL WHERE id = ?",
        (hash_pin(pin), member_id),
    )
    db.commit()


def create_reset_code(target_id):
    """另一半忘记了 PIN：为 TA 生成一次性重置码（30 分钟有效）。
    数据库里只存哈希；再生成一次时旧的码作废。返回 (重置码, 过期时间)。"""
    code = "".join(secrets.choice(INVITE_ALPHABET) for _ in range(RESET_CODE_LENGTH))
    expires = _now() + timedelta(minutes=RESET_CODE_MINUTES)
    db = get_db()
    db.execute(
        "UPDATE members SET reset_code_hash = ?, reset_code_expires = ? WHERE id = ?",
        (generate_password_hash(code), expires.isoformat(), target_id),
    )
    db.commit()
    return code, expires


def has_valid_reset_code(member):
    """这位成员有没有还没过期的重置码。"""
    if not member["reset_code_hash"] or not member["reset_code_expires"]:
        return False
    return datetime.fromisoformat(member["reset_code_expires"]) > _now()


def check_reset_code(member, code):
    """用重置码设置新 PIN 之前的校验，和 PIN 一样计入错误次数和锁定。
    返回 ("ok", 0) / ("none", 0) 没有可用的码 / ("locked", 剩余分钟) / ("wrong", 剩余可尝试次数)。"""
    if not has_valid_reset_code(member):
        return "none", 0
    code = normalize_invite_code(code)  # 和邀请码一样：忽略空格、横线和大小写
    return _check_secret(member, lambda: check_password_hash(member["reset_code_hash"], code))


# ---------- 重建自己的角色 ----------


def rebuild_character(member_id, nickname):
    """重新开始自己的角色：换昵称，清掉初见森林测出的动物（回到默认形象）和心情。
    回忆、消息、约会记录都保留；已经揭晓的"猜猜看"也保留（它们在回忆里），
    只删掉自己还没揭晓的猜测（重新测之前不能猜）。"""
    db = get_db()
    db.execute(
        "UPDATE members SET nickname = ?, animal_code = NULL, mood = NULL, mood_set_at = NULL WHERE id = ?",
        (nickname, member_id),
    )
    db.execute("DELETE FROM forest_results WHERE member_id = ?", (member_id,))
    db.execute("DELETE FROM forest_guesses WHERE guesser_id = ? AND actual_code IS NULL", (member_id,))
    db.commit()
