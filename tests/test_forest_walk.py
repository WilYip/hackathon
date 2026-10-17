"""初见森林的互动：森林散步测试页、小精灵回应、森林发现、灌木丛揭晓、猜猜 TA 是哪只小动物。"""

import json

from routes.forest import walk_path, walk_points
from services import content
from services.forest import matching_traits
from tests.test_forest import INFP, ISFJ, query, setup_pair, take_quiz
from tests.test_auth import create_island

# ---------- 内容：每个选项都有小精灵的回应，每个维度都有森林发现 ----------


def test_every_option_has_spirit_reply():
    quiz = content.load("quiz")
    replies = set()
    for q in quiz["questions"]:
        for key in ("a", "b"):
            reply = q[key]["spirit"]
            assert reply["zh"].strip() and reply["en"].strip()
            replies.add(reply["zh"])
    assert len(replies) == 24  # 每个选项的回应都不一样


def test_every_dimension_has_discovery():
    for d in content.load("quiz")["dimensions"]:
        for pole in (d["first"], d["second"]):
            text = d["discovery"][pole]
            assert text["zh"].strip() and text["en"].strip()


def test_questions_grouped_by_dimension():
    # 森林发现每 3 题弹一次：同一个维度的 3 题必须挨在一起
    dims = [q["dimension"] for q in content.load("quiz")["questions"]]
    assert dims == ["EI"] * 3 + ["SN"] * 3 + ["TF"] * 3 + ["JP"] * 3


# ---------- 纯函数：小路 ----------


def test_walk_points_trailhead_plus_signposts():
    points = walk_points(12)
    assert len(points) == 13  # 起点 + 12 个路标
    xs = [p["x"] for p in points]
    assert xs == sorted(xs) and xs[0] >= 0 and xs[-1] <= 100  # 从左到右，不出画面
    assert all(0 <= p["y"] <= 100 for p in points)


def test_walk_path_passes_every_point():
    points = walk_points(12)
    path = walk_path(points)
    assert path.startswith(f"M {points[0]['x']} {points[0]['y']}")
    assert path.count(" C ") == 12
    for p in points[1:]:
        assert f"{p['x']} {p['y']}" in path


def test_matching_traits():
    assert matching_traits("INFP", "INFP") == 4
    assert matching_traits("INFP", "ESTJ") == 0
    assert matching_traits("INFP", "ISFJ") == 2


# ---------- 测试页 ----------


def test_quiz_page_is_a_forest_walk(client, partner, app):
    setup_pair(client, partner, app)
    html = client.get("/forest/quiz").get_data(as_text=True)
    assert "data-walk" in html and "data-walker" in html
    assert html.count('data-post=') == 13
    assert "第 1 题 / 共 12 题" in html  # 保留文字进度
    assert "footprints" not in html  # 原来的进度条已经去掉
    # 小精灵的回应写在选项上；森林发现的文案在页面里
    assert 'data-reply="哇，派对小火箭出发！记得给我留块蛋糕～"' in html
    assert 'data-pole="E"' in html and 'data-pole="I"' in html
    discoveries = html.split('<script type="application/json" id="discoveries">')[1].split("</script>")[0]
    data = json.loads(discoveries)
    assert data["EI"]["poles"]["E"]["name"] == "热闹派"
    assert "小太阳" in data["EI"]["poles"]["E"]["text"]
    # 两种点击小动画 + 跳过按钮 + 森林发现卡片
    assert "effect-fruit" in html and "effect-door" in html
    assert "data-skip" in html and 'id="discovery"' in html


def test_quiz_page_english(client, partner, app):
    setup_pair(client, partner, app)
    client.post("/lang", data={"lang": "en", "next": "/"})
    html = client.get("/forest/quiz").get_data(as_text=True)
    assert "Whoosh, party rocket launched!" in html
    assert "Question 1 of 12" in html
    assert "Forest discovery" in html


# ---------- 结果揭晓：灌木丛 ----------


def test_new_result_hides_behind_bush(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    html = client.get("/forest/result?new=1").get_data(as_text=True)
    assert "data-bush" in html and "data-reveal-skip" in html
    assert "forest_reveal.js" in html
    # 揭晓前标题里不写动物名
    title = html.split("<title>")[1].split("</title>")[0]
    assert "梦想兔兔" not in title
    # 没有 JavaScript 时结果直接在页面上
    assert "梦想兔兔" in html

    # 不是刚测完：没有灌木丛
    html = client.get("/forest/result").get_data(as_text=True)
    assert "data-bush" not in html
    assert "梦想兔兔" in html.split("<title>")[1].split("</title>")[0]


# ---------- 猜猜 TA 是哪只小动物 ----------


def guess(client, code):
    return client.post("/forest/guess", data={"code": code})


def test_guess_card_only_after_own_result_before_partner(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    html = client.get("/forest/result").get_data(as_text=True)
    assert "猜猜 阿木 会是哪只小动物？" in html
    assert html.count('name="code"') == 16

    # 看对方的结果页、对方已经测完：都没有猜猜看
    take_quiz(partner, ISFJ)
    html = client.get("/forest/result").get_data(as_text=True)
    assert 'name="code"' not in html


def test_cannot_guess_before_own_result_or_alone(client, partner, app):
    create_island(client, nickname="小雨")
    take_quiz(client, INFP)
    assert guess(client, "ISFJ").status_code == 302
    assert query(app, "SELECT COUNT(*) FROM forest_guesses")[0][0] == 0  # 另一半还没加入

    from tests.test_auth import invite_code, join_island
    join_island(partner, invite_code(app), nickname="阿木")
    guess(partner, "INFP")  # 阿木自己还没测
    assert query(app, "SELECT COUNT(*) FROM forest_guesses")[0][0] == 0
    guess(client, "XXXX")  # 没有这种动物
    assert query(app, "SELECT COUNT(*) FROM forest_guesses")[0][0] == 0


def test_guess_can_change_before_reveal(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    resp = guess(client, "ESTJ")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/forest")
    guess(client, "ISFJ")
    assert query(app, "SELECT code, actual_code FROM forest_guesses") == [("ISFJ", None)]

    html = client.get("/forest").get_data(as_text=True)
    assert "你猜 阿木 是「暖心考拉」，等 TA 测完就揭晓。" in html
    # 对方只知道被猜了，不知道猜的是什么
    html = partner.get("/forest").get_data(as_text=True)
    assert "小雨 已经猜了你是哪只小动物" in html
    assert "暖心考拉" not in html


def test_guess_revealed_when_partner_finishes(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    guess(client, "ISFJ")
    html = take_quiz(partner, ISFJ, follow_redirects=True).get_data(as_text=True)
    assert "小雨 之前猜过你是哪只小动物" in html

    assert query(app, "SELECT code, actual_code FROM forest_guesses") == [("ISFJ", "ISFJ")]
    for c in (client, partner):
        html = c.get("/forest").get_data(as_text=True)
        assert "猜猜看揭晓" in html
        assert "小雨 猜 阿木 是「暖心考拉」，猜中啦！" in html

    # 回忆小屋多了一条"猜猜看"（由猜的人记录）
    rows = query(app, "SELECT kind, ref, created_by FROM memories WHERE kind = 'forest_guess'")
    assert rows == [("forest_guess", "ISFJ,ISFJ", 1)]
    html = client.get("/memories").get_data(as_text=True)
    assert "一猜就中！" in html
    assert "猜的是 暖心考拉，其实是 暖心考拉" in html


def test_wrong_guess_shows_matching_traits(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    guess(client, "INFP")
    take_quiz(partner, ISFJ)
    html = client.get("/forest").get_data(as_text=True)
    assert "小雨 猜 阿木 是「梦想兔兔」，其实是「暖心考拉」。" in html
    assert "四个小特点里猜中了 2 个。" in html
    html = client.get("/memories").get_data(as_text=True)
    assert "差一点就猜中了" in html

    # 重测不会再记一条
    take_quiz(partner, INFP)
    assert query(app, "SELECT COUNT(*) FROM memories WHERE kind = 'forest_guess'")[0][0] == 1


def test_guess_memory_in_english(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    guess(client, "ISFJ")
    take_quiz(partner, ISFJ)
    client.post("/lang", data={"lang": "en", "next": "/"})
    html = client.get("/memories").get_data(as_text=True)
    assert "Guessed it in one!" in html
    assert "Guessing game" in html
