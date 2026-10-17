"""回忆小屋：回忆时间线的数据（USLAND_SPEC.md 第 9 节）。

回忆有四种来源（memories.kind）：
- quest      约会任务完成：ref = 任务 id，note = 一句回忆，photo = 照片（可选）
- reconcile  双方和好："我们和好啦"
- forest     两人都完成初见森林测试：ref = "代码A,代码B"
- manual     手动添加：note = 一句话，photo = 照片（可选）
- forest_guess  猜猜 TA 是哪只小动物揭晓：ref = "猜的代码,真实代码"，created_by = 猜的人
标题按 kind 和当前语言在显示时生成，所以中英切换后标题也会跟着变。
"""

from datetime import datetime

from flask import url_for

from db import get_db
from services import content
from services.i18n import format_date, t, tr

NOTE_MAX = 140

KIND_ICONS = {"quest": "note", "reconcile": "heart", "forest": "tree", "manual": "camera", "forest_guess": "tree"}


def list_memories():
    """所有回忆，按时间倒序（新的在前）；同一秒内按 id 倒序。"""
    return get_db().execute(
        "SELECT m.*, mb.nickname AS author FROM memories m "
        "LEFT JOIN members mb ON mb.id = m.created_by "
        "ORDER BY m.created_at DESC, m.id DESC"
    ).fetchall()


def add_manual(member_id, note, photo_name=None):
    db = get_db()
    cur = db.execute(
        "INSERT INTO memories (kind, note, photo, created_by) VALUES ('manual', ?, ?, ?)",
        (note, photo_name, member_id),
    )
    db.commit()
    return cur.lastrowid


def _title(row):
    kind = row["kind"]
    if kind == "quest":
        task = {t_["id"]: t_ for t_ in content.load("tasks")["tasks"]}.get(row["ref"])
        return tr(task["title"]) if task else t("memories.kind.quest")
    if kind == "forest":
        return t("memories.title_section.forest")
    if kind == "reconcile":
        return t("memories.title_section.reconcile")
    if kind == "forest_guess":
        guessed, _, actual = (row["ref"] or ",").partition(",")
        return t("memories.title_section.guess_right" if guessed == actual else "memories.title_section.guess_close")
    return t("memories.kind.manual")


def _subtitle(row):
    """初见森林的回忆：显示两只动物的名字；猜猜看：显示"猜的 → 其实是"。"""
    all_animals = content.load("animals")["animals"]
    if row["kind"] == "forest_guess" and row["ref"]:
        guessed, _, actual = row["ref"].partition(",")
        if guessed in all_animals and actual in all_animals:
            return t("memories.guess_subtitle", guess=tr(all_animals[guessed]["name"]),
                     actual=tr(all_animals[actual]["name"]))
        return None
    if row["kind"] != "forest" or not row["ref"]:
        return None
    names = []
    for code in row["ref"].split(","):
        if code in all_animals:
            names.append(tr(all_animals[code]["name"]))
    return " × ".join(names) or None


def to_view(row):
    """一条回忆在页面上要显示的内容（当前语言）。"""
    created = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
    return {
        "id": row["id"],
        "kind": row["kind"],
        "kind_label": t("memories.kind." + row["kind"]),
        "icon": KIND_ICONS.get(row["kind"], "heart"),
        "title": _title(row),
        "subtitle": _subtitle(row),
        "note": row["note"],
        "photo": url_for("memories.media", filename=row["photo"]) if row["photo"] else None,
        "date": format_date(created),
        "iso": created.strftime("%Y-%m-%d"),
        "author": row["author"],
    }
