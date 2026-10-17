"""约会选选选（告示牌）。完全不使用 AI。

页面：GET /quest —— 根据当前这一轮的状态显示不同内容：
    没有进行中的一轮 → 开始新的约会冒险（以及刚完成时的庆祝）
    choosing  → 一步一题选择；自己选完后显示"告示牌在等 TA 的选择……"
    deciding  → 3 个推荐任务：选这个（提议）/ 同意 / 改选其他
    confirmed → 任务卡 +"我们完成啦！"表单（照片 + 一句回忆）
操作都是普通表单 POST，完成后跳回 /quest；页面每 4 秒查一次 /api/quest/state，状态变了就刷新。
"""

from flask import (Blueprint, current_app, flash, g, jsonify, redirect, render_template, request,
                   url_for)

from services import animals, auth, images, quest
from services.auth import api_login_required, login_required
from services.i18n import get_lang, t, tr
from services.quest import QuestError

bp = Blueprint("quest", __name__)


# ---------- 显示用的小工具 ----------


def duration_label(minutes):
    """15 → 15 分钟 / 15 min；90 → 1.5 小时 / 1.5 hrs"""
    zh = get_lang() == "zh"
    if minutes < 60:
        return f"{minutes} 分钟" if zh else f"{minutes} min"
    hours = minutes / 60
    text = f"{hours:g}"
    if zh:
        return f"{text} 小时"
    return f"{text} hr" if hours == 1 else f"{text} hrs"


def _option_lookup():
    """{问题 key: {选项 value: 选项}}"""
    return {q["key"]: {o["value"]: o for o in q["options"]} for q in quest.questions()}


def task_view(task_id, rec=None):
    """把一个任务整理成页面要显示的样子（当前语言）。"""
    task = quest.tasks_by_id()[task_id]
    budget = _option_lookup()["budget"][task["budget"]]
    view = {
        "id": task_id,
        "title": tr(task["title"]),
        "rules": tr(task["rules"]),
        "duration": duration_label(task["duration"]),
        "budget": tr(budget["label"]),
        "location": t("quest.location." + task["location"]),
    }
    if rec is not None:
        view["reason"] = tr(rec["reason"])
        view["relaxed"] = rec["relaxed"]
    return view


def choice_view(choice):
    """把一个人的选择变成 [(emoji, 文字), ...]，用于"你们的选择"小结。"""
    lookup = _option_lookup()
    return [
        {"emoji": lookup[key][choice[key]]["emoji"], "label": tr(lookup[key][choice[key]]["label"])}
        for key in ("time", "budget", "mood", "want")
    ]


def _people():
    """me / partner 的昵称和头像（初见森林测出的动物，见 services/animals.py）。"""
    return animals.pair(auth.get_members(), g.user["id"])


def _memory_view(memory_id):
    memory = quest.get_memory(memory_id)
    if memory is None:
        return None
    return {
        "note": memory["note"],
        "photo": url_for("memories.media", filename=memory["photo"]) if memory["photo"] else None,
        "task": task_view(memory["ref"]) if memory["ref"] in quest.tasks_by_id() else None,
    }


def _page(**extra):
    """准备 /quest 页面需要的全部数据。"""
    members = auth.get_members()
    if len(members) < 2:
        return render_template("quest/index.html", state="alone")

    me = g.user["id"]
    people = _people()
    row = quest.active_round()
    data = {"people": people, "version": quest.version(), "note_max": quest.NOTE_MAX}

    if row is None:
        state = "none"
        done_id = request.args.get("done", type=int)
        done = quest.get_round(done_id) if done_id else None
        if done is not None and done["status"] == "completed":
            data["celebrate"] = _memory_view(done["memory_id"])
        else:
            last = quest.last_completed_round()
            data["last"] = _memory_view(last["memory_id"]) if last else None
    else:
        data["round_id"] = row["id"]
        choices = quest.get_choices(row["id"])
        if row["status"] == "choosing":
            if me in choices:
                state = "waiting"  # 自己选好了，等对方
            else:
                state = "choosing"
                data["questions"] = quest.questions()
                data["partner_ready"] = people["partner"]["id"] in choices  # 只说"选好了"，不透露选了什么
        else:
            # 双方都选好了：可以互相看到对方的选择
            data["choices"] = {"me": choice_view(choices[me]),
                               "partner": choice_view(choices[people["partner"]["id"]])}
            if row["status"] == "deciding":
                state = "deciding"
                cards = []
                for rec in quest.recommendations(row):
                    card = task_view(rec["task_id"], rec)
                    if row["proposed_task_id"] == rec["task_id"]:
                        card["status"] = "proposed_by_me" if row["proposed_by"] == me else "proposed_by_partner"
                    else:
                        card["status"] = None
                    cards.append(card)
                data["cards"] = cards
                if row["proposed_task_id"]:
                    data["proposal"] = {"by_me": row["proposed_by"] == me,
                                        "title": task_view(row["proposed_task_id"])["title"]}
            else:
                state = "confirmed"
                data["task"] = task_view(row["confirmed_task_id"])

    data["sound_events"] = _sound_events(state, row, me, data)
    data.update(extra)
    return render_template("quest/index.html", state=state, **data)


def _sound_events(state, row, me, data):
    """这个页面状态对应的事件音（static/js/sound.js）。按重要程度排序，一个页面最多响一个。
    只有"刚刚发生"时才响（自己提交了表单 / 轮询发现变化后刷新）；庆祝页 fresh=True（只有刚完成时才会看到）。"""
    events = []
    if state == "none" and data.get("celebrate"):
        events.append({"sound": "quest_complete", "key": f"quest_complete:{request.args.get('done')}", "fresh": True})
    elif row is not None:
        rid = row["id"]
        if state == "confirmed":
            events.append({"sound": "quest_agreed", "key": f"quest_agreed:{rid}"})
        elif state == "deciding":
            if row["proposed_task_id"] and row["proposed_by"] != me:
                events.append({"sound": "message_receive", "key": f"quest_propose:{rid}:{row['proposed_task_id']}"})
            events.append({"sound": "quest_reveal", "key": f"quest_reveal:{rid}"})
        elif state == "choosing" and row["created_by"] != me:
            events.append({"sound": "message_receive", "key": f"quest_round:{rid}"})
    return events


def _fail(error):
    flash(t("quest.errors." + error.code), "error")
    return redirect(url_for("quest.index"))


def _active_round_id():
    row = quest.active_round()
    if row is None:
        raise QuestError("stale")
    return row["id"]


def _need_partner():
    return len(auth.get_members()) >= 2


# ---------- 页面与操作 ----------


@bp.get("/quest")
@login_required
def index():
    return _page()


@bp.post("/quest/start")
@login_required
def start():
    if _need_partner():
        quest.start_round(g.user["id"])
    return redirect(url_for("quest.index"))


@bp.post("/quest/choose")
@login_required
def choose():
    choice = {key: request.form.get(key, "") for key in ("time", "budget", "mood", "want")}
    try:
        member_ids = [m["id"] for m in auth.get_members()]
        if len(member_ids) < 2:
            raise QuestError("stale")
        quest.submit_choice(_active_round_id(), g.user["id"], choice, member_ids)
    except ValueError:
        return _fail(QuestError("incomplete"))
    except QuestError as error:
        return _fail(error)
    return redirect(url_for("quest.index"))


@bp.post("/quest/propose")
@login_required
def propose():
    try:
        quest.propose(_active_round_id(), g.user["id"], request.form.get("task_id", ""))
    except QuestError as error:
        return _fail(error)
    return redirect(url_for("quest.index"))


@bp.post("/quest/agree")
@login_required
def agree():
    try:
        quest.agree(_active_round_id(), g.user["id"], request.form.get("task_id", ""))
    except QuestError as error:
        return _fail(error)
    return redirect(url_for("quest.index"))


@bp.post("/quest/complete")
@login_required
def complete():
    """完成任务：一句回忆（必填，≤140 字）+ 一张照片（可选）。出错时保留已填的文字。"""
    note = (request.form.get("note") or "").strip()
    errors = {}
    if not note:
        errors["note"] = t("quest.errors.note_required")
    elif len(note) > quest.NOTE_MAX:
        errors["note"] = t("quest.errors.note_too_long")

    photo_name = None
    upload = request.files.get("photo")
    if not errors and images.has_file(upload):
        try:
            photo_name = images.save_photo(upload, current_app.config["UPLOAD_DIR"])
        except images.PhotoError as error:
            errors["photo"] = t("photo.errors." + error.code)

    if errors:
        return _page(form_errors=errors, form_note=note), 400

    try:
        round_id = _active_round_id()
        quest.complete(round_id, g.user["id"], note, photo_name)
    except QuestError as error:
        images.delete_photo(photo_name, current_app.config["UPLOAD_DIR"])  # 没保存成功，照片也删掉
        return _fail(error)
    return redirect(url_for("quest.index", done=round_id))


@bp.post("/quest/cancel")
@login_required
def cancel():
    try:
        quest.cancel(_active_round_id())
    except QuestError as error:
        return _fail(error)
    flash(t("quest.cancelled"), "info")
    return redirect(url_for("quest.index"))


@bp.get("/api/quest/state")
@api_login_required
def api_state():
    """轮询用：只返回版本号，不包含任何人的具体选择。
    另一半刚完成任务时，done_url 让这边也跳到庆祝页。"""
    data = {"version": quest.version(), "done_url": None}
    if quest.active_round() is None:
        recent = quest.recently_completed()
        if recent is not None:
            data["done_url"] = url_for("quest.index", done=recent["id"])
    return jsonify(data)
