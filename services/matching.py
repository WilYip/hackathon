"""约会选选选的匹配引擎（USLAND_SPEC.md 第 7.2、7.3 节）。

这是纯函数模块：不读数据库、不依赖 Flask，同样的输入永远得到同样的输出，方便写单元测试。
- 输入：任务库、两个人的选择、本轮 id（作为随机种子）、最近 14 天做过的任务 id
- 输出：得分最高的 3 个任务，每个带一句中英双语的推荐理由

一个人的选择是这样的字典：
    {"time": "1h", "budget": "under_20", "mood": "go_out", "want": "memory"}
"""

import random

# ---------- 选项映射（7.2 节） ----------

# 时间：双方取较小值
TIME_MINUTES = {"15min": 15, "1h": 60, "half_day": 240}

# 预算：free < under_20 < unlimited，双方取较低档
BUDGET_LEVELS = ["free", "under_20", "unlimited"]

# 状态 → 精力（想聊天可以是低或中）
MOOD_ENERGY = {
    "tired": {"low"},
    "bored": {"medium"},
    "chatty": {"low", "medium"},
    "go_out": {"medium"},
    "adventurous": {"high"},
}
OUTDOOR_MOODS = {"go_out", "adventurous"}  # 偏好户外

GOALS = ("quiet_time", "deep_talk", "memory", "teamwork")

# 放宽条件的标记
RELAX_BUDGET = "budget"
RELAX_DURATION = "duration"


# ---------- 基础工具 ----------


def validate_choice(choice):
    """检查一个人的选择是否完整、合法；不合法时抛出 ValueError。"""
    if not isinstance(choice, dict):
        raise ValueError("choice must be a dict")
    if choice.get("time") not in TIME_MINUTES:
        raise ValueError("bad time")
    if choice.get("budget") not in BUDGET_LEVELS:
        raise ValueError("bad budget")
    if choice.get("mood") not in MOOD_ENERGY:
        raise ValueError("bad mood")
    if choice.get("want") not in GOALS:
        raise ValueError("bad want")


def available_minutes(a, b):
    """双方取较小的可用时长（分钟）。"""
    return min(TIME_MINUTES[a["time"]], TIME_MINUTES[b["time"]])


def available_budget_level(a, b):
    """双方取较低的预算档（0 / 1 / 2）。"""
    return min(BUDGET_LEVELS.index(a["budget"]), BUDGET_LEVELS.index(b["budget"]))


def fits_time(task, a, b):
    return task["duration"] <= available_minutes(a, b)


def fits_budget(task, a, b):
    return BUDGET_LEVELS.index(task["budget"]) <= available_budget_level(a, b)


def _energy_fits(task, choice):
    return bool(MOOD_ENERGY[choice["mood"]] & set(task["energy"]))


# ---------- 计分（7.3 节） ----------


def score_breakdown(task, a, b, recent_task_ids=()):
    """返回每一项得分，方便测试和调试。总分 = 各项相加。"""
    parts = {}
    parts["time"] = 3 if fits_time(task, a, b) else 0
    parts["budget"] = 3 if fits_budget(task, a, b) else 0

    energy_hits = _energy_fits(task, a) + _energy_fits(task, b)
    parts["energy"] = {2: 4, 1: 1, 0: 0}[energy_hits]

    goal_hits = (a["want"] in task["goals"]) + (b["want"] in task["goals"])
    parts["goals"] = {2: 5, 1: 2, 0: 0}[goal_hits]

    moods = {a["mood"], b["mood"]}
    parts["outdoor"] = 2 if moods & OUTDOOR_MOODS and task["location"] == "outdoor" else 0
    parts["chatty"] = 1 if "chatty" in moods and "deep_talk" in task["goals"] else 0
    parts["fresh"] = 0 if task["id"] in recent_task_ids else 2
    return parts


def score_task(task, a, b, recent_task_ids=()):
    return sum(score_breakdown(task, a, b, recent_task_ids).values())


# ---------- 推荐 ----------


def recommend(tasks, a, b, round_id, recent_task_ids=(), count=3):
    """推荐 count 个任务。

    1. 硬性过滤：时长 ≤ 可用时长，且预算 ≤ 可用预算
    2. 按总分从高到低；同分时用 round_id 作为随机种子打乱（同一轮结果稳定，不同轮有变化）
    3. 不足 count 个时逐步放宽：先放宽预算，再放宽时长，并在理由里说明

    返回列表，每项是 {"task_id", "task", "score", "relaxed", "reason": {"zh", "en"}}。
    不会修改传入的 tasks、a、b。"""
    validate_choice(a)
    validate_choice(b)
    recent = set(recent_task_ids)

    # 先按种子打乱，再用稳定排序按分数排：同分的任务保持打乱后的顺序
    order = list(tasks)
    random.Random(round_id).shuffle(order)

    def ranked(pool):
        return sorted(pool, key=lambda t: score_task(t, a, b, recent), reverse=True)

    strict = [t for t in order if fits_time(t, a, b) and fits_budget(t, a, b)]
    over_budget = [t for t in order if fits_time(t, a, b) and not fits_budget(t, a, b)]
    over_time = [t for t in order if not fits_time(t, a, b)]

    picked = []
    for pool, relaxed in ((strict, None), (over_budget, RELAX_BUDGET), (over_time, RELAX_DURATION)):
        for task in ranked(pool):
            if len(picked) >= count:
                break
            picked.append((task, relaxed))

    return [
        {
            "task_id": task["id"],
            "task": task,
            "score": score_task(task, a, b, recent),
            "relaxed": relaxed,
            "reason": build_reason(task, a, b, relaxed),
        }
        for task, relaxed in picked
    ]


# ---------- 推荐理由（双语模板拼接） ----------

TIME_LABEL = {
    "15min": {"zh": "15 分钟", "en": "15 minutes"},
    "1h": {"zh": "一小时", "en": "an hour"},
    "half_day": {"zh": "半天", "en": "half a day"},
}

GOAL_PHRASE = {
    "quiet_time": {"zh": "安静地待在一起", "en": "spend quiet time together"},
    "deep_talk": {"zh": "好好聊聊", "en": "have a real talk"},
    "memory": {"zh": "制造一点回忆", "en": "make a memory"},
    "teamwork": {"zh": "一起完成一件事", "en": "get something done together"},
}

RELAX_NOTE = {
    RELAX_BUDGET: {
        "zh": "符合预算的任务不多，这个会稍微超出预算。",
        "en": "Few quests fit the budget, so this one goes a little over.",
    },
    RELAX_DURATION: {
        "zh": "符合时间的任务不多，这个需要的时间会长一些。",
        "en": "Few quests fit your time, so this one takes a bit longer.",
    },
}


def _goal_clause(task, a, b):
    ga, gb = a["want"], b["want"]
    in_a, in_b = ga in task["goals"], gb in task["goals"]
    if ga == gb and in_a:
        return {"zh": f"你们都想{GOAL_PHRASE[ga]['zh']}", "en": f"you both want to {GOAL_PHRASE[ga]['en']}"}
    if in_a and in_b:
        return {
            "zh": f"一个想{GOAL_PHRASE[ga]['zh']}、一个想{GOAL_PHRASE[gb]['zh']}，它都能满足",
            "en": f"one of you wants to {GOAL_PHRASE[ga]['en']} and the other wants to {GOAL_PHRASE[gb]['en']}",
        }
    if in_a or in_b:
        g = ga if in_a else gb
        return {"zh": f"其中一方想{GOAL_PHRASE[g]['zh']}", "en": f"one of you wants to {GOAL_PHRASE[g]['en']}"}
    return None


def _time_clause(task, a, b):
    if not fits_time(task, a, b):
        return None
    shorter = a["time"] if TIME_MINUTES[a["time"]] <= TIME_MINUTES[b["time"]] else b["time"]
    label = TIME_LABEL[shorter]
    if a["time"] == b["time"]:
        return {"zh": f"你们都有{label['zh']}", "en": f"you both have {label['en']}"}
    return {"zh": f"你们一起能空出{label['zh']}", "en": f"you can both spare {label['en']}"}


def _mood_clause(task, a, b):
    moods = [a["mood"], b["mood"]]
    outdoor = sum(m in OUTDOOR_MOODS for m in moods)
    tired = moods.count("tired")
    energy = set(task["energy"])
    if outdoor == 2 and task["location"] == "outdoor":
        return {"zh": "都想出门", "en": "you both want to get out"}
    if outdoor == 1 and task["location"] == "outdoor":
        return {"zh": "其中一方想出门", "en": "one of you wants to get out"}
    if tired == 2 and "low" in energy:
        return {"zh": "你们今天都有点累，它很轻松", "en": "you're both a bit tired and it's easy-going"}
    if tired == 1 and "low" in energy:
        return {"zh": "其中一方今天比较疲惫，它不费力", "en": "one of you is a bit tired and it takes little effort"}
    if "chatty" in moods and "deep_talk" in task["goals"]:
        return {"zh": "有人想聊天，正好可以好好说说话", "en": "someone feels chatty and there's room to talk"}
    if "adventurous" in moods and "high" in energy:
        return {"zh": "正好满足想冒险的心", "en": "it suits the adventurous mood"}
    if "bored" in moods and "medium" in energy:
        return {"zh": "能给无聊的一天加点料", "en": "it livens up a slow day"}
    return None


def _join_zh(parts):
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]}，而且{parts[1]}"
    return f"{'、'.join(parts[:-1])}，而且{parts[-1]}"


def _join_en(parts):
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def build_reason(task, a, b, relaxed=None):
    """拼出一句推荐理由，例如：推荐它，因为你们都有一小时、都想出门，而且其中一方想制造一点回忆。"""
    clauses = [c for c in (_time_clause(task, a, b), _mood_clause(task, a, b), _goal_clause(task, a, b)) if c]
    if len(clauses) < 3 and task["budget"] == "free":
        clauses.append({"zh": "不用花钱", "en": "it's free"})

    if clauses:
        zh = "推荐它，因为" + _join_zh([c["zh"] for c in clauses]) + "。"
        en = "We picked it because " + _join_en([c["en"] for c in clauses]) + "."
    else:
        zh = "推荐它，因为它很适合今天的你们。"
        en = "We picked it because it suits you both today."

    if relaxed:
        zh += RELAX_NOTE[relaxed]["zh"]
        en += " " + RELAX_NOTE[relaxed]["en"]
    return {"zh": zh, "en": en}
