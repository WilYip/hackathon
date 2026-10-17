"""初见森林的纯函数和内容检查（不需要 Flask 和数据库）。"""

import json
from itertools import product
from pathlib import Path

import pytest

from services.forest import combo_text, dimension_scores, result_code, validate_answers

ROOT = Path(__file__).resolve().parent.parent
QUIZ = json.loads((ROOT / "content" / "quiz.json").read_text(encoding="utf-8"))
ANIMALS = json.loads((ROOT / "content" / "animals.json").read_text(encoding="utf-8"))["animals"]
QUESTIONS, DIMENSIONS, INTRO = QUIZ["questions"], QUIZ["dimensions"], QUIZ["combo_intro"]

# 题目顺序：1–3 能量（E/I），4–6 感知（S/N），7–9 判断（T/F），10–12 节奏（J/P）
ALL_A = ["a"] * 12


def answers_for(code):
    """构造一组答案：每个维度 3 题都选同一端，得到指定的代码。"""
    result = []
    for dim, letter in zip(DIMENSIONS, code):
        result += ["a" if letter == dim["first"] else "b"] * 3
    return result


# ---------- 内容 ----------


def test_twelve_questions_three_per_dimension():
    assert len(QUESTIONS) == 12
    for dim in DIMENSIONS:
        assert sum(q["dimension"] == dim["key"] for q in QUESTIONS) == 3
    assert [d["key"] for d in DIMENSIONS] == ["EI", "SN", "TF", "JP"]
    for q in QUESTIONS:
        for part in (q["text"], q["a"]["text"], q["b"]["text"]):
            assert part["zh"].strip() and part["en"].strip()
        assert q["a"]["emoji"] and q["b"]["emoji"]


def test_cute_dimension_names():
    names = {pole: (d["names"][pole]["zh"], d["names"][pole]["en"]) for d in DIMENSIONS for pole in d["names"]}
    assert names == {
        "E": ("热闹派", "Sunny"), "I": ("安静派", "Cozy"),
        "S": ("务实派", "Grounded"), "N": ("梦想派", "Dreamy"),
        "T": ("小脑袋", "Clever"), "F": ("小心心", "Tender"),
        "J": ("计划控", "Planner"), "P": ("随心走", "Wanderer"),
    }


def test_sixteen_animals_from_the_spec():
    expected = {
        "INTJ": "星图猫头鹰", "INTP": "好奇小浣熊", "ENTJ": "领航狮子", "ENTP": "点子狐狸",
        "INFJ": "月光小鹿", "INFP": "梦想兔兔", "ENFJ": "暖阳金毛", "ENFP": "彩虹水獭",
        "ISTJ": "守护海龟", "ISFJ": "暖心考拉", "ESTJ": "管家企鹅", "ESFJ": "甜心小羊",
        "ISTP": "工匠海狸", "ISFP": "艺术小猫", "ESTP": "冒险袋鼠", "ESFP": "派对凤头鹦鹉",
    }
    assert {code: a["name"]["zh"] for code, a in ANIMALS.items()} == expected
    for code, a in ANIMALS.items():
        for field in ("name", "initial", "trait", "love"):
            assert a[field]["zh"].strip() and a[field]["en"].strip(), (code, field)
        assert len(a["initial"]["zh"]) == 1, code
        assert len(a["tips"]["zh"]) == 2 and len(a["tips"]["en"]) == 2, code
        # "在恋爱里的你"是 2–3 句
        assert 2 <= a["love"]["zh"].count("。") <= 3, code


def test_no_mbti_wording_anywhere():
    # 页面上不能出现 "MBTI"：检查所有内容、文案和模板（JSON 顶部给开发者看的 "_说明" 不算）
    for path in list((ROOT / "content").glob("*.json")) + list((ROOT / "i18n").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("_说明", None)
        assert "mbti" not in json.dumps(data, ensure_ascii=False).lower(), path
    for path in (ROOT / "templates").rglob("*.html"):
        assert "mbti" not in path.read_text(encoding="utf-8").lower(), path


# ---------- 计算结果 ----------


def test_validate_answers():
    validate_answers(ALL_A)
    for bad in (ALL_A[:11], ALL_A + ["a"], ["a"] * 11 + ["c"], "aaaaaaaaaaaa", None):
        with pytest.raises(ValueError):
            validate_answers(bad)


def test_scores_count_each_pole():
    answers = ["a", "a", "b",  "b", "b", "b",  "a", "b", "b",  "a", "a", "a"]
    scores = dimension_scores(QUESTIONS, DIMENSIONS, answers)
    assert scores == {"EI": {"E": 2, "I": 1}, "SN": {"S": 0, "N": 3},
                      "TF": {"T": 1, "F": 2}, "JP": {"J": 3, "P": 0}}
    assert result_code(QUESTIONS, DIMENSIONS, answers) == "ENFJ"


def test_all_a_and_all_b():
    assert result_code(QUESTIONS, DIMENSIONS, ALL_A) == "ESTJ"
    assert result_code(QUESTIONS, DIMENSIONS, ["b"] * 12) == "INFP"


def test_every_answer_pattern_maps_to_a_known_animal():
    # 每个维度 3 题 → 2^3 种答法，共 4096 种答案组合，全部都能对应到 16 种动物之一
    seen = set()
    per_dim = list(product("ab", repeat=3))
    for ei, sn, tf, jp in product(per_dim, repeat=4):
        code = result_code(QUESTIONS, DIMENSIONS, list(ei + sn + tf + jp))
        assert code in ANIMALS
        seen.add(code)
    assert seen == set(ANIMALS)


def test_answers_for_helper_round_trip():
    for code in ANIMALS:
        assert result_code(QUESTIONS, DIMENSIONS, answers_for(code)) == code


# ---------- 你们的组合 ----------


def test_combo_both_cozy_example_from_spec():
    # 规格里的例子：两人都是安静派
    text = combo_text(DIMENSIONS, INTRO, "INFP", "ISFJ")
    assert "你们都喜欢安静的陪伴，一起窝在家里就是最好的约会" in text["zh"]
    assert "You both love quiet company" in text["en"]


def test_combo_identical():
    text = combo_text(DIMENSIONS, INTRO, "ENFP", "ENFP")
    assert text["zh"].startswith("你们是同一种小动物")
    assert text["zh"].count("。") + text["zh"].count("！") == 3  # 三句


def test_combo_opposites():
    text = combo_text(DIMENSIONS, INTRO, "ESTJ", "INFP")
    assert text["zh"].startswith("你们几乎完全相反")
    assert "一个热闹、一个安静" in text["zh"]  # 先说能量
    assert "一个讲道理、一个讲感受" in text["zh"]  # 再说判断
    assert text["en"].startswith("You're almost complete opposites")


def test_combo_mixed_picks_one_same_and_one_different():
    # INTJ vs INFP：能量相同（都安静）、判断不同
    text = combo_text(DIMENSIONS, INTRO, "INTJ", "INFP")
    assert "你们有 2 个地方一模一样" in text["zh"]
    assert "你们都喜欢安静的陪伴" in text["zh"]
    assert "一个讲道理、一个讲感受" in text["zh"]
    assert "You match on 2 of 4 traits" in text["en"]


def test_combo_is_symmetric_and_bilingual():
    for a, b in (("ENFP", "ISTJ"), ("INFJ", "ENFJ"), ("ESTP", "ESFP")):
        ab, ba = combo_text(DIMENSIONS, INTRO, a, b), combo_text(DIMENSIONS, INTRO, b, a)
        assert ab == ba
        assert ab["zh"] and ab["en"]
