"""M4 温柔传话：API key、原话隐私、软化、安全卡片、未读、和好、次数限制。
所有 DeepSeek 调用都被 conftest.py 的 fake_ai 替换，不会联网。"""

import sqlite3

from tests.conftest import FakeAPIError
from tests.test_auth import create_island, invite_code, join_island

KEY = "sk-test-key-0123456789abcd"  # 测试用的假 key（末尾 4 位 abcd）


def setup_pair(client, partner, app):
    """创建小岛（小雨）+ 另一半加入（阿木）。"""
    create_island(client, nickname="小雨")
    join_island(partner, invite_code(app), nickname="阿木")


def save_key(client, key=KEY):
    return client.post("/api/whisper/key", json={"api_key": key})


def db_value(app, sql, *args):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    row = conn.execute(sql, args).fetchone()
    conn.close()
    return row[0] if row else None


def send_softened(client, fake_ai, original, softened):
    """完整走一遍"温柔转达 → 就这样发"。"""
    fake_ai.reply = softened
    resp = client.post("/api/whisper/soften", json={"text": original})
    assert resp.get_json() == {"status": "ok", "softened": softened}
    return client.post("/api/whisper/send", json={"text": softened, "original": original})


# ---------- API key ----------


def test_first_visit_shows_key_modal(client, partner, app):
    setup_pair(client, partner, app)
    html = client.get("/whisper").get_data(as_text=True)
    assert 'data-needs-key="1"' in html
    assert "点亮传话魔法" in html


def test_env_key_is_never_used(client, partner, app, monkeypatch, fake_ai):
    # 即使环境变量里有 key，应用也不会用它：仍然要求用户在网页上填写
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env-should-not-be-used")
    setup_pair(client, partner, app)
    assert 'data-needs-key="1"' in client.get("/whisper").get_data(as_text=True)
    resp = client.post("/api/whisper/soften", json={"text": "你好"})
    assert resp.status_code == 409
    assert resp.get_json()["status"] == "need_key"
    assert fake_ai.calls == []


def test_save_key_tests_then_stores_and_masks(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    resp = save_key(client)
    data = resp.get_json()
    assert data["ok"] is True
    assert data["masked"] == "sk-****abcd"
    assert KEY not in resp.get_data(as_text=True)
    # 先用极小请求测试过
    assert fake_ai.calls[-1]["max_tokens"] == 5
    assert db_value(app, "SELECT deepseek_api_key FROM island") == KEY

    # 之后两个人的页面都只显示末尾 4 位，页面源码里没有完整 key
    for c in (client, partner):
        html = c.get("/whisper").get_data(as_text=True)
        assert 'data-needs-key="0"' in html
        assert "sk-****abcd" in html
        assert KEY not in html
    # 首页和接口里也没有
    assert KEY not in client.get("/").get_data(as_text=True)
    assert KEY not in client.get("/api/whisper/messages").get_data(as_text=True)


def test_save_key_failures(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    fake_ai.error = FakeAPIError(401)
    data = save_key(client).get_json()
    assert data == {"ok": False, "error": "invalid_key", "message": "API key 不正确，请检查后重新粘贴"}
    fake_ai.error = FakeAPIError(402)
    assert save_key(client).get_json()["error"] == "no_balance"
    fake_ai.error = TimeoutError()
    assert save_key(client).get_json()["error"] == "network"
    # 失败时不保存
    assert db_value(app, "SELECT deepseek_api_key FROM island") is None


def test_save_key_format_check(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    resp = save_key(client, "sk short")
    assert resp.status_code == 400
    assert fake_ai.calls == []  # 格式不对时不会去调用 DeepSeek


# ---------- 原话隐私（重点） ----------


def test_original_only_visible_to_sender(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    save_key(client)
    original = "你又不回我消息，你根本不在乎我"
    softened = "你没回消息的时候我会有点不安，我希望能感受到你在乎我"
    sent = send_softened(client, fake_ai, original, softened).get_json()["message"]
    assert sent["original"] == original  # 发送者自己的返回里有原话

    # 发送者拉消息：看得到原话
    mine = client.get("/api/whisper/messages").get_json()["messages"]
    assert mine[0]["text"] == softened
    assert mine[0]["original"] == original

    # 对方拉消息：只有最终版本，响应里任何地方都没有原话
    resp = partner.get("/api/whisper/messages")
    theirs = resp.get_json()["messages"]
    assert theirs[0]["text"] == softened
    assert "original" not in theirs[0]
    assert original not in resp.get_data(as_text=True)

    # 用 ?after= 增量拉取时同样没有
    assert original not in partner.get("/api/whisper/messages?after=0").get_data(as_text=True)
    # 对方的页面源码里也没有
    assert original not in partner.get("/whisper").get_data(as_text=True)
    assert original not in partner.get("/").get_data(as_text=True)


def test_edited_version_keeps_original_private(client, partner, app, fake_ai):
    # "我再改改"：发送的是改过的版本，原话仍然只有自己能看
    setup_pair(client, partner, app)
    save_key(client)
    fake_ai.reply = "我有点累，想早点休息"
    client.post("/api/whisper/soften", json={"text": "别烦我了"})
    client.post("/api/whisper/send", json={"text": "我有点累了，想早点休息，明天再聊好吗", "original": "别烦我了"})
    theirs = partner.get("/api/whisper/messages").get_json()["messages"][0]
    assert theirs["text"] == "我有点累了，想早点休息，明天再聊好吗"
    assert "original" not in theirs


def test_direct_send_has_no_original(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    save_key(client)
    calls_before = len(fake_ai.calls)
    msg = client.post("/api/whisper/send", json={"text": "今晚吃什么？"}).get_json()["message"]
    assert msg["text"] == "今晚吃什么？"
    assert "original" not in msg
    assert len(fake_ai.calls) == calls_before  # 直接发送不经过 AI
    assert partner.get("/api/whisper/messages").get_json()["messages"][0]["text"] == "今晚吃什么？"


# ---------- 软化 ----------


def test_soften_only_previews_and_does_not_save(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    save_key(client)
    fake_ai.reply = "我有点想你"
    assert client.post("/api/whisper/soften", json={"text": "你怎么还不理我"}).get_json()["status"] == "ok"
    assert db_value(app, "SELECT COUNT(*) FROM messages") == 0
    assert fake_ai.calls[-1]["api_key"] == KEY  # 用的是数据库里用户填写的 key


def test_unsafe_is_not_sent(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    save_key(client)
    fake_ai.reply = "[UNSAFE]"
    resp = client.post("/api/whisper/soften", json={"text": "（一句有危险的话）"})
    assert resp.get_json() == {"status": "unsafe"}  # 不返回任何改写内容
    assert db_value(app, "SELECT COUNT(*) FROM messages") == 0
    assert partner.get("/api/whisper/messages").get_json()["messages"] == []


def test_safety_card_and_resources_on_page(client, partner, app):
    setup_pair(client, partner, app)
    save_key(client)
    html = client.get("/whisper").get_data(as_text=True)
    assert 'id="dlg-safety"' in html
    assert "这句话里好像有让人担心的内容" in html
    for number in ("000", "1800 737 732", "13 11 14"):
        assert number in html
    assert "Usland 不是心理咨询服务" in html


def test_soften_errors_are_friendly(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    save_key(client)
    fake_ai.error = FakeAPIError(402)
    data = client.post("/api/whisper/soften", json={"text": "你好"}).get_json()
    assert data["status"] == "error"
    assert data["code"] == "no_balance"
    fake_ai.error = FakeAPIError(401)  # key 后来失效了：提示重新填写
    assert client.post("/api/whisper/soften", json={"text": "你好"}).get_json()["code"] == "key_invalid_now"


def test_soften_validation(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    save_key(client)
    assert client.post("/api/whisper/soften", json={"text": "  "}).status_code == 400
    assert client.post("/api/whisper/soften", json={"text": "字" * 501}).status_code == 400
    assert client.post("/api/whisper/soften", json={"text": "字" * 500}).get_json()["status"] == "ok"


def test_daily_limit(client, partner, app, fake_ai):
    setup_pair(client, partner, app)
    save_key(client)
    app.config["SOFTEN_DAILY_LIMIT"] = 2
    assert client.post("/api/whisper/soften", json={"text": "1"}).get_json()["status"] == "ok"
    assert partner.post("/api/whisper/soften", json={"text": "2"}).get_json()["status"] == "ok"
    calls = len(fake_ai.calls)
    data = client.post("/api/whisper/soften", json={"text": "3"}).get_json()
    assert data["status"] == "limit"
    assert data["message"] == "今天的魔法用完啦，明天再来"
    assert len(fake_ai.calls) == calls  # 超过次数后不再调用 DeepSeek
    # 直接发送不受影响
    assert client.post("/api/whisper/send", json={"text": "晚安"}).status_code == 200


# ---------- 未读标记 ----------


def test_unread_badge_on_map(client, partner, app):
    setup_pair(client, partner, app)
    save_key(client)
    partner.post("/api/whisper/send", json={"text": "在吗"})
    partner.post("/api/whisper/send", json={"text": "想你了"})

    html = client.get("/").get_data(as_text=True)
    assert "unread-badge" in html
    assert "2 封新传话" in html
    # 发送者自己的首页不显示（自己发的不算未读）
    assert "unread-badge" not in partner.get("/").get_data(as_text=True)

    # 打开传话码头拉过消息后，标记消失
    client.get("/api/whisper/messages")
    assert "unread-badge" not in client.get("/").get_data(as_text=True)

    # 再来一条新消息，又出现 1 封
    partner.post("/api/whisper/send", json={"text": "晚安"})
    assert "1 封新传话" in client.get("/").get_data(as_text=True)


# ---------- 和好 ----------


def test_reconcile_flow(client, partner, app):
    setup_pair(client, partner, app)
    first = client.post("/api/whisper/reconcile").get_json()
    assert first["reconcile"] == {"me": True, "partner": False}
    assert first["hugged"] is False

    # 对方页面看到"TA 想和好啦"
    data = partner.get("/api/whisper/messages").get_json()
    assert data["reconcile"] == {"me": False, "partner": True}
    hug_before = data["hug_id"]

    # 对方也按下：拥抱动画 + 回忆里多一条"我们和好啦" + 和好状态重置
    second = partner.post("/api/whisper/reconcile").get_json()
    assert second["hugged"] is True
    assert second["hug_id"] > hug_before
    assert second["reconcile"] == {"me": False, "partner": False}
    assert db_value(app, "SELECT COUNT(*) FROM memories WHERE kind = 'reconcile'") == 1
    assert db_value(app, "SELECT COUNT(*) FROM reconcile_requests") == 0

    # 先按的人轮询时也能拿到新的 hug_id，从而播放动画
    assert client.get("/api/whisper/messages").get_json()["hug_id"] == second["hug_id"]


def test_reconcile_twice_by_same_person_does_not_hug(client, partner, app):
    setup_pair(client, partner, app)
    client.post("/api/whisper/reconcile")
    assert client.post("/api/whisper/reconcile").get_json()["hugged"] is False
    assert db_value(app, "SELECT COUNT(*) FROM memories") == 0


# ---------- 权限与边界 ----------


def test_api_requires_login(raw_client):
    assert raw_client.get("/api/whisper/messages").status_code == 401
    assert raw_client.get("/whisper").status_code == 302


def test_post_requires_same_origin(client, partner, app, raw_client):
    setup_pair(client, partner, app)
    # 没有 Origin / Referer 的 POST 一律拒绝（防跨站请求）
    assert raw_client.post("/api/whisper/send", json={"text": "hi"}).status_code == 403


def test_alone_shows_waiting(client, fake_ai):
    create_island(client)
    html = client.get("/whisper").get_data(as_text=True)
    assert "等 TA 加入后就能一起玩啦" in html
    assert "dlg-key" not in html
    assert client.post("/api/whisper/send", json={"text": "hi"}).status_code == 409
    assert client.post("/api/whisper/soften", json={"text": "hi"}).status_code == 409
    assert fake_ai.calls == []


def test_message_html_is_not_rendered_server_side(client, partner, app):
    # 消息只通过 JSON 接口返回，由前端用 textContent 显示，不会被当成 HTML 执行
    setup_pair(client, partner, app)
    save_key(client)
    partner.post("/api/whisper/send", json={"text": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in client.get("/whisper").get_data(as_text=True)
    assert client.get("/api/whisper/messages").get_json()["messages"][0]["text"] == "<script>alert(1)</script>"
