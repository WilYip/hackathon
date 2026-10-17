"""匹配引擎 services/matching.py 的单元测试（纯函数，不需要 Flask 和数据库）。"""

import copy
import json
import random
from itertools import product
from pathlib import Path

import pytest

from services import matching
from services.matching import RELAX_BUDGET, RELAX_DURATION, recommend, score_breakdown, score_task

TASKS_FILE = Path(__file__).resolve().parent.parent / "content" / "tasks.json"


def make_task(task_id, duration=15, budget="free", energy=("low",), location="home", goals=("quiet_time",)):
    return {
        "id": task_id,
        "title": {"zh": task_id, "en": task_id},
        "rules": {"zh": ["步骤"], "en": ["step"]},
        "duration": duration,
        "budget": budget,
        "energy": list(energy),
        "location": location,
        "goals": list(goals),
    }


def choice(time="1h", budget="unlimited", mood="tired", want="quiet_time"):
    return {"time": time, "budget": budget, "mood": mood, "want": want}


# ---------- 选项映射 ----------


def test_time_takes_the_smaller_value():
    assert matching.available_minutes(choice(time="half_day"), choice(time="1h")) == 60
    assert matching.available_minutes(choice(time="15min"), choice(time="half_day")) == 15
    assert matching.available_minutes(choice(time="half_day"), choice(time="half_day")) == 240


def test_budget_takes_the_lower_tier():
    assert matching.available_budget_level(choice(budget="unlimited"), choice(budget="under_20")) == 1
    assert matching.available_budget_level(choice(budget="free"), choice(budget="unlimited")) == 0
    assert matching.available_budget_level(choice(budget="unlimited"), choice(budget="unlimited")) == 2


def test_mood_to_energy_mapping():
    assert matching.MOOD_ENERGY == {
        "tired": {"low"},
        "bored": {"medium"},
        "chatty": {"low", "medium"},
        "go_out": {"medium"},
        "adventurous": {"high"},
    }
    assert matching.OUTDOOR_MOODS == {"go_out", "adventurous"}


def test_invalid_choice_raises():
    with pytest.raises(ValueError):
        recommend([], choice(time="2h"), choice(), round_id=1)
    with pytest.raises(ValueError):
        recommend([], choice(), {"time": "1h"}, round_id=1)
    with pytest.raises(ValueError):
        matching.validate_choice(choice(mood="sleepy"))


# ---------- 计分规则（每一项） ----------


def test_time_and_budget_points():
    a = b = choice(time="1h", budget="under_20")
    assert score_breakdown(make_task("t", duration=60, budget="under_20"), a, b)["time"] == 3
    assert score_breakdown(make_task("t", duration=60, budget="under_20"), a, b)["budget"] == 3
    assert score_breakdown(make_task("t", duration=90), a, b)["time"] == 0
    assert score_breakdown(make_task("t", budget="unlimited"), a, b)["budget"] == 0


def test_energy_points_both_one_none():
    task = make_task("t", energy=("low",))
    assert score_breakdown(task, choice(mood="tired"), choice(mood="tired"))["energy"] == 4
    assert score_breakdown(task, choice(mood="tired"), choice(mood="adventurous"))["energy"] == 1
    assert score_breakdown(task, choice(mood="bored"), choice(mood="adventurous"))["energy"] == 0


def test_chatty_fits_low_or_medium_energy():
    a = b = choice(mood="chatty")
    assert score_breakdown(make_task("t", energy=("low",)), a, b)["energy"] == 4
    assert score_breakdown(make_task("t", energy=("medium",)), a, b)["energy"] == 4
    assert score_breakdown(make_task("t", energy=("high",)), a, b)["energy"] == 0


def test_goal_points_both_one_none():
    task = make_task("t", goals=("memory", "teamwork"))
    assert score_breakdown(task, choice(want="memory"), choice(want="memory"))["goals"] == 5
    assert score_breakdown(task, choice(want="memory"), choice(want="teamwork"))["goals"] == 5
    assert score_breakdown(task, choice(want="memory"), choice(want="deep_talk"))["goals"] == 2
    assert score_breakdown(task, choice(want="quiet_time"), choice(want="deep_talk"))["goals"] == 0


def test_outdoor_bonus():
    outdoor = make_task("t", location="outdoor")
    home = make_task("t", location="home")
    anywhere = make_task("t", location="anywhere")
    assert score_breakdown(outdoor, choice(mood="go_out"), choice(mood="tired"))["outdoor"] == 2
    assert score_breakdown(outdoor, choice(mood="tired"), choice(mood="adventurous"))["outdoor"] == 2
    assert score_breakdown(outdoor, choice(mood="tired"), choice(mood="bored"))["outdoor"] == 0
    assert score_breakdown(home, choice(mood="go_out"), choice(mood="go_out"))["outdoor"] == 0
    assert score_breakdown(anywhere, choice(mood="go_out"), choice(mood="go_out"))["outdoor"] == 0


def test_chatty_deep_talk_bonus():
    talk = make_task("t", goals=("deep_talk",))
    assert score_breakdown(talk, choice(mood="chatty"), choice(mood="tired"))["chatty"] == 1
    assert score_breakdown(talk, choice(mood="tired"), choice(mood="tired"))["chatty"] == 0
    assert score_breakdown(make_task("t", goals=("memory",)), choice(mood="chatty"), choice())["chatty"] == 0


def test_recent_task_loses_fresh_bonus():
    task = make_task("t")
    assert score_breakdown(task, choice(), choice())["fresh"] == 2
    assert score_breakdown(task, choice(), choice(), recent_task_ids={"t"})["fresh"] == 0


def test_full_score_example():
    # 时长 +3、预算 +3、双方精力 +4、双方目标 +5、想出门且户外 +2、没做过 +2 = 19
    task = make_task("walk", duration=60, budget="free", energy=("medium",), location="outdoor", goals=("memory",))
    a = choice(time="1h", budget="free", mood="go_out", want="memory")
    b = choice(time="half_day", budget="under_20", mood="bored", want="memory")
    assert score_task(task, a, b) == 19


# ---------- 推荐：过滤、排序、同分 ----------


def test_hard_filter_excludes_too_long_or_too_expensive():
    tasks = [make_task(f"ok{i}") for i in range(3)] + [
        make_task("long", duration=90, energy=("low",), goals=("quiet_time",)),
        make_task("pricey", budget="unlimited"),
    ]
    a = b = choice(time="1h", budget="free")
    ids = [r["task_id"] for r in recommend(tasks, a, b, round_id=1)]
    assert sorted(ids) == ["ok0", "ok1", "ok2"]
    assert all(r["relaxed"] is None for r in recommend(tasks, a, b, round_id=1))


def test_returns_top_three_by_score():
    a = b = choice(time="1h", budget="free", mood="tired", want="deep_talk")
    tasks = [
        make_task("best", goals=("deep_talk",), energy=("low",)),  # 3+3+4+5+2 = 17
        make_task("good", goals=("deep_talk",), energy=("high",)),  # 3+3+0+5+2 = 13
        make_task("ok", goals=("memory",), energy=("low",)),  # 3+3+4+0+2 = 12
        make_task("meh", goals=("memory",), energy=("high",)),  # 3+3+0+0+2 = 8
    ]
    result = recommend(tasks, a, b, round_id=5)
    assert [r["task_id"] for r in result] == ["best", "good", "ok"]
    assert [r["score"] for r in result] == [17, 13, 12]


def test_ties_are_stable_within_a_round_and_vary_between_rounds():
    tasks = [make_task(f"t{i}") for i in range(8)]  # 全部同分
    a = b = choice()
    first = [r["task_id"] for r in recommend(tasks, a, b, round_id=42)]
    again = [r["task_id"] for r in recommend(tasks, a, b, round_id=42)]
    assert first == again  # 同一轮：结果稳定
    orders = {tuple(r["task_id"] for r in recommend(tasks, a, b, round_id=rid)) for rid in range(1, 21)}
    assert len(orders) > 1  # 不同轮：结果有变化


def test_recent_task_is_ranked_lower():
    tasks = [make_task("a"), make_task("b"), make_task("c"), make_task("d")]
    result = recommend(tasks, choice(), choice(), round_id=3, recent_task_ids={"a"})
    assert "a" not in [r["task_id"] for r in result]


def test_inputs_are_not_modified():
    tasks = [make_task(f"t{i}", duration=15 * (i + 1)) for i in range(6)]
    a, b = choice(time="15min"), choice()
    snapshot = copy.deepcopy((tasks, a, b))
    recommend(tasks, a, b, round_id=9)
    assert (tasks, a, b) == snapshot


# ---------- 推荐：逐步放宽 ----------


def test_relax_budget_before_duration():
    a = b = choice(time="15min", budget="free", mood="tired", want="quiet_time")
    tasks = [
        make_task("strict", duration=15, budget="free"),
        # 超预算但时长合适（分数较低）
        make_task("over_budget", duration=15, budget="unlimited", energy=("high",), goals=("memory",)),
        # 超时长但预算合适（分数更高），也要排在放宽预算之后
        make_task("over_time", duration=60, budget="free"),
        make_task("over_time_2", duration=240, budget="free", energy=("high",), goals=("memory",)),
    ]
    result = recommend(tasks, a, b, round_id=1)
    assert [(r["task_id"], r["relaxed"]) for r in result] == [
        ("strict", None),
        ("over_budget", RELAX_BUDGET),
        ("over_time", RELAX_DURATION),
    ]
    assert "稍微超出预算" in result[1]["reason"]["zh"]
    assert "goes a little over" in result[1]["reason"]["en"]
    assert "时间会长一些" in result[2]["reason"]["zh"]
    assert "takes a bit longer" in result[2]["reason"]["en"]
    assert "超出" not in result[0]["reason"]["zh"]


def test_fewer_tasks_than_count():
    result = recommend([make_task("only")], choice(), choice(), round_id=1)
    assert [r["task_id"] for r in result] == ["only"]
    assert recommend([], choice(), choice(), round_id=1) == []


# ---------- 推荐理由 ----------


def test_reason_example_from_spec():
    # 都有一小时、都想出门
    task = make_task("walk", duration=60, energy=("medium",), location="outdoor", goals=("memory",))
    a = choice(time="1h", budget="free", mood="go_out", want="memory")
    b = choice(time="1h", budget="free", mood="go_out", want="memory")
    reason = recommend([task], a, b, round_id=1)[0]["reason"]
    assert reason["zh"].startswith("推荐它，因为")
    assert "你们都有一小时" in reason["zh"]
    assert "都想出门" in reason["zh"]
    assert "你们都想制造一点回忆" in reason["zh"]
    assert reason["en"].startswith("We picked it because")
    assert "you both have an hour" in reason["en"]
    assert "you both want to get out" in reason["en"]


def test_reason_mentions_one_tired_partner():
    task = make_task("tea", energy=("low",), goals=("quiet_time",))
    a = choice(time="1h", mood="tired")
    b = choice(time="half_day", mood="bored", want="memory")
    reason = recommend([task], a, b, round_id=1)[0]["reason"]
    assert "你们一起能空出一小时" in reason["zh"]
    assert "其中一方今天比较疲惫" in reason["zh"]
    assert "其中一方想安静地待在一起" in reason["zh"]
    assert "one of you is a bit tired" in reason["en"]


def test_reason_always_bilingual_and_ends_with_period():
    tasks = [make_task(f"t{i}", goals=(g,)) for i, g in enumerate(matching.GOALS)]
    for r in recommend(tasks, choice(), choice(mood="chatty", want="deep_talk"), round_id=2):
        assert r["reason"]["zh"].endswith("。")
        assert r["reason"]["en"].endswith(".")


# ---------- 真实任务库 ----------


def load_library():
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))["tasks"]


REQUIRED_TASK_IDS = {
    "song_swap",  # 各自选择一首歌交换
    "phone_free_walk",  # 无手机散步
    "pantry_cook",  # 用家里现有材料做一道菜
    "first_photo_redo",  # 重现第一次见面的照片
    "three_thanks",  # 各自写三个感谢对方的瞬间
    "ten_min_break",  # 给对方规划一个十分钟休息时间
    "childhood_cartoon",  # 一起看童年最喜欢的动画
    "color_hunt",  # 在附近寻找三个相同颜色的物品
    "dream_weekend",  # 各自画出理想周末，再寻找重合部分
    "future_postcard",  # 设计一个未来旅行的明信片
}


def test_library_has_48_valid_tasks():
    tasks = load_library()
    assert len(tasks) == 48
    ids = [t["id"] for t in tasks]
    assert len(set(ids)) == 48
    assert REQUIRED_TASK_IDS <= set(ids)
    for t in tasks:
        assert t["title"]["zh"] and t["title"]["en"], t["id"]
        assert 2 <= len(t["rules"]["zh"]) <= 5, t["id"]
        assert len(t["rules"]["zh"]) == len(t["rules"]["en"]), t["id"]
        assert all(step.strip() for step in t["rules"]["zh"] + t["rules"]["en"]), t["id"]
        assert 1 <= t["duration"] <= 240, t["id"]
        assert t["budget"] in matching.BUDGET_LEVELS, t["id"]
        assert t["energy"] and set(t["energy"]) <= {"low", "medium", "high"}, t["id"]
        assert t["location"] in ("home", "outdoor", "anywhere"), t["id"]
        assert t["goals"] and set(t["goals"]) <= set(matching.GOALS), t["id"]


def test_library_covers_every_choice():
    """任意两人的选择组合，都能推荐出 3 个任务；条件够用时不会放宽。"""
    tasks = load_library()
    options = list(product(matching.TIME_MINUTES, matching.BUDGET_LEVELS, matching.MOOD_ENERGY, matching.GOALS))
    rng = random.Random(2026)
    pairs = [(o, o) for o in options] + [(rng.choice(options), rng.choice(options)) for _ in range(400)]
    for (t1, b1, m1, w1), (t2, b2, m2, w2) in pairs:
        a = {"time": t1, "budget": b1, "mood": m1, "want": w1}
        b = {"time": t2, "budget": b2, "mood": m2, "want": w2}
        result = recommend(tasks, a, b, round_id=7)
        assert len(result) == 3
        assert len({r["task_id"] for r in result}) == 3
        for r in result:
            assert r["reason"]["zh"] and r["reason"]["en"]
            if r["relaxed"] is None:
                assert matching.fits_time(r["task"], a, b) and matching.fits_budget(r["task"], a, b)


def test_strictest_choice_never_needs_relaxing():
    # 15 分钟 + 免费 是最严格的条件，任务库里要有足够多的任务
    tasks = load_library()
    a = b = {"time": "15min", "budget": "free", "mood": "tired", "want": "teamwork"}
    assert all(r["relaxed"] is None for r in recommend(tasks, a, b, round_id=1))
