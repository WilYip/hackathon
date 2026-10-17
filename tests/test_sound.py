"""全站声音：清单、每页的声音场景、服务器端的"刚完成的操作"音效、页面状态事件音、压缩脚本。
真正的播放在浏览器里（static/js/sound.js），这里检查服务器给它的数据是否正确。"""

import json
import re
import sys
from pathlib import Path

from services import content
from tests.test_auth import create_island, invite_code, join_island
from tests.test_forest import INFP, ISFJ, take_quiz
from tests.test_memories import add
from tests.test_quest import current_round, to_confirmed, to_deciding

ROOT = Path(__file__).resolve().parent.parent


def setup_pair(client, partner, app):
    create_island(client, nickname="小雨")
    join_island(partner, invite_code(app), nickname="阿木")
    # 浏览器会跟着跳转显示下一页，把"创建 / 加入成功"的音效用掉；测试客户端不会自动跳转，这里手动打开一次
    client.get("/")
    partner.get("/")


def json_block(html, block_id):
    """取出页面里 <script type="application/json" id="..."> 的内容（没有则 None）。"""
    m = re.search(r'<script type="application/json" id="' + block_id + r'">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


def body_attr(html, name):
    m = re.search(name + r'="([^"]*)"', html)
    return m.group(1) if m else None


# ---------- 清单 ----------


def test_manifest_files_exist():
    assets = content.load("audio_manifest")["assets"]
    assert len(assets) == 37
    for a in assets:
        assert (ROOT / a["path"]).exists(), a["path"]
        assert a["category"] in ("bgm", "ambience", "sfx")
        assert 0 < a["recommended_volume"] <= 1


def test_every_sound_used_in_code_exists():
    # 代码里写到的声音名都要在清单里（写错名字会静默不响，很难发现）
    ids = {a["id"] for a in content.load("audio_manifest")["assets"]}
    used = set()
    for path in list((ROOT / "static" / "js").glob("*.js")) + list((ROOT / "routes").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        used |= set(re.findall(r'(?:play|event|next|cue)\(\s*"([a-z_]+)"', text))
        used |= set(re.findall(r'"sound":\s*"([a-z_]+)"', text))
        used |= set(re.findall(r'"([a-z]+_open)"', text))  # map.js：信箱 / 告示牌面板
    for path in (ROOT / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        used |= set(re.findall(r"\{% block (?:bgm|amb|amb_extra|sound_enter) %\}([a-z_]+)\{% endblock %\}", text))
    assert used, "没有找到任何声音名"
    assert used <= ids, used - ids


def test_manifest_sent_to_browser(client, app):
    html = client.get("/").get_data(as_text=True)  # 欢迎页（还没有小岛）
    manifest = json_block(html, "sound-manifest")
    assert manifest["bgm_island"]["src"] == "/static/audio/bgm/bgm_island.mp3"
    assert manifest["bgm_island"]["cat"] == "bgm" and manifest["bgm_island"]["loop"] is True
    assert manifest["ui_select"]["cat"] == "sfx"
    assert "/static/js/sound.js" in html
    # 声音默认关闭：页面上没有 <audio> 标签，也不会自动加载声音文件
    assert "<audio" not in html


# ---------- 每个页面的声音场景 ----------


def test_scene_per_page(client, partner, app):
    html = client.get("/").get_data(as_text=True)
    assert body_attr(html, "data-bgm") == "bgm_welcome"
    assert "data-sound-toggle" in html  # 欢迎页也有开关

    setup_pair(client, partner, app)
    pages = {
        "/": ("bgm_island", "amb_ocean", "island", ""),
        "/memories": ("bgm_memories", "amb_cottage", "memories", "cottage_open"),
        "/whisper": ("bgm_whisper", "amb_dock", "whisper", "dock_enter"),
        "/quest": ("bgm_quest", "", "quest", "board_open"),
        "/forest": ("bgm_forest", "amb_forest", "forest", "forest_enter"),
        "/forest/quiz": ("bgm_forest", "amb_forest", "forest", "forest_enter"),
        "/settings": ("bgm_island", "", "mailbox", "mailbox_open"),
    }
    for url, (bgm, amb, region, enter) in pages.items():
        html = client.get(url).get_data(as_text=True)
        assert body_attr(html, "data-bgm") == bgm, url
        assert body_attr(html, "data-amb") == amb, url
        assert body_attr(html, "data-sound-region") == region, url
        assert body_attr(html, "data-sound-enter") == enter, url
    # 温柔传话页音乐小声一点
    assert body_attr(client.get("/whisper").get_data(as_text=True), "data-bgm-gain") == "0.7"


def test_home_has_sound_toggle_hidden_without_js(client, partner, app):
    setup_pair(client, partner, app)
    html = client.get("/").get_data(as_text=True)
    toggle = html.split("data-sound-toggle")[1].split(">")[0]
    assert "hidden" in toggle  # 没有 JavaScript 时不显示（反正也放不了声音）
    assert 'aria-pressed="false"' in toggle


def test_settings_sound_section_and_credits(client, partner, app):
    setup_pair(client, partner, app)
    html = client.get("/settings").get_data(as_text=True)
    for key in ("bgm", "amb", "sfx", "error"):
        assert f'data-sound-pref="{key}"' in html
    for key in ("bgm", "amb", "sfx"):
        assert f'data-sound-volume="{key}"' in html
    assert 'href="/static/audio/credits.html"' in html
    assert "音乐致谢" in html
    # 致谢页本身可以直接打开，并且有 CC BY 3.0 要求的署名
    credits = client.get("/static/audio/credits.html")
    assert credits.status_code == 200
    text = credits.get_data(as_text=True)
    assert "MouthlessGames" in text and "creativecommons.org/licenses/by/3.0" in text


# ---------- 服务器端：刚完成的操作 ----------


def test_cue_plays_once(client, partner, app):
    setup_pair(client, partner, app)
    client.post("/settings/profile", data={"island_name": "新岛", "nickname": "小雨", "lang": "zh"})
    html = client.get("/settings").get_data(as_text=True)
    assert json_block(html, "sound-cues") == ["ui_success"]
    # 刷新：不再响
    html = client.get("/settings").get_data(as_text=True)
    assert json_block(html, "sound-cues") == []


def test_memory_save_cue(client, partner, app):
    setup_pair(client, partner, app)
    add(client, "今天一起看了晚霞")
    html = client.get("/memories").get_data(as_text=True)
    assert json_block(html, "sound-cues") == ["memory_save"]


def test_login_cues(client, partner, app, raw_client):
    setup_pair(client, partner, app)
    client.post("/logout")
    resp = client.post("/login", data={"member_id": "1", "pin": "0000"})
    assert json_block(resp.get_data(as_text=True), "sound-cues") == ["ui_error"]
    client.post("/login", data={"member_id": "1", "pin": "1234"})
    assert json_block(client.get("/").get_data(as_text=True), "sound-cues") == ["ui_success"]


# ---------- 页面状态事件音（约会选选选、初见森林） ----------


def test_quest_events(client, partner, app):
    to_deciding(client, partner, app)
    rid = current_round(app)["id"]
    events = json_block(client.get("/quest").get_data(as_text=True), "sound-events")
    assert events == [{"sound": "quest_reveal", "key": f"quest_reveal:{rid}"}]

    task = json.loads(current_round(app)["recommendations"])[0]["task_id"]
    partner.post("/quest/propose", data={"task_id": task})
    events = json_block(client.get("/quest").get_data(as_text=True), "sound-events")
    assert events[0] == {"sound": "message_receive", "key": f"quest_propose:{rid}:{task}"}  # 对方提议，排在前面
    # 提议的人自己看不到"收到"
    events = json_block(partner.get("/quest").get_data(as_text=True), "sound-events")
    assert [e["sound"] for e in events] == ["quest_reveal"]


def test_quest_agreed_and_complete_events(client, partner, app):
    to_confirmed(client, partner, app)
    rid = current_round(app)["id"]
    events = json_block(client.get("/quest").get_data(as_text=True), "sound-events")
    assert events == [{"sound": "quest_agreed", "key": f"quest_agreed:{rid}"}]

    client.post("/quest/complete", data={"note": "一起散步"}, content_type="multipart/form-data")
    events = json_block(client.get(f"/quest?done={rid}").get_data(as_text=True), "sound-events")
    assert events == [{"sound": "quest_complete", "key": f"quest_complete:{rid}", "fresh": True}]


def test_forest_pair_reveal_only_when_fresh(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    assert json_block(client.get("/forest").get_data(as_text=True), "sound-events") is None  # 还没有组合
    take_quiz(partner, ISFJ)
    events = json_block(client.get("/forest").get_data(as_text=True), "sound-events")
    assert events[0]["sound"] == "pair_reveal" and events[0]["fresh"] is True

    # 很久以前相遇的：只记下，不补播
    import sqlite3
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.execute("UPDATE memories SET created_at = datetime('now', '-2 days') WHERE kind = 'forest'")
    conn.commit()
    conn.close()
    events = json_block(client.get("/forest").get_data(as_text=True), "sound-events")
    assert events[0]["fresh"] is False


# ---------- 压缩脚本 ----------


def test_compress_script_dry_run(capsys, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import compress_bgm

    monkeypatch.setattr(sys, "argv", ["compress_bgm.py", "--dry-run"])
    before = {p.name: p.stat().st_size for p in compress_bgm.BGM_DIR.glob("*.mp3")}
    compress_bgm.main()
    out = capsys.readouterr().out
    assert "bgm_island.mp3" in out
    after = {p.name: p.stat().st_size for p in compress_bgm.BGM_DIR.glob("*.mp3")}
    assert before == after  # 预览模式不改文件

    monkeypatch.setattr(sys, "argv", ["compress_bgm.py", "--bitrate", "64"])
    try:
        compress_bgm.main()
        raise AssertionError("码率超出范围应该报错")
    except SystemExit as exit_:
        assert "96" in str(exit_.code)
