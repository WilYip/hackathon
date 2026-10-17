"""M5 约会选选选：完整流程（两个浏览器 = 两个测试客户端）。
重点：选择在双方提交前保密；"已提议 / 等待确认 / 已共同确定"三种状态清楚区分；照片校验与登录保护。"""

import io
import json
import sqlite3

from PIL import Image

import db as db_module
from services import content
from tests.test_auth import create_island, invite_code, join_island

STRICT = {"time": "15min", "budget": "free", "mood": "tired", "want": "quiet_time"}


def setup_pair(client, partner, app):
    create_island(client, nickname="小雨")
    join_island(partner, invite_code(app), nickname="阿木")


def query(app, sql, *args):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return rows


def current_round(app):
    return query(app, "SELECT * FROM quest_rounds ORDER BY id DESC LIMIT 1")[0]


def choose(client, follow_redirects=False, **overrides):
    data = dict(STRICT, **overrides)
    return client.post("/quest/choose", data=data, follow_redirects=follow_redirects)


def to_deciding(client, partner, app):
    """开始一轮，双方都选完，返回 3 个推荐任务 id。"""
    setup_pair(client, partner, app)
    client.post("/quest/start")
    choose(client)
    choose(partner, mood="chatty", want="deep_talk")
    recs = json.loads(current_round(app)["recommendations"])
    return [r["task_id"] for r in recs]


def to_confirmed(client, partner, app):
    ids = to_deciding(client, partner, app)
    client.post("/quest/propose", data={"task_id": ids[0]})
    partner.post("/quest/agree", data={"task_id": ids[0]})
    return ids[0]


def photo_bytes(fmt="JPEG", size=(300, 200)):
    buf = io.BytesIO()
    Image.new("RGB", size, (240, 180, 200)).save(buf, fmt)
    return buf.getvalue()


def page(client):
    return client.get("/quest").get_data(as_text=True)


# ---------- 开始 ----------


def test_alone_shows_waiting(client):
    create_island(client)
    html = page(client)
    assert "等 TA 加入后就能一起玩啦" in html
    client.post("/quest/start")
    assert query(client.application, "SELECT COUNT(*) AS n FROM quest_rounds")[0]["n"] == 0


def test_only_one_active_round(client, partner, app):
    setup_pair(client, partner, app)
    assert "开始新的约会冒险" in page(client)
    client.post("/quest/start")
    partner.post("/quest/start")  # 对方同时点：不会开出第二轮
    assert query(app, "SELECT COUNT(*) AS n FROM quest_rounds")[0]["n"] == 1
    html = page(client)
    assert "第 1 步 / 共 4 步" in html
    for question in ("今天有多少时间？", "预算多少？", "你现在的状态？", "今天想要什么？"):
        assert question in html


# ---------- 各自选择（保密） ----------


def test_choice_validation(client, partner, app):
    setup_pair(client, partner, app)
    client.post("/quest/start")
    resp = client.post("/quest/choose", data={"time": "1h", "budget": "free"}, follow_redirects=True)
    assert "四个问题都要选哦" in resp.get_data(as_text=True)
    resp = choose(client, time="3h", follow_redirects=True)  # 不存在的选项
    assert "四个问题都要选哦" in resp.get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) AS n FROM quest_choices")[0]["n"] == 0


def test_choices_stay_secret_until_both_submit(client, partner, app):
    setup_pair(client, partner, app)
    client.post("/quest/start")
    choose(client, mood="adventurous", want="memory")

    # 自己：等待页，写着在等谁
    mine = page(client)
    assert "告示牌在等 阿木 的选择" in mine
    assert "choices-summary" not in mine

    # 对方：只知道"已经选好了"，看不到选了什么
    theirs = page(partner)
    assert "小雨 已经选好啦，就差你了" in theirs
    assert "choices-summary" not in theirs
    assert "choice-chips" not in theirs
    state = partner.get("/api/quest/state").get_json()
    assert set(state) == {"version", "done_url"}  # 接口里没有任何选择内容
    assert "adventurous" not in json.dumps(state)


def test_cannot_choose_twice(client, partner, app):
    setup_pair(client, partner, app)
    client.post("/quest/start")
    choose(client)
    resp = choose(client, mood="bored", follow_redirects=True)
    assert "你已经选好啦" in resp.get_data(as_text=True)
    assert query(app, "SELECT mood FROM quest_choices")[0]["mood"] == "tired"


def test_both_submitted_gives_three_recommendations(client, partner, app):
    ids = to_deciding(client, partner, app)
    row = current_round(app)
    assert row["status"] == "deciding"
    recs = json.loads(row["recommendations"])
    assert len(recs) == 3 and len(set(ids)) == 3
    # 双方都选了"15 分钟 + 免费"：推荐的任务都在条件内
    tasks = {t["id"]: t for t in content.load("tasks")["tasks"]}
    for task_id in ids:
        assert tasks[task_id]["duration"] <= 15
        assert tasks[task_id]["budget"] == "free"
    for r in recs:
        assert r["reason"]["zh"].startswith("推荐它，因为")
        assert r["reason"]["en"].startswith("We picked it because")

    # 双方都提交后，可以互相看到对方的选择
    for c in (client, partner):
        html = page(c)
        assert html.count('class="task-card') == 3
        assert "你们的选择" in html
        assert "想聊天" in html and "疲惫" in html
        assert "推荐它，因为" in html


# ---------- 共同选择：三种状态 ----------


def test_proposal_states_are_distinct(client, partner, app):
    ids = to_deciding(client, partner, app)
    client.post("/quest/propose", data={"task_id": ids[0]})

    # 提议的人：已提议，等待对方确认
    mine = page(client)
    assert "badge-proposed" in mine and "已提议" in mine and "等待 阿木 确认" in mine
    assert "你提议了「" in mine
    assert "badge-waiting" not in mine
    assert "badge-confirmed" not in mine
    assert 'action="/quest/agree"' not in mine  # 不能同意自己的提议

    # 对方：等待你确认，有"同意"按钮
    theirs = page(partner)
    assert "badge-waiting" in theirs and "等待你确认" in theirs and "小雨 提议了这个" in theirs
    assert 'action="/quest/agree"' in theirs
    assert "badge-proposed" not in theirs
    assert "badge-confirmed" not in theirs


def test_proposer_cannot_agree_to_own_proposal(client, partner, app):
    ids = to_deciding(client, partner, app)
    client.post("/quest/propose", data={"task_id": ids[0]})
    resp = client.post("/quest/agree", data={"task_id": ids[0]}, follow_redirects=True)
    assert "状态刚刚变了" in resp.get_data(as_text=True)
    assert current_round(app)["status"] == "deciding"


def test_counter_proposal_replaces_the_old_one(client, partner, app):
    ids = to_deciding(client, partner, app)
    client.post("/quest/propose", data={"task_id": ids[0]})
    partner.post("/quest/propose", data={"task_id": ids[1]})  # 对方改选另一个
    row = current_round(app)
    assert row["proposed_task_id"] == ids[1]
    assert row["status"] == "deciding"
    # 现在轮到小雨确认
    assert "badge-waiting" in page(client)
    assert "badge-proposed" in page(partner)
    # 旧提议已经失效：同意旧的会提示状态变了
    resp = partner.post("/quest/agree", data={"task_id": ids[0]}, follow_redirects=True)
    assert "状态刚刚变了" in resp.get_data(as_text=True)


def test_agree_confirms_for_both(client, partner, app):
    task_id = to_confirmed(client, partner, app)
    row = current_round(app)
    assert row["status"] == "confirmed"
    assert row["confirmed_task_id"] == task_id
    for c in (client, partner):
        html = page(c)
        assert "badge-confirmed" in html and "已共同确定" in html
        assert "我们完成啦！" in html
        assert "badge-proposed" not in html and "badge-waiting" not in html
        assert 'action="/quest/propose"' not in html


def test_propose_unknown_task(client, partner, app):
    to_deciding(client, partner, app)
    resp = client.post("/quest/propose", data={"task_id": "not_a_task"}, follow_redirects=True)
    assert "这个任务不在推荐里" in resp.get_data(as_text=True)


# ---------- 完成：一句回忆 + 照片 ----------


def test_complete_with_photo(client, partner, app, raw_client):
    task_id = to_confirmed(client, partner, app)
    resp = client.post(
        "/quest/complete",
        data={"note": "原来你小时候最喜欢的是机器猫", "photo": (io.BytesIO(photo_bytes("PNG", (2000, 1000))), "us.png")},
        content_type="multipart/form-data",
    )
    round_id = current_round(app)["id"]
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/quest?done={round_id}"

    memory = query(app, "SELECT * FROM memories WHERE kind = 'quest'")[0]
    assert memory["ref"] == task_id
    assert memory["note"] == "原来你小时候最喜欢的是机器猫"
    photo_path = app.config["UPLOAD_DIR"] / memory["photo"]
    with Image.open(photo_path) as im:
        assert im.format == "JPEG" and max(im.size) == 1280
    assert current_round(app)["status"] == "completed"

    # 庆祝页：回忆和照片
    html = client.get(f"/quest?done={round_id}").get_data(as_text=True)
    assert "冒险完成！" in html and "data-confetti" in html
    assert "原来你小时候最喜欢的是机器猫" in html
    assert f"/media/{memory['photo']}" in html
    assert 'href="/memories"' in html

    # 另一半的页面会跳到同一个庆祝页
    assert partner.get("/api/quest/state").get_json()["done_url"] == f"/quest?done={round_id}"
    # 照片：双方登录后能看，未登录不能看
    assert partner.get(f"/media/{memory['photo']}").status_code == 200
    assert raw_client.get(f"/media/{memory['photo']}").status_code == 403


def test_complete_without_photo(client, partner, app):
    to_confirmed(client, partner, app)
    client.post("/quest/complete", data={"note": "一起散步好开心"}, content_type="multipart/form-data")
    memory = query(app, "SELECT * FROM memories")[0]
    assert memory["photo"] is None
    assert current_round(app)["status"] == "completed"


def test_complete_validation_keeps_text(client, partner, app):
    to_confirmed(client, partner, app)
    resp = client.post("/quest/complete", data={"note": "  "}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "写一句回忆吧" in resp.get_data(as_text=True)

    resp = client.post("/quest/complete", data={"note": "字" * 141}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "最多 140 个字" in resp.get_data(as_text=True)

    # 格式不对：GIF；写好的文字保留在表单里
    gif = io.BytesIO(photo_bytes("GIF"))
    resp = client.post("/quest/complete", data={"note": "保留我", "photo": (gif, "a.gif")},
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    html = resp.get_data(as_text=True)
    assert "只支持 jpg、png、webp" in html
    assert "保留我" in html

    # 扩展名是 .jpg，内容不是图片
    resp = client.post("/quest/complete", data={"note": "a", "photo": (io.BytesIO(b"not an image"), "x.jpg")},
                       content_type="multipart/form-data")
    assert "这张照片打不开" in resp.get_data(as_text=True)

    # 超过 5MB（但小于请求上限 6MB）
    big = io.BytesIO(b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024 + 10))
    resp = client.post("/quest/complete", data={"note": "a", "photo": (big, "big.jpg")},
                       content_type="multipart/form-data")
    assert "照片不能超过 5MB" in resp.get_data(as_text=True)

    assert query(app, "SELECT COUNT(*) AS n FROM memories")[0]["n"] == 0
    assert list(app.config["UPLOAD_DIR"].iterdir()) == []  # 不合格的照片不会留在服务器上
    assert current_round(app)["status"] == "confirmed"


def test_request_over_size_limit_is_friendly(client, partner, app):
    to_confirmed(client, partner, app)
    huge = io.BytesIO(b"0" * (7 * 1024 * 1024))  # 超过整个请求的上限 6MB
    resp = client.post("/quest/complete", data={"note": "a", "photo": (huge, "huge.jpg")},
                       content_type="multipart/form-data", headers={"Referer": "http://localhost/quest"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "http://localhost/quest"
    assert "照片不能超过 5MB" in client.get("/quest").get_data(as_text=True)


def test_complete_requires_confirmed(client, partner, app):
    to_deciding(client, partner, app)
    resp = client.post("/quest/complete", data={"note": "太早了"}, content_type="multipart/form-data",
                       follow_redirects=True)
    assert "状态刚刚变了" in resp.get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) AS n FROM memories")[0]["n"] == 0


def test_completed_task_counts_as_recent(client, partner, app):
    task_id = to_confirmed(client, partner, app)
    client.post("/quest/complete", data={"note": "好玩"}, content_type="multipart/form-data")
    with app.test_request_context():
        from services import quest as quest_service
        assert quest_service.recent_task_ids() == {task_id}


# ---------- 结束一轮、轮询、首页提示 ----------


def test_cancel_round_then_start_again(client, partner, app):
    to_deciding(client, partner, app)
    resp = partner.post("/quest/cancel", follow_redirects=True)
    assert "这一轮已经结束" in resp.get_data(as_text=True)
    assert current_round(app)["status"] == "cancelled"
    client.post("/quest/start")
    assert current_round(app)["status"] == "choosing"


def test_version_changes_with_each_step(client, partner, app):
    setup_pair(client, partner, app)
    seen = [client.get("/api/quest/state").get_json()["version"]]
    client.post("/quest/start")
    seen.append(client.get("/api/quest/state").get_json()["version"])
    choose(client)
    seen.append(client.get("/api/quest/state").get_json()["version"])
    choose(partner)
    seen.append(client.get("/api/quest/state").get_json()["version"])
    ids = json.loads(current_round(app)["recommendations"])
    client.post("/quest/propose", data={"task_id": ids[0]["task_id"]})
    seen.append(client.get("/api/quest/state").get_json()["version"])
    assert len(set(seen)) == len(seen)


def test_map_badges(client, partner, app):
    setup_pair(client, partner, app)
    client.post("/quest/start")
    assert "轮到你选啦" in partner.get("/").get_data(as_text=True)
    choose(client)
    assert "轮到你选啦" not in client.get("/").get_data(as_text=True)  # 自己选完了
    choose(partner)
    ids = json.loads(current_round(app)["recommendations"])
    client.post("/quest/propose", data={"task_id": ids[0]["task_id"]})
    assert "TA 提议了任务" in partner.get("/").get_data(as_text=True)
    assert "TA 提议了任务" not in client.get("/").get_data(as_text=True)


def test_requires_login(raw_client):
    assert raw_client.get("/quest").status_code == 302
    assert raw_client.get("/api/quest/state").status_code == 401


def test_old_database_gets_new_column(tmp_path):
    # M4 时建的 memories 表没有 ref 列：启动时会自动补上
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT, note TEXT, "
                 "photo TEXT, created_by INTEGER, created_at TEXT)")
    conn.commit()
    conn.close()
    db_module.init_db(path)
    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    conn.close()
    assert "ref" in columns
