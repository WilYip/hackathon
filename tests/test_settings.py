"""M7 小信箱（设置）：改小岛名 / 昵称 / 语言、邀请码、API key 管理（只显示末尾 4 位）、隐私说明、退出。
所有 DeepSeek 调用都被 conftest.py 的 fake_ai 替换，不会联网。"""

import sqlite3

from tests.conftest import FakeAPIError
from tests.test_auth import create_island, invite_code, join_island

KEY = "sk-settings-key-000011112222wxyz"  # 测试用的假 key（末尾 4 位 wxyz）


def setup_pair(client, partner, app):
    create_island(client, nickname="小雨")
    join_island(partner, invite_code(app), nickname="阿木")


def db_value(app, sql):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    value = conn.execute(sql).fetchone()[0]
    conn.close()
    return value


def page(client):
    return client.get("/settings").get_data(as_text=True)


def test_settings_page_sections(client, partner, app):
    setup_pair(client, partner, app)
    html = page(client)
    for text in ("小信箱", "小岛与我", "传话魔法", "未设置", "隐私说明", "Usland 不是心理咨询服务", 'action="/logout"'):
        assert text in html
    assert "等 TA 加入后" not in html  # 两人都在：不显示邀请码


def test_invite_code_only_when_alone(client, app):
    create_island(client)
    html = page(client)
    assert "等 TA 加入后就能一起玩啦" in html
    assert invite_code(app) in html


def test_update_profile(client, partner, app):
    setup_pair(client, partner, app)
    resp = client.post("/settings/profile", data={"island_name": "星星岛", "nickname": "雨雨", "lang": "en"},
                       follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "Saved!" in html  # 提示已经用新语言
    assert db_value(app, "SELECT name FROM island") == "星星岛"
    assert db_value(app, "SELECT nickname FROM members WHERE id = 1") == "雨雨"
    assert db_value(app, "SELECT lang FROM members WHERE id = 1") == "en"
    # 另一半也看到新的小岛名
    assert "星星岛" in partner.get("/").get_data(as_text=True)


def test_profile_validation(client, partner, app):
    setup_pair(client, partner, app)
    resp = client.post("/settings/profile", data={"island_name": "", "nickname": "雨", "lang": "zh"},
                       follow_redirects=True)
    assert "请填写小岛名" in resp.get_data(as_text=True)
    resp = client.post("/settings/profile", data={"island_name": "岛", "nickname": "阿木", "lang": "zh"},
                       follow_redirects=True)
    assert "这个昵称已经被 TA 用了" in resp.get_data(as_text=True)
    assert db_value(app, "SELECT nickname FROM members WHERE id = 1") == "小雨"


def test_set_test_and_delete_key(client, partner, app, fake_ai):
    setup_pair(client, partner, app)

    # 填写：先测试再保存；页面只显示末尾 4 位
    resp = client.post("/settings/key", data={"api_key": KEY}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "新的 key 测试通过" in html
    assert "sk-****wxyz" in html
    assert KEY not in html
    assert db_value(app, "SELECT deepseek_api_key FROM island") == KEY
    assert fake_ai.calls[-1]["max_tokens"] == 5

    # 对方的设置页、温柔传话页也只有末尾 4 位
    for url in ("/settings", "/whisper"):
        html = partner.get(url).get_data(as_text=True)
        assert "sk-****wxyz" in html and KEY not in html

    # 测试连接：成功 / 失败
    assert "连接正常" in client.post("/settings/key/test", follow_redirects=True).get_data(as_text=True)
    fake_ai.error = FakeAPIError(402)
    assert "余额不足" in client.post("/settings/key/test", follow_redirects=True).get_data(as_text=True)
    assert fake_ai.calls[-1]["api_key"] == KEY  # 测试的是数据库里保存的 key

    # 删除
    fake_ai.error = None
    resp = client.post("/settings/key/delete", follow_redirects=True)
    assert "key 已经删除" in resp.get_data(as_text=True)
    assert db_value(app, "SELECT deepseek_api_key FROM island") is None
    assert 'data-needs-key="1"' in client.get("/whisper").get_data(as_text=True)


def test_replace_key_failure_keeps_old_key(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    client.post("/settings/key", data={"api_key": KEY})
    fake_ai.error = FakeAPIError(401)
    resp = client.post("/settings/key", data={"api_key": "sk-wrong-key-99999999"}, follow_redirects=True)
    assert "API key 不正确" in resp.get_data(as_text=True)
    assert db_value(app, "SELECT deepseek_api_key FROM island") == KEY  # 旧 key 没被替换


def test_key_format_and_missing_key(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    resp = client.post("/settings/key", data={"api_key": "short"}, follow_redirects=True)
    assert "这看起来不像 API key" in resp.get_data(as_text=True)
    assert fake_ai.calls == []
    resp = client.post("/settings/key/test", follow_redirects=True)
    assert "还没有设置 key" in resp.get_data(as_text=True)


def test_requires_login_and_same_origin(raw_client):
    assert raw_client.get("/settings").status_code == 302
    for url in ("/settings/profile", "/settings/key", "/settings/key/test", "/settings/key/delete"):
        assert raw_client.post(url).status_code == 403


def test_reduce_motion_setting(client, app):
    create_island(client)
    html = client.get("/settings").get_data(as_text=True)
    assert "减少动态效果" in html
    assert 'class="reduce-motion"' not in html

    resp = client.post("/settings/motion", data={"reduce": "1"})
    assert resp.status_code == 302
    html = client.get("/forest").get_data(as_text=True)
    assert '<html lang="zh-CN" class="reduce-motion">' in html  # 全站生效

    client.post("/settings/motion", data={})
    assert 'class="reduce-motion"' not in client.get("/forest").get_data(as_text=True)
