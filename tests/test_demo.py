"""演示模式（DEMO_MODE=1，services/demo.py）：演示小岛自动生成、一键进入、共用小岛的保护、
示范改写、代替对方选择、自动 / 手动恢复，以及"真实小岛绝不被清空"。"""

import io
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from app import create_app
from services import demo
from tests.conftest import make_client
from tests.test_auth import create_island


@pytest.fixture
def demo_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    animal_dir = tmp_path / "animals"
    animal_dir.mkdir()
    return create_app({"TESTING": True, "ANIMAL_DIR": animal_dir, "DEMO_MODE": True})


@pytest.fixture
def visitor(demo_app):
    return make_client(demo_app)


def query(app, sql, *args):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return rows


def enter(client, member_id):
    return client.post("/demo/enter", data={"member_id": str(member_id)})


def set_marker(app, when):
    (app.config["DATA_DIR"] / demo.MARKER).write_text(when.isoformat(), encoding="utf-8")


def png():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 220, 240)).save(buf, "PNG")
    buf.seek(0)
    return buf


# ---------- 演示小岛自动生成 ----------


def test_demo_island_is_seeded_on_first_visit(demo_app, visitor):
    resp = visitor.get("/")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/login")
    members = query(demo_app, "SELECT id, nickname, animal_code FROM members ORDER BY id")
    assert [(m["id"], m["nickname"], m["animal_code"]) for m in members] == [(1, "Wilson", "INTJ"), (2, "Yvette", "ISFJ")]
    # 三条回忆：初见森林相遇 + 两条小日常
    kinds = sorted(r["kind"] for r in query(demo_app, "SELECT kind FROM memories"))
    assert kinds == ["forest", "manual", "manual"]
    assert query(demo_app, "SELECT COUNT(*) AS n FROM messages")[0]["n"] == 4
    # 不预置 API key
    assert query(demo_app, "SELECT deepseek_api_key FROM island")[0]["deepseek_api_key"] is None
    assert (demo_app.config["DATA_DIR"] / demo.MARKER).exists()


def test_login_page_offers_one_click_entry(demo_app, visitor):
    html = visitor.get("/login").get_data(as_text=True)
    assert html.count('action="/demo/enter"') == 2
    assert "Wilson" in html and "Yvette" in html
    assert 'name="pin"' not in html  # 不用输 PIN
    assert "/pin/change" not in html and "/character/new" not in html
    assert "1234" in html


def test_enter_logs_in_without_pin(demo_app, visitor):
    resp = enter(visitor, 2)
    assert resp.status_code == 302
    html = visitor.get("/").get_data(as_text=True)
    assert "demo-banner" in html  # 全站横幅
    assert "Yvette" in html


def test_demo_routes_404_when_not_demo(client):
    create_island(client)
    assert client.post("/demo/enter", data={"member_id": "1"}).status_code == 404
    assert client.post("/demo/reset").status_code == 404


# ---------- 共用小岛的保护 ----------


def test_blocked_actions(demo_app, visitor):
    enter(visitor, 1)
    visitor.post("/settings/profile", data={"island_name": "Hacked", "nickname": "Hacker", "lang": "en"})
    assert query(demo_app, "SELECT name FROM island")[0]["name"] == demo.ISLAND_NAME
    assert query(demo_app, "SELECT nickname FROM members WHERE id = 1")[0]["nickname"] == "Wilson"

    visitor.post("/settings/key", data={"api_key": "sk-abcdefghijklmnopqrstuv"})
    resp = visitor.post("/api/whisper/key", json={"api_key": "sk-abcdefghijklmnopqrstuv"})
    assert resp.status_code == 403
    assert query(demo_app, "SELECT deepseek_api_key FROM island")[0]["deepseek_api_key"] is None

    visitor.post("/settings/reset-code")
    assert query(demo_app, "SELECT reset_code_hash FROM members WHERE id = 2")[0]["reset_code_hash"] is None

    other = make_client(demo_app)
    other.post("/pin/change", data={"member_id": "1", "current_pin": "1234", "pin": "9999", "pin_confirm": "9999"})
    other.post("/character/new", data={"member_id": "1", "pin": "1234", "nickname": "Evil", "confirm": "1"})
    assert query(demo_app, "SELECT nickname FROM members WHERE id = 1")[0]["nickname"] == "Wilson"
    assert other.post("/login", data={"member_id": "1", "pin": "1234"}).status_code == 302  # PIN 没被改
    assert other.get("/join").status_code == 302


def test_settings_page_shows_demo_card(demo_app, visitor):
    enter(visitor, 1)
    html = visitor.get("/settings").get_data(as_text=True)
    assert "demo-card" in html and 'action="/demo/reset"' in html
    assert 'action="/settings/profile"' not in html
    assert 'action="/settings/key"' not in html


def test_photos_are_not_saved(demo_app, visitor):
    enter(visitor, 1)
    visitor.post("/memories/add", data={"note": "A lovely day", "photo": (png(), "a.png")},
                 content_type="multipart/form-data")
    row = query(demo_app, "SELECT note, photo FROM memories WHERE note = 'A lovely day'")[0]
    assert row["photo"] is None
    assert not any(demo_app.config["UPLOAD_DIR"].iterdir())


# ---------- 温柔传话：示范改写 ----------


def test_soften_uses_sample_rewrites(demo_app, visitor, fake_ai):
    enter(visitor, 1)
    html = visitor.get("/whisper").get_data(as_text=True)
    assert 'data-needs-key="0"' in html  # 不弹出填写 key
    data = visitor.post("/api/whisper/soften", json={"text": "你怎么又迟到了"}).get_json()
    assert data["status"] == "ok" and data["softened"] in demo.DEMO_SOFTEN["zh"]
    data = visitor.post("/api/whisper/soften", json={"text": "You never listen!"}).get_json()
    assert data["softened"] in demo.DEMO_SOFTEN["en"]
    assert fake_ai.calls == []  # 没有调用 AI


# ---------- 约会选选选：代替对方 ----------


def test_partner_choose_and_agree(demo_app, visitor):
    enter(visitor, 1)
    visitor.post("/quest/start")
    visitor.post("/quest/choose", data={"time": "15min", "budget": "free", "mood": "tired", "want": "quiet_time"})
    html = visitor.get("/quest").get_data(as_text=True)
    assert 'action="/quest/demo/partner-choose"' in html
    visitor.post("/quest/demo/partner-choose")
    row = query(demo_app, "SELECT status, recommendations FROM quest_rounds")[0]
    assert row["status"] == "deciding"

    import json
    task = json.loads(row["recommendations"])[0]["task_id"]
    visitor.post("/quest/propose", data={"task_id": task})
    visitor.post("/quest/demo/partner-agree", data={"task_id": task})
    assert query(demo_app, "SELECT status FROM quest_rounds")[0]["status"] == "confirmed"


# ---------- 恢复 ----------


def test_auto_reset_after_six_hours(demo_app, visitor):
    visitor.get("/login")
    enter(visitor, 1)
    visitor.post("/memories/add", data={"note": "Stranger was here"}, content_type="multipart/form-data")
    assert query(demo_app, "SELECT COUNT(*) AS n FROM memories")[0]["n"] == 4

    set_marker(demo_app, datetime.now(timezone.utc) - timedelta(hours=5))
    visitor.get("/login")
    assert query(demo_app, "SELECT COUNT(*) AS n FROM memories")[0]["n"] == 4  # 还没到 6 小时

    set_marker(demo_app, datetime.now(timezone.utc) - timedelta(hours=6, minutes=1))
    visitor.get("/login")
    assert query(demo_app, "SELECT COUNT(*) AS n FROM memories")[0]["n"] == 3  # 恢复成初始状态
    ids = [m["id"] for m in query(demo_app, "SELECT id FROM members ORDER BY id")]
    assert ids == [1, 2]  # 编号不变


def test_manual_reset(demo_app, visitor):
    enter(visitor, 2)
    visitor.post("/memories/add", data={"note": "Will be cleared"}, content_type="multipart/form-data")
    resp = visitor.post("/demo/reset")
    assert resp.headers["Location"].endswith("/login")
    assert query(demo_app, "SELECT COUNT(*) AS n FROM memories WHERE note = 'Will be cleared'")[0]["n"] == 0


def test_real_island_is_never_wiped(tmp_path, monkeypatch):
    # 先用普通模式建一座真实小岛
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    (tmp_path / "animals").mkdir()
    real = create_app({"TESTING": True, "ANIMAL_DIR": tmp_path / "animals"})
    create_island(make_client(real), nickname="小雨")
    # 再误开 DEMO_MODE：没有演示标记，绝对不能清空
    demo_on = create_app({"TESTING": True, "ANIMAL_DIR": tmp_path / "animals", "DEMO_MODE": True})
    make_client(demo_on).get("/login")
    assert [m["nickname"] for m in query(demo_on, "SELECT nickname FROM members")] == ["小雨"]
    assert not (tmp_path / demo.MARKER).exists()
