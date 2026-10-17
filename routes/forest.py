"""初见森林：森林动物性格测试（页面上不出现 MBTI 字样）。完全不使用 AI。

页面：
- GET  /forest          森林：两人的动物站在森林里；两人都测完后显示"你们的组合"
- GET  /forest/quiz     一页一题，12 道题（森林小精灵带路）
- POST /forest/quiz     提交答案 → 保存结果 → 跳到结果页
- GET  /forest/result   我的结果；?who=partner 看另一半的结果
- POST /forest/guess    先测完的人猜另一半会是哪只动物（对方测完时揭晓，写一条回忆）
- GET  /api/forest/state  森林页轮询用：另一半测完时自动刷新
测出的动物会成为这个人在全站的头像（见 services/animals.py）。
"""

import json
import math

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from services import animals, auth, forest, sound
from services.auth import api_login_required, login_required
from services.i18n import t, tr

bp = Blueprint("forest", __name__)


def _animal_view(code):
    """一种动物在当前语言下的文案。"""
    a = forest.animals()[code]
    return {"code": code, "name": tr(a["name"]), "trait": tr(a["trait"]),
            "love": tr(a["love"]), "tips": tr(a["tips"])}


def _trait_bars(answers):
    """四个维度的可爱进度条：两端名字、各几票、前一端占的百分比。"""
    scores = forest.compute_scores(answers)
    bars = []
    for d in forest.quiz()["dimensions"]:
        first, second = scores[d["key"]][d["first"]], scores[d["key"]][d["second"]]
        bars.append({
            "label": tr(d["label"]),
            "first": tr(d["names"][d["first"]]),
            "second": tr(d["names"][d["second"]]),
            "first_votes": first,
            "second_votes": second,
            "percent": round(first / (first + second) * 100),
            "winner": "first" if first > second else "second",
        })
    return bars


def _questions_view():
    """每道题：题目、两个选项（含小精灵的回应）、属于哪个维度、选 a / b 各记哪一端。"""
    dims = {d["key"]: d for d in forest.quiz()["dimensions"]}
    result = []
    for i, q in enumerate(forest.quiz()["questions"]):
        dim = dims[q["dimension"]]
        result.append({
            "number": i + 1, "text": tr(q["text"]), "dimension": dim["key"],
            "a": {"emoji": q["a"]["emoji"], "text": tr(q["a"]["text"]), "spirit": tr(q["a"]["spirit"]),
                  "pole": dim["first"]},
            "b": {"emoji": q["b"]["emoji"], "text": tr(q["b"]["text"]), "spirit": tr(q["b"]["spirit"]),
                  "pole": dim["second"]},
        })
    return result


def _discoveries():
    """"森林发现"卡片的文案：{"EI": {"label": "能量", "poles": {"E": {"name": "热闹派", "text": ...}, ...}}}"""
    return {
        d["key"]: {"label": tr(d["label"]),
                   "poles": {pole: {"name": tr(d["names"][pole]), "text": tr(d["discovery"][pole])}
                             for pole in (d["first"], d["second"])}}
        for d in forest.quiz()["dimensions"]
    }


def walk_points(count):
    """纯函数：森林小路上的点（百分比坐标）。第 0 个是起点，第 1–count 个是路标。
    小路从左到右，上下轻轻起伏。"""
    points = []
    for n in range(count + 1):
        x = 5 + n * 90 / count
        y = 64 + 12 * math.sin(n * 0.95)
        points.append({"n": n, "x": round(x, 2), "y": round(y, 2)})
    return points


def walk_path(points):
    """纯函数：经过所有点的平滑曲线（SVG path，坐标就是百分比，viewBox 0 0 100 100）。"""
    d = f"M {points[0]['x']} {points[0]['y']}"
    for i in range(1, len(points)):
        p0 = points[max(i - 2, 0)]
        p1, p2 = points[i - 1], points[i]
        p3 = points[min(i + 1, len(points) - 1)]
        # Catmull-Rom 转成三次贝塞尔：控制点在前后两点连线方向上
        c1 = (p1["x"] + (p2["x"] - p0["x"]) / 6, p1["y"] + (p2["y"] - p0["y"]) / 6)
        c2 = (p2["x"] - (p3["x"] - p1["x"]) / 6, p2["y"] - (p3["y"] - p1["y"]) / 6)
        d += f" C {c1[0]:.2f} {c1[1]:.2f} {c2[0]:.2f} {c2[1]:.2f} {p2['x']} {p2['y']}"
    return d


def _quiz_page(**extra):
    questions = _questions_view()
    points = walk_points(len(questions))
    me = animals.pair(auth.get_members(), g.user["id"])["me"]
    return render_template("forest/quiz.html", questions=questions, spirit=animals.spirit_url(),
                           discoveries=_discoveries(), points=points, path=walk_path(points), me=me, **extra)


def _animal_choices():
    """猜猜看用：16 种动物（当前语言的名字 + 头像信息）。"""
    choices = []
    for code, a in forest.animals().items():
        path = animals.find_image(code.lower())
        choices.append({"code": code, "name": tr(a["name"]), "trait": tr(a["trait"]),
                        "src": animals.image_url(path) if path else None,
                        "initial": tr(a["initial"]), "animal_name": tr(a["name"]),
                        "index": len(choices) % 2 + 1})
    return choices


def _guess_reveal(members_by_id):
    """森林页上最近一次揭晓的猜测：谁猜谁、猜的、其实是、有几个小特点猜中。"""
    rows = forest.revealed_guesses()
    if not rows:
        return None
    row = rows[0]
    guesser, target = members_by_id.get(row["guesser_id"]), members_by_id.get(row["target_id"])
    if guesser is None or target is None:
        return None
    all_animals = forest.animals()
    return {
        "guesser": guesser["nickname"], "target": target["nickname"],
        "guess": tr(all_animals[row["code"]]["name"]), "actual": tr(all_animals[row["actual_code"]]["name"]),
        "correct": row["code"] == row["actual_code"],
        "matching": forest.matching_traits(row["code"], row["actual_code"]),
    }


# ---------- 森林 ----------


@bp.get("/forest")
@login_required
def index():
    members = auth.get_members()
    people = animals.pair(members, g.user["id"])
    for p in people.values():
        if p is not None:
            p["animal"] = _animal_view(p["code"]) if p["code"] else None

    combo = None
    if people["partner"] and people["me"]["code"] and people["partner"]["code"]:
        # 组合描述按成员加入顺序计算，两个人看到的是同一段话
        codes = [m["animal_code"] for m in members]
        combo = {"text": tr(forest.couple_text(codes[0], codes[1])),
                 "names": [tr(forest.animals()[c]["name"]) for c in codes]}

    # 猜猜看：我猜了还没揭晓 / 对方猜了我在等我测 / 最近一次揭晓
    by_id = {m["id"]: m for m in members}
    pending = forest.pending_guess(g.user["id"])
    my_guess = tr(forest.animals()[pending["code"]]["name"]) if pending else None
    waiting = forest.guess_waiting_for(g.user["id"]) is not None
    me_row = by_id[g.user["id"]]
    partner_row = next((m for m in members if m["id"] != g.user["id"]), None)

    # 双人组合第一次显示：pair_reveal（不另播回忆保存音）。只有 30 分钟内刚相遇时才响，每台设备只响一次
    sound_events = []
    if combo:
        met = forest.met_memory()
        if met is not None:
            sound_events.append({"sound": "pair_reveal", "key": f"pair:{met['id']}", "fresh": met["recent"]})

    return render_template(
        "forest/index.html",
        sound_events=sound_events,
        me=people["me"],
        partner=people["partner"],
        combo=combo,
        version=forest.version(),
        my_guess=my_guess,
        guessed_me=waiting,
        can_guess=forest.can_guess(me_row, partner_row),
        reveal=_guess_reveal(by_id) if combo else None,
    )


# ---------- 测试 ----------


@bp.get("/forest/quiz")
@login_required
def quiz():
    return _quiz_page()


@bp.post("/forest/quiz")
@login_required
def submit_quiz():
    count = len(forest.quiz()["questions"])
    answers = [request.form.get(f"q{i}", "") for i in range(1, count + 1)]
    try:
        forest.validate_answers(answers, count)
    except ValueError:
        # 有题没答：回到测试页，保留已经选好的答案
        return _quiz_page(error=t("forest.incomplete"), chosen=answers), 400

    waiting = forest.guess_waiting_for(g.user["id"])  # 另一半之前猜过我是哪只动物
    _code, met = forest.save_result(g.user["id"], answers)
    if met:
        flash(t("forest.met"), "info")
    if waiting is not None:
        guesser = next((m for m in auth.get_members() if m["id"] == waiting["guesser_id"]), None)
        if guesser is not None:
            flash(t("forest.guess.revealed_flash", name=guesser["nickname"]), "info")
    return redirect(url_for("forest.result", new=1))


@bp.get("/forest/result")
@login_required
def result():
    members = auth.get_members()
    people = animals.pair(members, g.user["id"])
    who = "partner" if request.args.get("who") == "partner" and people["partner"] else "me"
    person = people[who]
    latest = forest.latest_result(person["id"])
    if latest is None:
        return redirect(url_for("forest.index"))  # 还没测过

    # 猜猜看：看自己的结果、另一半已加入但还没测时，可以猜 TA 是哪只动物
    guess = None
    if who == "me":
        me_row = next(m for m in members if m["id"] == g.user["id"])
        partner_row = next((m for m in members if m["id"] != g.user["id"]), None)
        if forest.can_guess(me_row, partner_row):
            pending = forest.pending_guess(g.user["id"])
            guess = {"partner": partner_row["nickname"], "choices": _animal_choices(),
                     "current": pending["code"] if pending else None}

    return render_template(
        "forest/result.html",
        person=person,
        is_me=who == "me",
        animal=_animal_view(latest["code"]),
        bars=_trait_bars(json.loads(latest["answers"])),
        is_new=request.args.get("new") == "1" and who == "me",
        guess=guess,
    )


@bp.post("/forest/guess")
@login_required
def guess():
    """猜另一半会是哪只动物。揭晓前可以改猜。"""
    members = auth.get_members()
    me_row = next(m for m in members if m["id"] == g.user["id"])
    partner_row = next((m for m in members if m["id"] != g.user["id"]), None)
    try:
        forest.save_guess(me_row, partner_row, request.form.get("code", ""))
        flash(t("forest.guess.saved", name=partner_row["nickname"]), "info")
        sound.cue("ui_success")
    except ValueError:
        flash(t("forest.guess.invalid"), "error")
        return redirect(url_for("forest.result"))
    return redirect(url_for("forest.index"))


@bp.get("/api/forest/state")
@api_login_required
def api_state():
    return jsonify({"version": forest.version()})
