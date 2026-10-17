"""登录页新增功能的测试：修改 PIN、忘记 PIN（另一半生成的重置码）、创建新角色、
登录前切换语言、加入 / 创建小岛页的返回按钮、默认形象。"""

import re
import sqlite3
from datetime import datetime, timedelta, timezone

from test_auth import create_island, invite_code, join_island, member_id


def db_row(app, sql, *args):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    row = conn.execute(sql, args).fetchone()
    conn.close()
    return row


def db_run(app, sql, *args):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute(sql, args)
    conn.commit()
    conn.close()


def two_islanders(client, partner, app):
    """小雨（PIN 1234）创建小岛，阿木（PIN 5678）加入；两人都退出登录。"""
    create_island(client)
    join_island(partner, invite_code(app))
    client.post("/logout")
    partner.post("/logout")


def login(client, app, nickname, pin):
    return client.post("/login", data={"member_id": member_id(app, nickname), "pin": pin})


def new_reset_code(app, giver, for_nickname):
    """giver 登录后在小信箱生成重置码，返回页面上显示的码。"""
    giver.post("/settings/reset-code")
    html = giver.get("/settings").get_data(as_text=True)
    match = re.search(r'<code class="reset-code">([A-Z0-9]+)</code>', html)
    assert match, "设置页应该显示刚生成的重置码"
    assert f"给 {for_nickname} 的重置码" in html
    return match.group(1)


# ---------- 登录页入口 ----------


def test_login_page_has_new_links(client, app):
    create_island(client)
    client.post("/logout")
    html = client.get("/login").get_data(as_text=True)
    assert 'href="/pin/forgot"' in html and "忘记 PIN？" in html
    assert 'href="/pin/change"' in html and "修改 PIN" in html
    assert 'href="/character/new"' in html and "创建新角色" in html


def test_new_pages_need_island_and_logged_out(client, raw_client):
    # 还没有小岛：跳回首页（欢迎页）
    for path in ("/pin/change", "/pin/forgot", "/character/new"):
        assert raw_client.get(path).headers["Location"] == "/"
    # 已登录：也跳回首页
    create_island(client)
    for path in ("/pin/change", "/pin/forgot", "/character/new"):
        assert client.get(path).headers["Location"] == "/"


# ---------- 修改 PIN ----------


def test_change_pin(client, app):
    create_island(client)
    client.post("/logout")
    mid = member_id(app, "小雨")
    resp = client.post("/pin/change", data={"member_id": mid, "current_pin": "1234",
                                            "pin": "246810", "pin_confirm": "246810"})
    assert resp.headers["Location"] == "/login"
    assert "PIN 已经换好啦" in client.get("/login").get_data(as_text=True)

    assert login(client, app, "小雨", "1234").status_code == 200  # 旧 PIN 不能用了
    assert login(client, app, "小雨", "246810").status_code == 302


def test_change_pin_errors(client, app):
    create_island(client)
    client.post("/logout")
    mid = member_id(app, "小雨")
    html = client.post("/pin/change", data={"current_pin": "1234", "pin": "2468", "pin_confirm": "2468"}).get_data(as_text=True)
    assert "请先选择你是谁" in html
    html = client.post("/pin/change", data={"member_id": mid, "current_pin": "1234",
                                            "pin": "12", "pin_confirm": "12"}).get_data(as_text=True)
    assert "4–6 位数字" in html
    html = client.post("/pin/change", data={"member_id": mid, "current_pin": "1234",
                                            "pin": "2468", "pin_confirm": "2469"}).get_data(as_text=True)
    assert "两次输入的 PIN 不一样" in html
    # 新 PIN 写错不算错误次数；现在的 PIN 错了才算
    html = client.post("/pin/change", data={"member_id": mid, "current_pin": "0000",
                                            "pin": "2468", "pin_confirm": "2468"}).get_data(as_text=True)
    assert "还可以再试 4 次" in html
    assert login(client, app, "小雨", "1234").status_code == 302  # 没有被改掉


def test_change_pin_shares_lock_with_login(client, app):
    create_island(client)
    client.post("/logout")
    mid = member_id(app, "小雨")
    for _ in range(5):
        client.post("/pin/change", data={"member_id": mid, "current_pin": "0000", "pin": "2468", "pin_confirm": "2468"})
    html = login(client, app, "小雨", "1234").get_data(as_text=True)
    assert "分钟后再试" in html


# ---------- 忘记 PIN ----------


def test_forgot_pin_with_partner_code(client, partner, app):
    two_islanders(client, partner, app)
    login(partner, app, "阿木", "5678")
    code = new_reset_code(app, partner, "小雨")
    assert len(code) == 8
    # 数据库里只有哈希，不存明文
    row = db_row(app, "SELECT reset_code_hash FROM members WHERE nickname = '小雨'")
    assert row["reset_code_hash"] and code not in row["reset_code_hash"]
    # 只显示一次：刷新设置页就没有了
    assert 'class="reset-code"' not in partner.get("/settings").get_data(as_text=True)

    # 小雨在登录页用重置码（小写、带空格也可以）
    mid = member_id(app, "小雨")
    typed = code.lower()[:4] + " " + code.lower()[4:]
    resp = client.post("/pin/forgot", data={"member_id": mid, "reset_code": typed, "pin": "9999", "pin_confirm": "9999"})
    assert resp.headers["Location"] == "/login"
    assert login(client, app, "小雨", "9999").status_code == 302
    client.post("/logout")

    # 重置码只能用一次
    html = client.post("/pin/forgot", data={"member_id": mid, "reset_code": code, "pin": "1111", "pin_confirm": "1111"}).get_data(as_text=True)
    assert "现在没有可用的重置码" in html


def test_forgot_pin_wrong_and_expired_code(client, partner, app):
    two_islanders(client, partner, app)
    login(partner, app, "阿木", "5678")
    code = new_reset_code(app, partner, "小雨")
    mid = member_id(app, "小雨")

    html = client.post("/pin/forgot", data={"member_id": mid, "reset_code": "WRONG234", "pin": "9999", "pin_confirm": "9999"}).get_data(as_text=True)
    assert "重置码不正确，还可以再试 4 次" in html

    # 超过 30 分钟
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db_run(app, "UPDATE members SET reset_code_expires = ? WHERE id = ?", past, mid)
    html = client.post("/pin/forgot", data={"member_id": mid, "reset_code": code, "pin": "9999", "pin_confirm": "9999"}).get_data(as_text=True)
    assert "现在没有可用的重置码" in html
    assert login(client, app, "小雨", "1234").status_code == 302


def test_reset_code_only_for_partner(client, partner, app):
    """重置码是给另一半的：不能用它重置生成者自己的 PIN；重新生成后旧码作废。"""
    two_islanders(client, partner, app)
    login(partner, app, "阿木", "5678")
    first = new_reset_code(app, partner, "小雨")
    second = new_reset_code(app, partner, "小雨")
    partner.post("/logout")

    amu = member_id(app, "阿木")
    html = client.post("/pin/forgot", data={"member_id": amu, "reset_code": second, "pin": "9999", "pin_confirm": "9999"}).get_data(as_text=True)
    assert "现在没有可用的重置码" in html

    xiaoyu = member_id(app, "小雨")
    if first != second:
        html = client.post("/pin/forgot", data={"member_id": xiaoyu, "reset_code": first, "pin": "9999", "pin_confirm": "9999"}).get_data(as_text=True)
        assert "重置码不正确" in html
    resp = client.post("/pin/forgot", data={"member_id": xiaoyu, "reset_code": second, "pin": "9999", "pin_confirm": "9999"})
    assert resp.status_code == 302


def test_forgot_pin_when_alone_shows_script(client, app):
    create_island(client)
    client.post("/logout")
    html = client.get("/pin/forgot").get_data(as_text=True)
    assert "scripts\\reset_pin.py" in html
    assert 'name="reset_code"' not in html
    # 只有一个人时，小信箱里没有"帮 TA 重置"
    login(client, app, "小雨", "1234")
    assert "settings/reset-code" not in client.get("/settings").get_data(as_text=True)
    client.post("/settings/reset-code")
    assert db_row(app, "SELECT reset_code_hash FROM members")["reset_code_hash"] is None


# ---------- 创建新角色 ----------


def test_new_character_resets_animal_and_mood(client, partner, app):
    two_islanders(client, partner, app)
    mid = member_id(app, "小雨")
    db_run(app, "UPDATE members SET animal_code = 'ENFP', mood = 'happy', mood_set_at = datetime('now') WHERE id = ?", mid)
    db_run(app, "INSERT INTO forest_results (member_id, code, answers) VALUES (?, 'ENFP', '[]')", mid)
    db_run(app, "INSERT INTO memories (kind, note, created_by) VALUES ('manual', '一起看海', ?)", mid)

    resp = client.post("/character/new", data={"member_id": mid, "pin": "1234", "nickname": "小雨点", "confirm": "1"})
    assert resp.headers["Location"] == "/"  # 直接登录回小岛

    row = db_row(app, "SELECT * FROM members WHERE id = ?", mid)
    assert row["nickname"] == "小雨点"
    assert row["animal_code"] is None and row["mood"] is None
    assert db_row(app, "SELECT COUNT(*) AS n FROM forest_results WHERE member_id = ?", mid)["n"] == 0
    assert db_row(app, "SELECT COUNT(*) AS n FROM memories")["n"] == 1  # 回忆保留

    home = client.get("/").get_data(as_text=True)
    assert "新角色创建好啦" in home
    assert "player_slot_left.png" in home  # 回到默认形象（第一位成员在左边）
    assert "小雨点" in home


def test_new_character_checks(client, partner, app):
    two_islanders(client, partner, app)
    mid = member_id(app, "小雨")
    html = client.post("/character/new", data={"member_id": mid, "pin": "1234", "nickname": "阿木", "confirm": "1"}).get_data(as_text=True)
    assert "这个昵称已经被 TA 用了" in html
    html = client.post("/character/new", data={"member_id": mid, "pin": "1234", "nickname": "小雨点"}).get_data(as_text=True)
    assert "请先勾选确认" in html
    html = client.post("/character/new", data={"member_id": mid, "pin": "0000", "nickname": "小雨点", "confirm": "1"}).get_data(as_text=True)
    assert "还可以再试 4 次" in html
    assert db_row(app, "SELECT nickname FROM members WHERE id = ?", mid)["nickname"] == "小雨"
    # 可以保留原来的昵称，只重置动物
    resp = client.post("/character/new", data={"member_id": mid, "pin": "1234", "nickname": "小雨", "confirm": "1"})
    assert resp.status_code == 302


# ---------- 登录前切换语言（bug 修复） ----------


def test_language_picked_on_login_page_survives_login(client, partner, app):
    two_islanders(client, partner, app)  # 两人的语言都是中文
    client.post("/lang", data={"lang": "en", "next": "/login"})
    login_page = client.get("/login").get_data(as_text=True)
    assert 'lang="en"' in login_page  # 登录页本身已经是英文

    login(client, app, "小雨", "1234")
    home = client.get("/").get_data(as_text=True)
    assert 'lang="en"' in home and "Whisper Pier" in home
    assert db_row(app, "SELECT lang FROM members WHERE nickname = '小雨'")["lang"] == "en"


def test_login_without_switching_keeps_saved_language(client, partner, app):
    """没有在登录页切换语言时，仍然用自己保存的语言（不会被别人留下的 Cookie 改掉）。"""
    two_islanders(client, partner, app)
    login(client, app, "小雨", "1234")
    client.post("/lang", data={"lang": "en", "next": "/"})
    client.post("/logout")
    # 同一台设备（Cookie 仍是英文），阿木登录：阿木保存的是中文
    login(client, app, "阿木", "5678")
    assert 'lang="zh-CN"' in client.get("/").get_data(as_text=True)


# ---------- 返回按钮 ----------


def test_join_and_create_pages_have_back_button(client, partner, app):
    html = partner.get("/create").get_data(as_text=True)
    assert 'class="back-link form-back" href="/"' in html
    create_island(client)
    html = partner.get("/join").get_data(as_text=True)
    assert 'class="back-link form-back" href="/login"' in html and "返回登录" in html
    for path in ("/pin/change", "/pin/forgot", "/character/new"):
        assert 'href="/login"' in partner.get(path).get_data(as_text=True)


# ---------- 默认形象 ----------


def test_default_avatar_is_clay_figure(client, app):
    create_island(client)
    home = client.get("/").get_data(as_text=True)
    assert "/static/usland/assets/ui/placeholders/avatar_placeholder.png" in home
    assert ".svg" not in "".join(re.findall(r'player_slot_[a-z]+\.\w+', home))
