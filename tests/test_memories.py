"""M7 回忆小屋：时间线（四种来源）、手动添加、照片校验与权限、空状态、中英文。"""

import io
import json
import sqlite3

from PIL import Image

from tests.test_auth import create_island, invite_code, join_island
from tests.test_forest import INFP, ISFJ, take_quiz


def setup_pair(client, partner, app):
    create_island(client, nickname="小雨")
    join_island(partner, invite_code(app), nickname="阿木")


def query(app, sql, *args):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return rows


def png_bytes(size=(400, 300)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 220, 240)).save(buf, "PNG")
    return buf.getvalue()


def add(client, note, photo=None):
    data = {"note": note}
    if photo is not None:
        data["photo"] = photo
    return client.post("/memories/add", data=data, content_type="multipart/form-data")


def test_empty_state(client, partner, app):
    setup_pair(client, partner, app)
    html = client.get("/memories").get_data(as_text=True)
    assert "回忆小屋" in html
    assert "小屋里还空空的" in html
    assert 'class="fab"' in html  # 右下角的"＋"


def test_add_manual_memory(client, partner, app):
    setup_pair(client, partner, app)
    resp = add(client, "今天一起在楼下看到了晚霞", (io.BytesIO(png_bytes()), "sky.png"))
    assert resp.status_code == 302
    row = query(app, "SELECT kind, note, photo FROM memories")[0]
    assert row[0] == "manual" and row[1] == "今天一起在楼下看到了晚霞"
    assert (app.config["UPLOAD_DIR"] / row[2]).exists()

    # 两个人都能看到，照片走 /media
    for c in (client, partner):
        html = c.get("/memories").get_data(as_text=True)
        assert "今天一起在楼下看到了晚霞" in html
        assert "小日常" in html
        assert f"/media/{row[2]}" in html
        assert "小雨 记录" in html
    assert partner.get(f"/media/{row[2]}").status_code == 200


def test_add_without_photo(client, partner, app):
    setup_pair(client, partner, app)
    add(client, "只是想记一下今天很开心")
    assert query(app, "SELECT photo FROM memories")[0][0] is None


def test_add_validation_keeps_text(client, partner, app):
    setup_pair(client, partner, app)
    resp = add(client, "  ")
    assert resp.status_code == 400
    assert "写一句话吧" in resp.get_data(as_text=True)

    resp = add(client, "字" * 141)
    assert resp.status_code == 400
    assert "最多 140 个字" in resp.get_data(as_text=True)

    # 照片格式不对：报错、保留文字、自动重新打开添加窗口
    resp = add(client, "保留这句话", (io.BytesIO(b"GIF89a....."), "a.gif"))
    assert resp.status_code == 400
    html = resp.get_data(as_text=True)
    assert "只支持 jpg、png、webp" in html
    assert "保留这句话" in html
    assert "data-open-on-load" in html

    assert query(app, "SELECT COUNT(*) FROM memories")[0][0] == 0
    assert list(app.config["UPLOAD_DIR"].iterdir()) == []


def test_timeline_shows_all_sources_newest_first(client, partner, app):
    setup_pair(client, partner, app)
    # 1. 初见森林相遇
    take_quiz(client, INFP)
    take_quiz(partner, ISFJ)
    # 2. 约会任务完成
    choice = {"time": "15min", "budget": "free", "mood": "tired", "want": "quiet_time"}
    client.post("/quest/start")
    client.post("/quest/choose", data=choice)
    partner.post("/quest/choose", data=choice)
    first = json.loads(query(app, "SELECT recommendations FROM quest_rounds")[0][0])[0]["task_id"]
    client.post("/quest/propose", data={"task_id": first})
    partner.post("/quest/agree", data={"task_id": first})
    client.post("/quest/complete", data={"note": "一起完成啦"}, content_type="multipart/form-data")
    # 3. 和好
    client.post("/api/whisper/reconcile")
    partner.post("/api/whisper/reconcile")
    # 4. 手动添加
    add(partner, "手动写的一句")

    # 时间都在同一秒内时按 id 倒序：最新的在最前面
    html = client.get("/memories").get_data(as_text=True)
    positions = [html.index(text) for text in ("手动写的一句", "我们和好啦", "一起完成啦", "我们在初见森林相遇")]
    assert positions == sorted(positions)
    assert "梦想兔兔 × 暖心考拉" in html  # 初见森林回忆显示两只动物
    for label in ("约会任务", "和好", "初见森林", "小日常"):
        assert label in html


def test_dates_and_english(client, partner, app):
    setup_pair(client, partner, app)
    add(client, "date check")
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("UPDATE memories SET created_at = '2026-10-16 08:00:00'")
    conn.commit()
    conn.close()
    assert "2026年10月16日" in client.get("/memories").get_data(as_text=True)
    client.post("/lang", data={"lang": "en", "next": "/memories"})
    html = client.get("/memories").get_data(as_text=True)
    assert "16 Oct 2026" in html
    assert "Little moment" in html
    assert "Memory Cottage" in html


def test_requires_login(raw_client):
    assert raw_client.get("/memories").status_code == 302
    assert raw_client.post("/memories/add", data={"note": "x"}).status_code == 403  # 没有 Origin


def test_alone_can_use_cottage(client, app):
    create_island(client)
    html = client.get("/memories").get_data(as_text=True)
    assert "等 TA 加入后就能一起玩啦" in html
    add(client, "先替 TA 记下来")
    assert "先替 TA 记下来" in client.get("/memories").get_data(as_text=True)
