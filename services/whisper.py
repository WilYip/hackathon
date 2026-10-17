"""温柔传话的数据操作：API key、消息、已读、和好、每日次数。

隐私规则（重要）：
- API key 只在后端使用，返回给前端的只有 mask_key() 的结果，例如 sk-****a3f9
- 原话 original_text 只在"查看的人就是发送者"时才放进返回结果（见 message_to_json）
"""

from datetime import datetime, timezone

from db import get_db


# ---------- API key ----------


def get_api_key():
    row = get_db().execute("SELECT deepseek_api_key FROM island WHERE id = 1").fetchone()
    return row["deepseek_api_key"] if row and row["deepseek_api_key"] else None


def save_api_key(key):
    db = get_db()
    db.execute("UPDATE island SET deepseek_api_key = ? WHERE id = 1", (key,))
    db.commit()


def mask_key(key):
    """只显示末尾 4 位：sk-****a3f9。"""
    if not key:
        return None
    prefix = "sk-" if key.startswith("sk-") else ""
    return f"{prefix}****{key[-4:]}"


def looks_like_key(key):
    """简单检查格式：长度合理、没有空格。真正是否可用要靠 ai.check_key 测试。"""
    return 10 <= len(key) <= 200 and not any(ch.isspace() for ch in key)


# ---------- 消息 ----------


def _iso(sqlite_time):
    """SQLite 的 'YYYY-MM-DD HH:MM:SS'（UTC）转成前端能直接解析的 ISO 格式。"""
    return sqlite_time.replace(" ", "T") + "Z"


def message_to_json(row, viewer_id):
    """把一条消息转成返回给前端的数据。原话只给发送者本人。"""
    mine = row["sender_id"] == viewer_id
    data = {
        "id": row["id"],
        "mine": mine,
        "text": row["final_text"],
        "time": _iso(row["created_at"]),
    }
    if mine and row["original_text"]:
        data["original"] = row["original_text"]
    return data


def list_messages(after_id=0, limit=200):
    """按时间顺序返回消息。
    after_id 为 0（刚打开页面）：最近的 limit 条；否则：id 大于 after_id 的新消息。"""
    db = get_db()
    if after_id <= 0:
        rows = db.execute("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return list(reversed(rows))
    return db.execute(
        "SELECT * FROM messages WHERE id > ? ORDER BY id LIMIT ?", (after_id, limit)
    ).fetchall()


def add_message(sender_id, final_text, original_text=None):
    db = get_db()
    cur = db.execute(
        "INSERT INTO messages (sender_id, final_text, original_text) VALUES (?, ?, ?)",
        (sender_id, final_text, original_text),
    )
    db.commit()
    return db.execute("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)).fetchone()


# ---------- 已读 / 未读 ----------


def mark_read(member_id, message_id):
    """记录读到了哪条消息（只会往后移，不会倒退）。"""
    db = get_db()
    db.execute(
        "INSERT INTO whisper_reads (member_id, last_read_id) VALUES (?, ?) "
        "ON CONFLICT(member_id) DO UPDATE SET last_read_id = MAX(last_read_id, excluded.last_read_id)",
        (member_id, message_id),
    )
    db.commit()


def unread_count(member_id):
    """对方发来、我还没读的消息数（首页传话码头的信封标记用）。"""
    row = get_db().execute(
        "SELECT COUNT(*) AS n FROM messages WHERE sender_id != ? AND id > "
        "COALESCE((SELECT last_read_id FROM whisper_reads WHERE member_id = ?), 0)",
        (member_id, member_id),
    ).fetchone()
    return row["n"]


# ---------- 每日软化次数 ----------


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def try_use_soften(daily_limit):
    """如果今天还没用完，次数 +1 并返回 True；用完了返回 False。"""
    db = get_db()
    db.execute("BEGIN IMMEDIATE")  # 加写锁，两个人同时请求也不会多算或少算
    row = db.execute("SELECT count FROM soften_usage WHERE day = ?", (_today(),)).fetchone()
    used = row["count"] if row else 0
    if used >= daily_limit:
        db.rollback()
        return False
    db.execute(
        "INSERT INTO soften_usage (day, count) VALUES (?, 1) "
        "ON CONFLICT(day) DO UPDATE SET count = count + 1",
        (_today(),),
    )
    db.commit()
    return True


# ---------- 和好 ----------


def reconcile_state(member_id):
    """{"me": 我按了没有, "partner": TA 按了没有}"""
    rows = get_db().execute("SELECT member_id FROM reconcile_requests").fetchall()
    pressed = {r["member_id"] for r in rows}
    return {"me": member_id in pressed, "partner": bool(pressed - {member_id})}


def press_reconcile(member_id):
    """按下"和好"。双方都按下后：在回忆里添加"我们和好啦"、清空和好状态，
    返回这条回忆的 id（前端用它播放拥抱动画）；否则返回 None。"""
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    db.execute("INSERT OR IGNORE INTO reconcile_requests (member_id) VALUES (?)", (member_id,))
    pressed = db.execute("SELECT COUNT(*) AS n FROM reconcile_requests").fetchone()["n"]
    if pressed < 2:
        db.commit()
        return None
    cur = db.execute("INSERT INTO memories (kind, created_by) VALUES ('reconcile', ?)", (member_id,))
    db.execute("DELETE FROM reconcile_requests")
    db.commit()
    return cur.lastrowid


def latest_hug_id():
    """最近一次和好记录的 id；两边的页面发现它变大了，就播放拥抱动画。"""
    row = get_db().execute("SELECT MAX(id) AS id FROM memories WHERE kind = 'reconcile'").fetchone()
    return row["id"] or 0
