"""演示模式（USLAND_SPEC.md 第 13 节，环境变量 DEMO_MODE=1）。

给很多人一起试玩的公开演示：
- 网站里永远有一座演示小岛：两位岛民 Wilson（星图猫头鹰 INTJ）和 Yvette（暖心考拉 ISFJ），
  PIN 都是 1234；预置两人的动物结果、三条回忆、几条传话
- 登录页直接点"以 Wilson / Yvette 进入"，不用输 PIN（避免有人故意输错把角色锁住）
- 所有访客共用这座小岛，所以每 6 小时自动恢复成初始状态（小信箱里也可以手动恢复）
- 共用小岛的保护：不能改 PIN / 昵称 / 岛名、不能填 API key、不能上传照片、不能创建新角色或新小岛
- 温柔传话用预先写好的示范改写，不调用 AI（演示版不预置、也不接受任何 API key）
- 约会选选选可以"代替对方选择 / 同意"，一个人也能走完整个流程

安全：只有数据目录里有演示标记文件（demo_reset_at），或者数据库里还没有小岛时，才会自动重置。
所以就算有人在真实小岛上误开了 DEMO_MODE=1，也不会清空真实数据。
"""

import threading
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import current_app, flash, jsonify, redirect, request, url_for

from db import get_db
from services import auth, forest
from services.i18n import t

PIN = "1234"
ISLAND_NAME = "Usland Demo Isle"
MARKER = "demo_reset_at"  # DATA_DIR 下的标记文件：上次重置的时间（UTC ISO 格式）

# 两位演示岛民：昵称、初见森林的答案（12 题，见 content/quiz.json：每 3 题一个维度，a = E/S/T/J，b = I/N/F/P）
RESIDENTS = [
    {"nickname": "Wilson", "answers": ["b"] * 3 + ["b"] * 3 + ["a"] * 3 + ["a"] * 3},   # INTJ 星图猫头鹰
    {"nickname": "Yvette", "answers": ["b"] * 3 + ["a"] * 3 + ["b"] * 3 + ["a"] * 3},   # ISFJ 暖心考拉
]

# 预置的传话（发送者序号，最终文字，原话）。原话只有发送者本人看得到
MESSAGES = [
    (1, "Want to try the new dumpling place after work tonight?", None),
    (0, "I felt a little left out when plans changed without me. Could we decide together next time?",
     "You always change plans without asking me!!"),
    (1, "You're right, I'm sorry. Next time I'll check with you first.", None),
    (0, "Thank you. Dumplings sound perfect.", None),
]

# 预置的手动回忆（记录人序号，一句话，几天前）。初见森林的"相遇"回忆由测试结果自动生成，一共三条
MEMORIES = [
    (0, "Sunset from the balcony, both of us too lazy to cook.", 3),
    (1, "First picnic of spring. Wilson forgot the forks again.", 1),
]

# 温柔传话的示范改写（不调用 AI）：按原话挑一句，中文原话用中文、其他用英文
DEMO_SOFTEN = {
    "zh": [
        "我现在心里有点难受，想和你好好聊聊，可以吗？",
        "刚才那件事让我有点委屈，我希望我们能一起想想办法。",
        "我有点着急，但我更想听听你的想法，我们慢慢说好吗？",
        "我知道你也不容易。我只是希望下次我们能先商量一下。",
    ],
    "en": [
        "I'm feeling a bit hurt right now. Could we talk about it together?",
        "That made me feel a little left out. I'd love for us to figure it out together.",
        "I'm a bit frustrated, but I really want to hear your side. Can we take it slowly?",
        "I know things are hard for you too. I just hope we can talk it through first next time.",
    ],
}

_lock = threading.Lock()


# ---------- 开关与状态 ----------


def enabled():
    return bool(current_app.config.get("DEMO_MODE"))


def _marker_path():
    return Path(current_app.config["DATA_DIR"]) / MARKER


def last_reset():
    """上次重置的时间（UTC）；没有标记文件时返回 None。"""
    try:
        return datetime.fromisoformat(_marker_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def reset_every():
    return timedelta(hours=current_app.config.get("DEMO_RESET_HOURS", 6))


def next_reset():
    last = last_reset()
    return last + reset_every() if last else None


def view():
    """模板里用的演示信息（不是演示模式时 enabled=False）。"""
    if not enabled():
        return {"enabled": False}
    nxt = next_reset()
    minutes = max(0, int((nxt - datetime.now(timezone.utc)).total_seconds() // 60)) if nxt else None
    return {"enabled": True, "pin": PIN, "hours": int(reset_every().total_seconds() // 3600),
            "minutes_left": minutes}


# ---------- 重置 ----------


def maybe_reset():
    """每个请求开始时调用：演示小岛不存在，或者距离上次重置已经超过 6 小时，就恢复成初始状态。"""
    if not enabled():
        return
    last = last_reset()
    has_island = auth.get_island() is not None
    if last is None and has_island:
        # 没有演示标记、却已经有小岛：这是真实数据，绝对不动
        current_app.logger.warning("DEMO_MODE=1 但数据目录里是真实小岛（没有演示标记），不会重置。")
        return
    if has_island and datetime.now(timezone.utc) - last < reset_every():
        return
    reset(force=False)


def reset(force=True):
    """清空所有数据和上传的照片，重新生成演示小岛。
    自动恢复（force=False）时，多个请求同时触发只重置一次；小信箱里手动恢复（force=True）总会执行。"""
    with _lock:
        last = last_reset()
        recently = last and datetime.now(timezone.utc) - last < timedelta(seconds=5)
        if not force and recently and auth.get_island() is not None:
            return  # 刚刚别的请求已经重置过了
        db = get_db()
        db.commit()
        db.execute("PRAGMA foreign_keys = OFF")
        tables = [r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        for name in tables:
            db.execute(f'DELETE FROM "{name}"')
        # 自增编号也归零：两位岛民永远是 1 号和 2 号，旧的登录状态还能对应到同一个角色
        if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
            db.execute("DELETE FROM sqlite_sequence")
        db.commit()
        db.execute("PRAGMA foreign_keys = ON")

        upload_dir = Path(current_app.config["UPLOAD_DIR"])
        if upload_dir.exists():
            for f in upload_dir.iterdir():
                if f.is_file():
                    f.unlink(missing_ok=True)

        _seed(db)
        _marker_path().write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def _seed(db):
    db.execute("INSERT INTO island (id, name, invite_code) VALUES (1, ?, ?)",
               (ISLAND_NAME, auth.generate_invite_code()))
    ids = []
    for r in RESIDENTS:
        cur = db.execute("INSERT INTO members (nickname, pin_hash, lang) VALUES (?, ?, 'en')",
                         (r["nickname"], auth.hash_pin(PIN)))
        ids.append(cur.lastrowid)
    db.commit()

    # 初见森林：两人都测完会自动写入"我们在初见森林相遇"
    for member_id, r in zip(ids, RESIDENTS):
        forest.save_result(member_id, r["answers"])

    for i, (who, text, original) in enumerate(MESSAGES):
        minutes = (len(MESSAGES) - i) * 7
        db.execute(
            "INSERT INTO messages (sender_id, final_text, original_text, created_at) "
            "VALUES (?, ?, ?, datetime('now', ?))",
            (ids[who], text, original, f"-{minutes} minutes"),
        )
    for who, note, days in MEMORIES:
        db.execute(
            "INSERT INTO memories (kind, note, created_by, created_at) VALUES ('manual', ?, ?, datetime('now', ?))",
            (note, ids[who], f"-{days} days"),
        )
    # 森林相遇的回忆放在最早
    db.execute("UPDATE memories SET created_at = datetime('now', '-5 days') WHERE kind = 'forest'")
    # Yvette 今天心情不错（首页和传话页能看到心情效果）
    db.execute("UPDATE members SET mood = 'happy', mood_set_at = ? WHERE id = ?",
               (datetime.now(timezone.utc).isoformat(), ids[1]))
    db.commit()


# ---------- 共用小岛的保护 ----------


def blocked(api=False):
    """装饰器：演示模式下不允许的操作（改 PIN、改昵称、填 API key……）。
    页面请求：提示后跳回原来的页面；接口请求（api=True）：返回 403 JSON。"""
    def deco(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if enabled():
                if api:
                    return jsonify({"ok": False, "error": "demo", "message": t("demo.blocked")}), 403
                flash(t("demo.blocked"), "error")
                back = request.referrer or ""
                host = request.host_url.rstrip("/")
                return redirect(back if back.startswith(host) else url_for("island.index"))
            return view_func(*args, **kwargs)
        return wrapper
    return deco


def soften(text):
    """温柔传话的示范改写：按原话的内容固定挑一句（同一句话每次结果一样）。"""
    lang = "zh" if any("一" <= ch <= "鿿" for ch in text) else "en"
    options = DEMO_SOFTEN[lang]
    return options[sum(map(ord, text)) % len(options)]

