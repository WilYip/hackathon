"""M6 初见森林：测试流程、结果页、你们的组合、相遇回忆，以及动物头像应用到全站。"""

import sqlite3

from tests.conftest import put_animal
from tests.test_auth import create_island, invite_code, join_island

# 每个维度 3 题：全选 b → INFP（梦想兔兔）；全选 a → ESTJ（管家企鹅）
INFP = ["b"] * 12
ESTJ = ["a"] * 12
# 能量、感知 b（I、S 需要 a）……ISFJ = I(b) S(a) F(b) J(a)
ISFJ = ["b"] * 3 + ["a"] * 3 + ["b"] * 3 + ["a"] * 3


def form(answers):
    return {f"q{i + 1}": a for i, a in enumerate(answers)}


def take_quiz(client, answers, follow_redirects=False):
    return client.post("/forest/quiz", data=form(answers), follow_redirects=follow_redirects)


def setup_pair(client, partner, app):
    create_island(client, nickname="小雨")
    join_island(partner, invite_code(app), nickname="阿木")


def query(app, sql, *args):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return rows


# ---------- 森林页与测试页 ----------


def test_forest_before_quiz(client, partner, app):
    setup_pair(client, partner, app)
    html = client.get("/forest").get_data(as_text=True)
    assert "森林动物性格测试" in html
    assert "开始测试" in html
    assert html.count("还没走进森林") == 2
    assert "小雨" in html and "阿木" in html
    assert "你们的组合" not in html


def test_quiz_page_one_question_per_step(client, partner, app):
    setup_pair(client, partner, app)
    html = client.get("/forest/quiz").get_data(as_text=True)
    assert html.count('class="wizard-step"') == 12
    assert html.count("data-post=") == 13  # 起点 + 12 个路标（取代原来的进度条）
    assert "第 1 题 / 共 12 题" in html
    assert "我是森林小精灵" in html
    assert "小岛周末开派对，你会……" in html
    assert "第一个冲去，顺便认识新朋友" in html
    assert 'name="q12" value="b"' in html
    assert "mbti" not in html.lower()


def test_incomplete_answers_keep_choices(client, partner, app):
    setup_pair(client, partner, app)
    data = form(INFP)
    del data["q5"]
    resp = client.post("/forest/quiz", data=data)
    assert resp.status_code == 400
    html = resp.get_data(as_text=True)
    assert "还有题目没有回答哦" in html
    assert html.count("checked") == 11  # 已经选好的答案还在
    assert query(app, "SELECT COUNT(*) FROM forest_results")[0][0] == 0


def test_bad_answer_values_are_rejected(client, partner, app):
    setup_pair(client, partner, app)
    data = form(INFP)
    data["q1"] = "c"
    assert client.post("/forest/quiz", data=data).status_code == 400


# ---------- 结果 ----------


def test_result_saved_and_shown(client, partner, app):
    setup_pair(client, partner, app)
    resp = take_quiz(client, INFP)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/forest/result?new=1"
    assert query(app, "SELECT animal_code FROM members WHERE nickname = '小雨'")[0][0] == "INFP"
    assert query(app, "SELECT code FROM forest_results")[0][0] == "INFP"

    html = client.get("/forest/result?new=1").get_data(as_text=True)
    assert "你是……" in html
    assert "梦想兔兔" in html
    assert "浪漫的小诗人，心里有片花田。" in html
    assert "在恋爱里的你" in html and "和你相处的小贴士" in html
    assert "认真对待 TA 的小心思" in html
    assert html.count('class="trait-bar"') == 4
    for name in ("热闹派", "安静派", "务实派", "梦想派", "小脑袋", "小心心", "计划控", "随心走"):
        assert name in html
    assert "result card is-new" in html  # 刚测完：出场动画
    assert "再测一次" in html


def test_trait_bars_show_votes(client, partner, app):
    setup_pair(client, partner, app)
    # 能量 2:1 偏热闹，其余全选 b
    take_quiz(client, ["a", "a", "b"] + ["b"] * 9)
    html = client.get("/forest/result").get_data(as_text=True)
    assert 'style="width: 67%"' in html  # 热闹派 2 票 / 3 票
    assert "彩虹水獭" in html  # ENFP


def test_partner_result_and_combo(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    take_quiz(partner, ISFJ)

    for c in (client, partner):
        html = c.get("/forest").get_data(as_text=True)
        assert "你们的组合" in html
        assert "梦想兔兔" in html and "暖心考拉" in html
        assert "你们都喜欢安静的陪伴，一起窝在家里就是最好的约会" in html

    html = client.get("/forest/result?who=partner").get_data(as_text=True)
    assert "阿木 是……" in html
    assert "暖心考拉" in html
    assert "在恋爱里的 阿木" in html and "和 阿木 相处的小贴士" in html
    assert 'href="/forest/quiz"' not in html  # 看对方的结果时没有"再测一次"


def test_meeting_memory_added_once(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    assert query(app, "SELECT COUNT(*) FROM memories WHERE kind = 'forest'")[0][0] == 0
    resp = take_quiz(partner, ISFJ, follow_redirects=True)
    assert "你们在初见森林相遇啦" in resp.get_data(as_text=True)
    rows = query(app, "SELECT ref FROM memories WHERE kind = 'forest'")
    assert rows == [("INFP,ISFJ",)]  # 按成员加入顺序
    take_quiz(client, ESTJ)  # 重测不会再加一条
    assert query(app, "SELECT COUNT(*) FROM memories WHERE kind = 'forest'")[0][0] == 1


def test_retake_updates_animal(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    take_quiz(client, ESTJ)
    assert query(app, "SELECT animal_code FROM members WHERE nickname = '小雨'")[0][0] == "ESTJ"
    assert "管家企鹅" in client.get("/forest/result").get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) FROM forest_results")[0][0] == 2


def test_result_requires_a_finished_quiz(client, partner, app):
    setup_pair(client, partner, app)
    assert client.get("/forest/result").headers["Location"] == "/forest"
    take_quiz(client, INFP)
    assert client.get("/forest/result?who=partner").headers["Location"] == "/forest"


def test_alone_can_take_quiz(client, app):
    create_island(client)
    html = client.get("/forest").get_data(as_text=True)
    assert "等 TA 加入后就能一起玩啦" in html
    assert "开始测试" in html
    take_quiz(client, INFP)
    assert "梦想兔兔" in client.get("/forest/result").get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) FROM memories")[0][0] == 0


def test_state_version_changes_when_partner_finishes(client, partner, app):
    setup_pair(client, partner, app)
    before = client.get("/api/forest/state").get_json()["version"]
    take_quiz(partner, ISFJ)
    assert client.get("/api/forest/state").get_json()["version"] != before


def test_requires_login_and_same_origin(raw_client):
    assert raw_client.get("/forest").status_code == 302
    assert raw_client.get("/api/forest/state").status_code == 401
    assert raw_client.post("/forest/quiz", data=form(INFP)).status_code == 403


def test_english_result(client, partner, app):
    setup_pair(client, partner, app)
    client.post("/lang", data={"lang": "en", "next": "/"})
    take_quiz(client, INFP)
    html = client.get("/forest/result").get_data(as_text=True)
    assert "Dreamy Bunny" in html
    assert "Tips for getting along with you" in html
    assert "Sunny" in html and "Cozy" in html


# ---------- 动物头像应用到全站 ----------


PLACEHOLDER = "/static/usland/assets/ui/placeholders/avatar_placeholder.svg"
RESULT_INFP = "/static/usland/assets/animals/result/infp.png"


def test_placeholder_uses_animal_initial_everywhere(client, partner, app):
    # 结果立绘缺失：做完测试后，占位头像上写动物名首字（梦想兔兔 → 兔）
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    for url in ("/", "/whisper", "/forest", "/quest"):
        html = client.get(url).get_data(as_text=True)
        assert 'title="梦想兔兔">兔</span>' in html, url
    # 对方还没测：第三版的中性占位头像（不显示任何人格动物）
    assert PLACEHOLDER in client.get("/").get_data(as_text=True)


def test_animal_images_everywhere(client, partner, app, raw_client):
    put_animal(app, "result", "infp")
    setup_pair(client, partner, app)
    take_quiz(client, INFP)

    for c in (client, partner):
        for url in ("/", "/whisper", "/forest"):
            html = c.get(url).get_data(as_text=True)
            assert RESULT_INFP in html, url  # 小雨：测出来的梦想兔兔
            assert PLACEHOLDER in html, url  # 阿木：还没测，中性占位头像

    # 首页：小雨站在野餐垫左边，阿木还没测，右边是占位剪影
    home = client.get("/").get_data(as_text=True)
    assert "player_slot_right.svg" in home
    assert "player_slot_left.svg" not in home
    # 约会选选选：等待页上的小动物
    client.post("/quest/start")
    client.post("/quest/choose", data={"time": "1h", "budget": "free", "mood": "tired", "want": "memory"})
    assert RESULT_INFP in client.get("/quest").get_data(as_text=True)
    # 登录页
    client.post("/logout")
    assert RESULT_INFP in client.get("/login").get_data(as_text=True)


def test_no_personality_animal_before_quiz(client, partner, app):
    # 有结果立绘，但两人都还没测：任何页面都不出现人格动物，只有中性占位
    for code in ("infp", "estj"):
        put_animal(app, "result", code)
    setup_pair(client, partner, app)
    for url in ("/", "/whisper", "/forest", "/quest"):
        html = client.get(url).get_data(as_text=True)
        assert "animals/result/" not in html, url
        assert PLACEHOLDER in html, url
    home = client.get("/").get_data(as_text=True)
    assert "player_slot_left.svg" in home and "player_slot_right.svg" in home
