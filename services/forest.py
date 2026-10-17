"""初见森林：森林动物性格测试（USLAND_SPEC.md 第 8 节）。

上半部分是纯函数（算结果、维度得分、组合描述），只依赖传进来的数据，方便写单元测试；
下半部分是数据库操作（保存结果、两人都完成时写入回忆）。
页面上不出现 "MBTI" 字样，统一叫"森林动物性格测试"。
"""

import json

from db import get_db
from services import content

QUESTION_COUNT = 12


# ---------- 内容 ----------


def quiz():
    return content.load("quiz")


def animals():
    """{"ENFP": {...}, ...}"""
    return content.load("animals")["animals"]


# ---------- 纯函数 ----------


def validate_answers(answers, question_count=QUESTION_COUNT):
    """答案必须是 12 个 "a" 或 "b"，否则抛出 ValueError。"""
    if not isinstance(answers, (list, tuple)) or len(answers) != question_count:
        raise ValueError("need one answer per question")
    if any(a not in ("a", "b") for a in answers):
        raise ValueError("answers must be 'a' or 'b'")


def dimension_scores(questions, dimensions, answers):
    """每个维度两端各得几票，例如 {"EI": {"E": 2, "I": 1}, ...}。选 a 记前一端，选 b 记后一端。"""
    validate_answers(answers, len(questions))
    scores = {d["key"]: {d["first"]: 0, d["second"]: 0} for d in dimensions}
    by_key = {d["key"]: d for d in dimensions}
    for question, answer in zip(questions, answers):
        dim = by_key[question["dimension"]]
        pole = dim["first"] if answer == "a" else dim["second"]
        scores[dim["key"]][pole] += 1
    return scores


def result_code(questions, dimensions, answers):
    """四个维度各取票多的一端，拼成代码（如 ENFP）。每个维度 3 题，不会平局。"""
    scores = dimension_scores(questions, dimensions, answers)
    code = ""
    for dim in dimensions:
        votes = scores[dim["key"]]
        code += dim["first"] if votes[dim["first"]] > votes[dim["second"]] else dim["second"]
    return code


def combo_text(dimensions, intro, code_a, code_b):
    """"你们的组合"：按四个维度是否相同，用模板拼出 3 句中英双语描述。
    第一句：总体（完全一样 / 完全相反 / 有 n 个一样）；
    后两句：优先各取一个"相同"和一个"不同"的维度（按 能量、判断、节奏、感知 的顺序）。"""
    order = ["EI", "TF", "JP", "SN"]
    by_key = {d["key"]: d for d in dimensions}
    index = {d["key"]: i for i, d in enumerate(dimensions)}

    same, different = [], []
    for key in order:
        i = index[key]
        (same if code_a[i] == code_b[i] else different).append(key)

    if not different:
        first = intro["all_same"]
    elif not same:
        first = intro["none_same"]
    else:
        first = {lang: text.replace("{n}", str(len(same))) for lang, text in intro["some_same"].items()}

    if same and different:
        picked = [same[0], different[0]]
    else:
        picked = (same or different)[:2]

    sentences = [first]
    for key in picked:
        dim = by_key[key]
        i = index[key]
        if code_a[i] != code_b[i]:
            sentences.append(dim["combo"]["different"])
        elif code_a[i] == dim["first"]:
            sentences.append(dim["combo"]["same_first"])
        else:
            sentences.append(dim["combo"]["same_second"])

    joiner = {"zh": "", "en": " "}
    return {lang: joiner[lang].join(s[lang] for s in sentences) for lang in ("zh", "en")}


# ---------- 方便调用的包装（读取 content/ 里的数据） ----------


def compute_code(answers):
    q = quiz()
    return result_code(q["questions"], q["dimensions"], answers)


def compute_scores(answers):
    q = quiz()
    return dimension_scores(q["questions"], q["dimensions"], answers)


def couple_text(code_a, code_b):
    q = quiz()
    return combo_text(q["dimensions"], q["combo_intro"], code_a, code_b)


# ---------- 数据库 ----------


def save_result(member_id, answers):
    """保存一次测试结果：更新成员的动物（全站头像随之改变），记录答案。
    两个人都第一次完成时，在回忆里添加"我们在初见森林相遇"（只加一次）。
    返回 (动物代码, 这次是否刚刚相遇)。"""
    code = compute_code(answers)
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    db.execute(
        "INSERT INTO forest_results (member_id, code, answers) VALUES (?, ?, ?)",
        (member_id, code, json.dumps(answers)),
    )
    db.execute("UPDATE members SET animal_code = ? WHERE id = ?", (code, member_id))
    _reveal_guesses(db, member_id, code)

    met = False
    members = db.execute("SELECT id, animal_code FROM members ORDER BY id").fetchall()
    already = db.execute("SELECT 1 FROM memories WHERE kind = 'forest'").fetchone()
    if len(members) == 2 and all(m["animal_code"] for m in members) and not already:
        codes = ",".join(m["animal_code"] for m in members)
        db.execute("INSERT INTO memories (kind, ref, created_by) VALUES ('forest', ?, ?)", (codes, member_id))
        met = True
    db.commit()
    return code, met


def _reveal_guesses(db, target_id, actual_code):
    """对方测完了：揭晓所有猜 TA 的猜测，每条写一条回忆（ref = "猜的代码,真实代码"）。"""
    pending = db.execute(
        "SELECT * FROM forest_guesses WHERE target_id = ? AND actual_code IS NULL", (target_id,)
    ).fetchall()
    for guess in pending:
        cur = db.execute(
            "INSERT INTO memories (kind, ref, created_by) VALUES ('forest_guess', ?, ?)",
            (f"{guess['code']},{actual_code}", guess["guesser_id"]),
        )
        db.execute(
            "UPDATE forest_guesses SET actual_code = ?, memory_id = ?, revealed_at = datetime('now') WHERE id = ?",
            (actual_code, cur.lastrowid, guess["id"]),
        )


# ---------- 猜猜 TA 是哪只小动物 ----------


def matching_traits(code_a, code_b):
    """纯函数：两个动物代码有几个维度一样（0–4）。"""
    return sum(1 for x, y in zip(code_a, code_b) if x == y)


def can_guess(me, partner):
    """我已经测完、另一半已经加入但还没测完时，才可以猜。me / partner 是成员数据（partner 可以是 None）。"""
    return bool(me and me["animal_code"] and partner is not None and not partner["animal_code"])


def save_guess(guesser, target, code):
    """保存（或修改）我的猜测。不能猜时抛出 ValueError。"""
    if code not in animals():
        raise ValueError("unknown animal")
    if not can_guess(guesser, target):
        raise ValueError("cannot guess now")
    db = get_db()
    db.execute("DELETE FROM forest_guesses WHERE guesser_id = ? AND actual_code IS NULL", (guesser["id"],))
    db.execute(
        "INSERT INTO forest_guesses (guesser_id, target_id, code) VALUES (?, ?, ?)",
        (guesser["id"], target["id"], code),
    )
    db.commit()


def pending_guess(guesser_id):
    """我还没揭晓的猜测（没有则 None）。"""
    return get_db().execute(
        "SELECT * FROM forest_guesses WHERE guesser_id = ? AND actual_code IS NULL ORDER BY id DESC LIMIT 1",
        (guesser_id,),
    ).fetchone()


def guess_waiting_for(target_id):
    """有没有人在等我测完揭晓（对方猜了我，但还没揭晓）。"""
    return get_db().execute(
        "SELECT * FROM forest_guesses WHERE target_id = ? AND actual_code IS NULL ORDER BY id DESC LIMIT 1",
        (target_id,),
    ).fetchone()


def revealed_guesses():
    """已经揭晓的猜测（新的在前），森林页的"猜猜看揭晓"用。"""
    return get_db().execute(
        "SELECT * FROM forest_guesses WHERE actual_code IS NOT NULL ORDER BY id DESC"
    ).fetchall()


def met_memory():
    """"我们在初见森林相遇"这条回忆（没有则 None）；recent：是不是 30 分钟内刚写的。"""
    row = get_db().execute(
        "SELECT id, created_at >= datetime('now', '-30 minutes') AS recent FROM memories "
        "WHERE kind = 'forest' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {"id": row["id"], "recent": bool(row["recent"])} if row else None


def latest_result(member_id):
    """这位成员最近一次的测试结果（没有则 None）。"""
    return get_db().execute(
        "SELECT * FROM forest_results WHERE member_id = ? ORDER BY id DESC LIMIT 1", (member_id,)
    ).fetchone()


def version():
    """森林页面轮询用：两人的动物或"相遇"回忆有变化时，版本号就会变。"""
    db = get_db()
    codes = [m["animal_code"] or "-" for m in db.execute("SELECT animal_code FROM members ORDER BY id")]
    last = db.execute("SELECT MAX(id) AS id FROM forest_results").fetchone()["id"] or 0
    guess = db.execute("SELECT MAX(id) AS id FROM forest_guesses").fetchone()["id"] or 0
    return f"{':'.join(codes)}:{last}:{guess}"
