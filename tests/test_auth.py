"""M2 账号与小岛测试：创建、邀请码、加入、登录、PIN 锁定、退出、等待状态。"""

import sqlite3
from datetime import datetime, timedelta, timezone

from services.auth import INVITE_ALPHABET, generate_invite_code


def create_island(client, name="椰子岛", nickname="小雨", pin="1234", lang="zh"):
    return client.post(
        "/create",
        data={"island_name": name, "nickname": nickname, "pin": pin, "pin_confirm": pin, "lang": lang},
    )


def invite_code(app):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    code = conn.execute("SELECT invite_code FROM island").fetchone()[0]
    conn.close()
    return code


def join_island(client, code, nickname="阿木", pin="5678"):
    return client.post(
        "/join", data={"invite_code": code, "nickname": nickname, "pin": pin, "pin_confirm": pin}
    )


def member_id(app, nickname):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    row = conn.execute("SELECT id FROM members WHERE nickname = ?", (nickname,)).fetchone()
    conn.close()
    return row[0]


# ---------- 邀请码 ----------


def test_invite_code_format():
    for _ in range(200):
        code = generate_invite_code()
        assert len(code) == 6
        assert all(ch in INVITE_ALPHABET for ch in code)
        assert not set(code) & set("0O1I")


# ---------- 创建 ----------


def test_create_island_logs_in_and_shows_invite(client, app):
    resp = create_island(client)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/invite"

    html = client.get("/invite").get_data(as_text=True)
    assert invite_code(app) in html
    assert "小岛建好啦" in html

    # 首页显示等待 TA 的提示和邀请码
    home = client.get("/").get_data(as_text=True)
    assert "等 TA 加入后就能一起玩啦" in home
    assert invite_code(app) in home


def test_pin_is_hashed(client, app):
    create_island(client, pin="1234")
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    pin_hash = conn.execute("SELECT pin_hash FROM members").fetchone()[0]
    conn.close()
    assert pin_hash != "1234"


def test_create_validation_errors(client):
    html = create_island(client, pin="12").get_data(as_text=True)
    assert "PIN 需要是 4–6 位数字" in html

    resp = client.post(
        "/create",
        data={"island_name": "岛", "nickname": "小雨", "pin": "1234", "pin_confirm": "4321", "lang": "zh"},
    )
    assert "两次输入的 PIN 不一样" in resp.get_data(as_text=True)

    html = create_island(client, name="").get_data(as_text=True)
    assert "请填写小岛名" in html


def test_create_language_is_saved(client):
    create_island(client, lang="en")
    html = client.get("/invite").get_data(as_text=True)
    assert "Your island is ready!" in html


def test_cannot_create_second_island(client, partner):
    create_island(client)
    resp = create_island(partner, name="第二座岛")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login"


# ---------- 加入 ----------


def test_join_with_wrong_code(client, partner):
    create_island(client)
    html = join_island(partner, "ZZZZZZ").get_data(as_text=True)
    assert "邀请码不正确" in html


def test_join_success_lowercase_code(client, partner, app):
    create_island(client)
    resp = join_island(partner, invite_code(app).lower())
    assert resp.status_code == 302

    # 加入后直接进入小岛地图，两只动物下方显示两人的昵称，不再显示等待横幅
    home = partner.get("/").get_data(as_text=True)
    assert "data-map-stage" in home
    assert "小雨" in home and "阿木" in home
    assert "等 TA 加入后" not in home


def test_join_nickname_must_differ(client, partner, app):
    create_island(client, nickname="小雨")
    html = join_island(partner, invite_code(app), nickname="小雨").get_data(as_text=True)
    assert "这个昵称已经被 TA 用了" in html


def test_third_person_cannot_join(client, partner, app):
    create_island(client)
    code = invite_code(app)
    join_island(partner, code)

    third = app.test_client()
    third.environ_base["HTTP_ORIGIN"] = "http://localhost"
    html = join_island(third, code, nickname="路人").get_data(as_text=True)
    assert "小岛已经住满啦" in html
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    assert conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 2
    conn.close()


def test_status_api_for_waiting(client, partner, app):
    create_island(client)
    assert client.get("/api/island/status").get_json() == {"member_count": 1}
    join_island(partner, invite_code(app))
    assert client.get("/api/island/status").get_json() == {"member_count": 2}


# ---------- 登录 / 退出 ----------


def test_logout_requires_post(client):
    create_island(client)
    assert client.get("/logout").status_code == 405
    resp = client.post("/logout")
    assert resp.status_code == 302
    # 退出后首页跳到登录页
    assert client.get("/").headers["Location"] == "/login"


def test_login_success(client, app):
    create_island(client)
    client.post("/logout")
    resp = client.post("/login", data={"member_id": member_id(app, "小雨"), "pin": "1234"})
    assert resp.status_code == 302
    home = client.get("/").get_data(as_text=True)
    assert "data-map-stage" in home
    assert "小雨" in home


def test_login_wrong_pin_then_lock(client, app):
    create_island(client)
    client.post("/logout")
    mid = member_id(app, "小雨")

    for left in (4, 3, 2, 1):
        html = client.post("/login", data={"member_id": mid, "pin": "0000"}).get_data(as_text=True)
        assert f"还可以再试 {left} 次" in html

    # 第 5 次错误：锁定
    html = client.post("/login", data={"member_id": mid, "pin": "0000"}).get_data(as_text=True)
    assert "5 分钟后再试" in html

    # 锁定期间即使 PIN 正确也不能登录
    resp = client.post("/login", data={"member_id": mid, "pin": "1234"})
    assert resp.status_code == 200
    assert "分钟后再试" in resp.get_data(as_text=True)


def test_lock_expires(client, app):
    create_island(client)
    client.post("/logout")
    mid = member_id(app, "小雨")
    for _ in range(5):
        client.post("/login", data={"member_id": mid, "pin": "0000"})

    # 把锁定时间改到过去，模拟 5 分钟已经过去
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("UPDATE members SET locked_until = ?", (past,))
    conn.commit()
    conn.close()

    resp = client.post("/login", data={"member_id": mid, "pin": "1234"})
    assert resp.status_code == 302


def test_success_resets_failed_count(client, app):
    create_island(client)
    client.post("/logout")
    mid = member_id(app, "小雨")
    for _ in range(3):
        client.post("/login", data={"member_id": mid, "pin": "0000"})
    client.post("/login", data={"member_id": mid, "pin": "1234"})
    client.post("/logout")
    html = client.post("/login", data={"member_id": mid, "pin": "0000"}).get_data(as_text=True)
    assert "还可以再试 4 次" in html


def test_login_page_lists_members_and_join_link(client, partner, app):
    create_island(client)
    html = partner.get("/login").get_data(as_text=True)
    assert "小雨" in html
    assert "用邀请码加入小岛" in html

    join_island(partner, invite_code(app))
    partner.post("/logout")
    html = partner.get("/login").get_data(as_text=True)
    assert "阿木" in html
    assert "用邀请码加入小岛" not in html


def test_session_cookie_flags(client):
    resp = create_island(client)
    cookie = resp.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


# ---------- 语言偏好 ----------


def test_logged_in_language_saved_to_database(client, app):
    create_island(client, lang="zh")
    client.post("/lang", data={"lang": "en", "next": "/"})
    # 换一个没有 lang Cookie 的浏览器登录，仍然是英文
    other = app.test_client()
    other.environ_base["HTTP_ORIGIN"] = "http://localhost"
    other.post("/login", data={"member_id": member_id(app, "小雨"), "pin": "1234"})
    html = other.get("/").get_data(as_text=True)
    # 地图上的入口标签是英文
    assert 'lang="en"' in html
    assert "Whisper Pier" in html


def test_protected_pages_redirect_when_logged_out(raw_client):
    assert raw_client.get("/invite").status_code == 302
    assert raw_client.get("/api/island/status").status_code == 302
