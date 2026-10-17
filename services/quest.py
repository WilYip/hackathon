"""约会选选选的数据操作：一轮冒险从开始到完成的每一步。

状态流转（见 db.py 的 quest_rounds 表）：
    choosing（各自选择）→ deciding（共同挑任务，可以有提议）→ confirmed（已共同确定）→ completed（已完成）
    任何进行中的状态都可以 cancelled（结束这一轮）

所有修改都先 BEGIN IMMEDIATE 加写锁、再检查状态，两个人同时点按钮也不会出错。
出错时抛出 QuestError(code)，路由负责把 code 翻译成提示文字。
"""

import json

from db import get_db
from services import content, matching

ACTIVE_STATUSES = ("choosing", "deciding", "confirmed")
NOTE_MAX = 140  # 一句回忆最多 140 字
RECENT_DAYS = 14


class QuestError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ---------- 内容 ----------


def tasks_by_id():
    return {t["id"]: t for t in content.load("tasks")["tasks"]}


def questions():
    """四个问题及选项（content/quest_options.json）。"""
    return content.load("quest_options")["questions"]


# ---------- 读取 ----------


def active_round():
    return get_db().execute(
        "SELECT * FROM quest_rounds WHERE status IN ('choosing', 'deciding', 'confirmed') ORDER BY id DESC LIMIT 1"
    ).fetchone()


def get_round(round_id):
    return get_db().execute("SELECT * FROM quest_rounds WHERE id = ?", (round_id,)).fetchone()


def last_completed_round():
    return get_db().execute(
        "SELECT * FROM quest_rounds WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def get_choices(round_id):
    """{member_id: 选择}，选择的格式和匹配引擎一样。"""
    rows = get_db().execute("SELECT * FROM quest_choices WHERE round_id = ?", (round_id,)).fetchall()
    return {r["member_id"]: _row_to_choice(r) for r in rows}


def _row_to_choice(row):
    return {"time": row["time_option"], "budget": row["budget"], "mood": row["mood"], "want": row["want"]}


def recommendations(round_row):
    """这一轮的 3 个推荐（存在数据库里的 JSON）。"""
    if not round_row or not round_row["recommendations"]:
        return []
    return json.loads(round_row["recommendations"])


def recent_task_ids():
    """最近 14 天完成过的任务（匹配时它们少 2 分）。"""
    rows = get_db().execute(
        "SELECT confirmed_task_id FROM quest_rounds WHERE status = 'completed' "
        "AND completed_at >= datetime('now', ?)",
        (f"-{RECENT_DAYS} days",),
    ).fetchall()
    return {r["confirmed_task_id"] for r in rows}


def get_memory(memory_id):
    return get_db().execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()


# ---------- 修改 ----------


def _locked_round(db, round_id, *allowed_statuses):
    """加写锁后重新读取这一轮，并检查状态。"""
    db.execute("BEGIN IMMEDIATE")
    row = db.execute("SELECT * FROM quest_rounds WHERE id = ?", (round_id,)).fetchone()
    if row is None or row["status"] not in allowed_statuses:
        db.rollback()
        raise QuestError("stale")  # 页面上的状态已经过时（比如对方刚刚改了）
    return row


def start_round(member_id):
    """开始新的一轮。已经有进行中的一轮时，直接返回那一轮（同一时间只能有一轮）。"""
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute(
        "SELECT * FROM quest_rounds WHERE status IN ('choosing', 'deciding', 'confirmed') LIMIT 1"
    ).fetchone()
    if row is None:
        cur = db.execute("INSERT INTO quest_rounds (created_by) VALUES (?)", (member_id,))
        row = db.execute("SELECT * FROM quest_rounds WHERE id = ?", (cur.lastrowid,)).fetchone()
    db.commit()
    return row


def submit_choice(round_id, member_id, choice, member_ids):
    """提交自己的选择。双方都提交后，运行匹配引擎并进入 deciding。
    member_ids 是两位成员按加入顺序排列的 id，用来固定传给匹配引擎的顺序。"""
    matching.validate_choice(choice)
    db = get_db()
    _locked_round(db, round_id, "choosing")
    exists = db.execute(
        "SELECT 1 FROM quest_choices WHERE round_id = ? AND member_id = ?", (round_id, member_id)
    ).fetchone()
    if exists:
        db.rollback()
        raise QuestError("already_chosen")
    db.execute(
        "INSERT INTO quest_choices (round_id, member_id, time_option, budget, mood, want) VALUES (?, ?, ?, ?, ?, ?)",
        (round_id, member_id, choice["time"], choice["budget"], choice["mood"], choice["want"]),
    )

    rows = db.execute("SELECT * FROM quest_choices WHERE round_id = ?", (round_id,)).fetchall()
    chosen = {r["member_id"]: _row_to_choice(r) for r in rows}
    if all(mid in chosen for mid in member_ids):
        a, b = chosen[member_ids[0]], chosen[member_ids[1]]
        recs = matching.recommend(
            list(tasks_by_id().values()), a, b, round_id=round_id, recent_task_ids=recent_task_ids()
        )
        stored = [{k: r[k] for k in ("task_id", "score", "relaxed", "reason")} for r in recs]
        db.execute(
            "UPDATE quest_rounds SET status = 'deciding', recommendations = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(stored, ensure_ascii=False), round_id),
        )
    else:
        db.execute("UPDATE quest_rounds SET updated_at = datetime('now') WHERE id = ?", (round_id,))
    db.commit()


def propose(round_id, member_id, task_id):
    """"选这个"：提议一个任务（会替换掉之前的提议，不管是谁提的）。"""
    db = get_db()
    row = _locked_round(db, round_id, "deciding")
    if task_id not in {r["task_id"] for r in recommendations(row)}:
        db.rollback()
        raise QuestError("bad_task")
    db.execute(
        "UPDATE quest_rounds SET proposed_task_id = ?, proposed_by = ?, updated_at = datetime('now') WHERE id = ?",
        (task_id, member_id, round_id),
    )
    db.commit()


def agree(round_id, member_id, task_id):
    """"同意"：同意对方提议的任务，双方共同确定。不能同意自己的提议。"""
    db = get_db()
    row = _locked_round(db, round_id, "deciding")
    if row["proposed_task_id"] != task_id or row["proposed_by"] in (None, member_id):
        db.rollback()
        raise QuestError("stale")
    db.execute(
        "UPDATE quest_rounds SET status = 'confirmed', confirmed_task_id = ?, updated_at = datetime('now') "
        "WHERE id = ?",
        (task_id, round_id),
    )
    db.commit()


def complete(round_id, member_id, note, photo_name=None):
    """"我们完成啦"：写入回忆（任务名、照片、一句回忆），这一轮结束。返回回忆 id。"""
    db = get_db()
    row = _locked_round(db, round_id, "confirmed")
    cur = db.execute(
        "INSERT INTO memories (kind, ref, note, photo, created_by) VALUES ('quest', ?, ?, ?, ?)",
        (row["confirmed_task_id"], note, photo_name, member_id),
    )
    db.execute(
        "UPDATE quest_rounds SET status = 'completed', memory_id = ?, completed_at = datetime('now'), "
        "updated_at = datetime('now') WHERE id = ?",
        (cur.lastrowid, round_id),
    )
    db.commit()
    return cur.lastrowid


def cancel(round_id):
    """结束这一轮（没完成也可以结束，之后可以开始新的一轮）。"""
    db = get_db()
    _locked_round(db, round_id, *ACTIVE_STATUSES)
    db.execute(
        "UPDATE quest_rounds SET status = 'cancelled', updated_at = datetime('now') WHERE id = ?", (round_id,)
    )
    db.commit()


# ---------- 给页面用的状态 ----------


def version():
    """当前状态的"版本号"。页面每 4 秒查一次，变了就刷新。不包含任何人的具体选择。"""
    row = active_round()
    if row is None:
        last = last_completed_round()
        return f"none:{last['id'] if last else 0}"
    count = get_db().execute("SELECT COUNT(*) AS n FROM quest_choices WHERE round_id = ?", (row["id"],)).fetchone()
    return f"{row['id']}:{row['status']}:{count['n']}:{row['proposed_task_id']}:{row['proposed_by']}"


def recently_completed(minutes=10):
    """刚刚（10 分钟内）完成的一轮，用来让另一半的页面也跳到庆祝页。"""
    return get_db().execute(
        "SELECT * FROM quest_rounds WHERE status = 'completed' AND completed_at >= datetime('now', ?) "
        "ORDER BY id DESC LIMIT 1",
        (f"-{minutes} minutes",),
    ).fetchone()


def attention(member_id):
    """首页告示牌上的提示：轮到我选择 / 对方提议了任务等我确认；没有就返回 None。"""
    row = active_round()
    if row is None:
        return None
    if row["status"] == "choosing" and member_id not in get_choices(row["id"]):
        return "your_turn"
    if row["status"] == "deciding" and row["proposed_by"] not in (None, member_id):
        return "proposal"
    return None
