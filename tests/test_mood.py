"""情绪状态（VISUAL_DESIGN 13.4）：只由用户主动选择、24 小时后恢复平静、对方的首页和温柔传话页能看到。"""

import sqlite3
from datetime import datetime, timedelta, timezone

import db as db_module
from services.mood import DEFAULT, MOODS, effective
from tests.test_auth import create_island, invite_code, join_island

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def setup_pair(client, partner, app):
    create_island(client, nickname="小雨")
    join_island(partner, invite_code(app), nickname="阿木")


def set_mood(client, mood, next_url="/"):
    return client.post("/mood", data={"mood": mood, "next": next_url})


def stored(app, nickname):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    row = conn.execute("SELECT mood, mood_set_at FROM members WHERE nickname = ?", (nickname,)).fetchone()
    conn.close()
    return row


# ---------- 纯函数：什么时候显示什么心情 ----------


def test_four_moods_default_calm():
    assert MOODS == ("happy", "wronged", "need_space", "calm")
    assert DEFAULT == "calm"


def test_effective_mood_expires_after_24_hours():
    set_at = (NOW - timedelta(hours=23, minutes=59)).isoformat()
    assert effective("wronged", set_at, now=NOW) == "wronged"
    set_at = (NOW - timedelta(hours=24)).isoformat()
    assert effective("wronged", set_at, now=NOW) == "calm"


def test_effective_mood_bad_values():
    assert effective(None, None, now=NOW) == "calm"
    assert effective("happy", None, now=NOW) == "calm"
    assert effective("angry", NOW.isoformat(), now=NOW) == "calm"
    assert effective("happy", "not a date", now=NOW) == "calm"


# ---------- 设置心情 ----------


def test_default_is_calm_everywhere(client, partner, app):
    setup_pair(client, partner, app)
    home = partner.get("/").get_data(as_text=True)
    assert home.count(" mood-calm") == 4  # 两只动物 × 横竖两套构图
    assert "mood-badge" not in home


def test_own_animal_opens_picker_only(client, partner, app):
    setup_pair(client, partner, app)
    html = client.get("/").get_data(as_text=True)
    assert 'id="mood-panel"' in html
    assert html.count("data-mood-picker") == 2  # 只有自己的动物可以选心情（横竖两套构图各一次）
    for label in ("开心", "委屈", "需要空间", "平静"):
        assert label in html


def test_set_mood_shows_to_partner(client, partner, app):
    setup_pair(client, partner, app)
    resp = set_mood(client, "wronged")
    assert resp.status_code == 302 and resp.headers["Location"] == "/"
    assert stored(app, "小雨")[0] == "wronged"

    # 对方首页：委屈的动作 + 小水滴标记 + 名牌上的文字
    home = partner.get("/").get_data(as_text=True)
    assert "animal-left mood-wronged" in home
    assert "mood-badge-wronged" in home
    assert "chip-mood-wronged" in home

    # 对方温柔传话页：心情和一句温柔提示
    html = partner.get("/whisper").get_data(as_text=True)
    assert "mood-wrap mood-wronged" in html
    assert "小雨 有点委屈，说话可以更温柔一点。" in html

    # 轮询接口也带着心情，页面不用刷新就能更新
    moods = partner.get("/api/whisper/messages").get_json()["moods"]
    assert moods["partner"]["key"] == "wronged"
    assert moods["me"]["key"] == "calm"


def test_need_space_and_happy(client, partner, app):
    setup_pair(client, partner, app)
    set_mood(partner, "need_space")
    home = client.get("/").get_data(as_text=True)
    assert "animal-right mood-need_space" in home and "mood-badge-need_space" in home
    assert "阿木 需要一点空间，不急着回复也没关系。" in client.get("/whisper").get_data(as_text=True)
    set_mood(partner, "happy")
    assert "animal-right mood-happy" in client.get("/").get_data(as_text=True)
    set_mood(partner, "calm")
    assert "mood-badge" not in client.get("/").get_data(as_text=True)


def test_invalid_mood_is_rejected(client, partner, app):
    setup_pair(client, partner, app)
    resp = set_mood(client, "angry")
    assert stored(app, "小雨")[0] is None
    assert "没有这种心情哦" in client.get(resp.headers["Location"]).get_data(as_text=True)


def test_mood_resets_after_24_hours(client, partner, app):
    setup_pair(client, partner, app)
    set_mood(client, "wronged")
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("UPDATE members SET mood_set_at = ? WHERE nickname = '小雨'", (old,))
    conn.commit()
    conn.close()
    assert "mood-wronged" not in partner.get("/").get_data(as_text=True)
    assert partner.get("/api/whisper/messages").get_json()["moods"]["partner"]["key"] == "calm"


def test_mood_is_never_guessed(client, partner, app):
    # 发消息、软化被拒、按和好、一直不登录……都不会自动改变心情
    setup_pair(client, partner, app)
    partner.post("/api/whisper/send", json={"text": "你怎么又不回我"})
    client.post("/api/whisper/reconcile")
    client.post("/logout")
    assert stored(app, "小雨") == (None, None)
    assert stored(app, "阿木") == (None, None)
    assert partner.get("/").get_data(as_text=True).count(" mood-calm") == 4


def test_next_redirect_stays_on_site(client, partner, app):
    setup_pair(client, partner, app)
    assert set_mood(client, "happy", "//evil.example").headers["Location"] == "/"
    assert set_mood(client, "happy", "/whisper").headers["Location"] == "/whisper"


def test_requires_login_and_same_origin(raw_client, client, app):
    create_island(client)
    client.post("/logout")
    assert client.post("/mood", data={"mood": "happy"}).status_code == 302  # 未登录跳走
    assert raw_client.post("/mood", data={"mood": "happy"}).status_code == 403  # 跨站拒绝


def test_english_labels(client, partner, app):
    setup_pair(client, partner, app)
    partner.post("/lang", data={"lang": "en", "next": "/"})
    set_mood(client, "need_space")
    html = partner.get("/whisper").get_data(as_text=True)
    assert "Need space" in html
    assert "小雨 needs a little space. No rush to reply." in html


def test_old_database_gets_mood_columns(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE members (id INTEGER PRIMARY KEY, nickname TEXT NOT NULL, pin_hash TEXT NOT NULL, "
                 "lang TEXT, animal_code TEXT, failed_attempts INTEGER, locked_until TEXT, created_at TEXT)")
    conn.commit()
    conn.close()
    db_module.init_db(path)
    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(members)")}
    conn.close()
    assert {"mood", "mood_set_at"} <= columns


# ---------- 取消心情 ----------


def test_clear_mood_back_to_calm(client, partner, app):
    setup_pair(client, partner, app)
    set_mood(client, "wronged")
    html = client.get("/").get_data(as_text=True)
    assert 'value="clear"' in html and "清除心情" in html

    resp = set_mood(client, "clear")
    assert resp.status_code == 302
    assert stored(app, "小雨")[0] == "calm"
    html = client.get("/").get_data(as_text=True)
    assert "心情已经清除" in html
    assert "chip-mood-wronged" not in partner.get("/").get_data(as_text=True)


def test_tap_current_mood_again_cancels(client, partner, app):
    setup_pair(client, partner, app)
    set_mood(client, "happy")
    set_mood(client, "happy")  # 再点一次当前的心情 = 取消
    assert stored(app, "小雨")[0] == "calm"
    set_mood(client, "happy")
    set_mood(client, "need_space")  # 点别的心情：正常切换
    assert stored(app, "小雨")[0] == "need_space"


def test_clear_button_disabled_when_calm(client, partner, app):
    setup_pair(client, partner, app)
    html = client.get("/").get_data(as_text=True)
    clear = html.split('value="clear"')[1].split(">")[0]
    assert "disabled" in clear


def test_name_chip_mood_below_name(client, partner, app):
    # 心情文字放在名牌里（map.js 根据实际大小把两张名牌推开，见 separateChips）
    setup_pair(client, partner, app)
    set_mood(client, "need_space")
    home = partner.get("/").get_data(as_text=True)
    assert "has-mood" in home
    assert home.count("data-name-chip") == 4  # 两张名牌 × 横竖两套构图
