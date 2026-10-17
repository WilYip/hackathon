"""小岛场景（第三版素材）：横竖底图、循环视频、热区与悬停放大的元素、野餐垫上的动物、森林石像、新用户引导、
功能页背景、回忆小屋互动区域、图标与配色。"""

import json
import re
from pathlib import Path

import pytest

from services import content, scene
from tests.conftest import put_animal
from tests.test_auth import create_island, invite_code, join_island, member_id
from tests.test_forest import INFP, ESTJ, take_quiz

ROOT = Path(__file__).resolve().parent.parent
DELIVERY = ROOT / "docs" / "ui-v3" / "integration"
ASSETS = ROOT / "static" / "usland" / "assets"
ENTRY_URLS = ["/memories", "/whisper", "/quest", "/forest", "/settings"]


def home(client):
    create_island(client)
    return client.get("/").get_data(as_text=True)


def setup_pair(client, partner, app):
    create_island(client, nickname="小雨")
    join_island(partner, invite_code(app), nickname="阿木")


def style_of(html, pattern):
    return re.search(pattern + r'[^>]*style="([^"]*)"', html).group(1)


# ---------- 配置文件 ----------


@pytest.mark.parametrize("name, delivered", [
    ("scene_anchors", "scene_anchors.json"),
    ("character_assets", "character_asset_contract.json"),
])
def test_config_is_copy_of_delivery(name, delivered):
    # content/ 里的两份配置必须和队友交付的 docs/ui-v3/integration/ 完全一致
    path = DELIVERY / delivered
    if not path.exists():
        pytest.skip("没有交付文件夹")
    assert content.load(name) == json.loads(path.read_text(encoding="utf-8"))


def test_scene_config_covers_all_regions():
    region_ids = {r["id"] for r in content.regions()}
    cfg = content.load("scene")
    anchors = content.load("scene_anchors")
    assert set(cfg["island"]["regions"]) == region_ids
    for mode in ("desktop", "mobile"):
        assert set(cfg["island"]["labels"][mode]) == region_ids
        # 每个入口都对应 scene_anchors.json 里的一个热区
        assert {r["anchor"] for r in cfg["island"]["regions"].values()} == set(anchors[mode]["hotspots"])
        assert set(cfg["memory_room"]["spots"][mode]) == {"frames", "album", "postcards"}


def test_all_configured_assets_exist(app):
    # 配置里写到的已交付素材都必须真的存在（pending 里的是还没交付的）
    cfg = content.load("scene")
    with app.test_request_context():
        for mode in ("desktop", "mobile"):
            paths = [cfg["island"]["base"], cfg["island"]["statue_shadow"], cfg["memory_room"]["background"]]
            paths += [r["halo"] for r in cfg["island"]["regions"].values()]
            paths += [cfg["island"]["loop_video"], cfg["island"]["loop_detail"]]
            paths += [v for k, v in cfg["page_backgrounds"].items() if not k.startswith("_")]
            for p in paths:
                assert (ASSETS / p.format(mode=mode)).is_file(), p
        for side in ("left", "right"):
            assert (ASSETS / cfg["island"]["player_slot"].format(side=side)).is_file()
    # 16 种动物的石像都已交付
    for code in content.load("character_assets")["codes"]:
        assert (ASSETS / "animals" / "statues" / f"{code}.png").is_file(), code


def test_watermarked_reference_image_removed():
    assert not (ROOT / "static" / "img" / "island").exists()


# ---------- 主岛：底图、循环视频、热区、悬停放大的元素 ----------


def test_home_uses_both_layouts(client):
    html = home(client)
    assert "layout-desktop" in html and "layout-mobile" in html
    assert "/static/usland/assets/scenes/island/desktop/island_base_desktop.webp" in html
    assert "/static/usland/assets/scenes/island/mobile/island_base_mobile.webp" in html
    assert "--ratio: 2560 / 1440" in html and "--ratio: 1440 / 2560" in html
    assert "island_desktop" not in html  # 带水印的参考图不再使用
    # 五个入口：两套构图各一个热区 + 一个常驻标签
    for url in ENTRY_URLS:
        assert html.count(f'class="hotspot" href="{url}"') == 2
    for name in ("回忆小屋", "传话码头", "约会选选选", "初见森林", "小信箱"):
        assert name in html


def test_hotspots_follow_element_outline(client):
    """点击范围只在元素本身：热区是轮廓多边形的外接矩形 + clip-path 多边形。"""
    html = home(client)
    cfg = content.load("scene")["island"]["shapes"]
    for region_id, url in (("first_meet_forest", "/forest"), ("mailbox", "/settings"), ("whisper_pier", "/whisper")):
        hit = cfg["desktop"][region_id]["hit"]
        xs, ys = [x for x, _ in hit], [y for _, y in hit]
        box = scene.rect_box([min(xs), min(ys), max(xs), max(ys)], (2560, 1440))
        style = style_of(html, rf'<a class="hotspot" href="{url}"')
        assert f"left: {box['left']}%; top: {box['top']}%; width: {box['width']}%; height: {box['height']}%" in style
        assert "clip-path: polygon(" in style
    # 信箱的点击范围很小（不再是一大块矩形）
    mailbox = style_of(html, r'<a class="hotspot" href="/settings"')
    assert float(mailbox.split("width: ")[1].split("%")[0]) < 6


def test_halo_for_every_region(client):
    """悬停时元素四周和脚下亮起光圈；不再显示抠出来的元素图，也没有柔光层。"""
    html = home(client)
    for mode in ("desktop", "mobile"):
        for name in ("first_meet_forest", "quest_board", "memory_cottage", "mailbox", "whisper_pier"):
            assert f"scenes/island/{mode}/halo/{name}_{mode}.png" in html
    assert html.count('<img class="scene-halo"') == 10
    assert "scene-element" not in html and "scene-pop" not in html and "/hotspots/" not in html
    # 光圈按配置里的位置摆放（横版小信箱）
    box = scene.rect_box(content.load("scene")["island"]["shapes"]["desktop"]["mailbox"]["halo"], (2560, 1440))
    mailbox = style_of(html, r'<img class="scene-halo" src="[^"]*mailbox_desktop.png"')
    assert f"left: {box['left']}%; top: {box['top']}%; width: {box['width']}%; height: {box['height']}%" in mailbox


def test_loop_video_and_crisp_overlay_only_through_js(client):
    """循环视频：两套构图各一个（data-src，由 map.js 只给显示中的那套加载），缩小 0.9794 倍和底图对齐；
    上面的高清小岛也是 data-src，和视频一起加载。"""
    html = home(client)
    for mode in ("desktop", "mobile"):
        assert f'data-src="/static/usland/assets/scenes/island/{mode}/island_loop_{mode}.mp4"' in html
        assert f'data-src="/static/usland/assets/scenes/island/{mode}/island_detail_{mode}.webp"' in html
    assert html.count("--video-scale: 0.9794;") == 2
    assert "<video" not in html  # 视频元素由 JS 创建：没有 JS 时只显示静态底图
    assert "island_waves" not in html


def test_debug_mode(client):
    create_island(client)
    html = client.get("/?hotspots=1").get_data(as_text=True)
    assert "map-stage is-loading debug" in html
    assert "debug-id" in html


# ---------- 野餐垫上的两只动物 ----------


def test_slots_before_quiz(client, partner, app):
    put_animal(app, "result", "infp")
    setup_pair(client, partner, app)
    html = client.get("/").get_data(as_text=True)
    # 没做测试：两边都是中性占位剪影，不显示任何人格动物
    assert html.count("player_slot_left.png") == 2  # 横版、竖版各一次
    assert html.count("player_slot_right.png") == 2
    assert "animals/result/" not in html


def test_result_animal_on_blanket(client, partner, app):
    put_animal(app, "result", "infp")
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    html = client.get("/").get_data(as_text=True)
    assert "/static/usland/assets/animals/result/infp.png" in html
    # 交付必读第 3 条：宽 = 1024 × 0.25 = 256；左 = (1330 - 128) / 2560；上 = (850 - 256 × 0.94043) / 1440
    expected = scene.foot_box({"x": 1330, "y": 850, "scale": 0.25}, 0.94043, (2560, 1440))
    assert expected["left"] == pytest.approx(46.9531, abs=1e-3)
    assert expected["top"] == pytest.approx(42.3086, abs=1e-3)
    left = style_of(html, r'<button type="button" class="animal animal-left')
    assert f"left: {expected['left']}%; top: {expected['top']}%" in left
    # 两人状态独立：阿木还没测，右边仍是占位剪影
    assert "player_slot_right.png" in html
    assert "player_slot_left.png" not in html


def test_island_pose_preferred_over_result(client, partner, app):
    put_animal(app, "result", "infp")
    put_animal(app, "island", "infp")
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    html = client.get("/").get_data(as_text=True)
    assert "animals/island/infp.png" in html
    # 海岛姿态是 1536 画布，脚底比例 0.92，显示宽度仍按 1024 × scale
    expected = scene.foot_box({"x": 1330, "y": 850, "scale": 0.25}, 0.92, (2560, 1440))
    assert f"top: {expected['top']}%" in style_of(html, r'<button type="button" class="animal animal-left')


def test_mood_and_click_still_on_animal(client, partner, app):
    put_animal(app, "result", "infp")
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    client.post("/mood", data={"mood": "wronged"})
    html = partner.get("/").get_data(as_text=True)
    assert "animal animal-left mood-wronged" in html
    assert "mood-badge-wronged" in html
    # 自己的动物可以打开心情选择
    assert "data-mood-picker" in client.get("/").get_data(as_text=True)


# ---------- 森林石像 ----------


def test_default_slot_is_smaller_than_animal(client, partner, app):
    """默认形象比动物立绘小 30%（player_slot_scale = 0.7），脚底位置不变。"""
    put_animal(app, "result", "infp")
    setup_pair(client, partner, app)
    take_quiz(client, INFP)  # 小雨（左）做完测试，阿木（右）还是默认形象
    html = client.get("/").get_data(as_text=True)
    animal = style_of(html, r'<button type="button" class="animal animal-left')
    slot = style_of(html, r'<button type="button" class="animal animal-right')
    width = lambda style: float(re.search(r"width: ([\d.]+)%", style).group(1))
    assert abs(width(slot) / width(animal) - 0.7) < 0.001


def test_no_statue_until_file_delivered(client, partner, app):
    put_animal(app, "result", "infp")
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    html = client.get("/").get_data(as_text=True)
    # 石像还没交付：保持空底座，页面上不出现任何石像图片（浏览器不会去请求不存在的文件）
    assert "animals/statues/" not in html
    assert "statue-shadow" not in html


def test_statue_with_contact_shadow(client, partner, app):
    put_animal(app, "statues", "infp")
    put_animal(app, "statues", "estj")
    setup_pair(client, partner, app)
    html = client.get("/").get_data(as_text=True)
    assert "animals/statues/" not in html  # 还没做测试：没有石像
    take_quiz(client, INFP)
    html = client.get("/").get_data(as_text=True)
    assert html.count("animals/statues/infp.png") == 2
    assert "animals/statues/estj.png" not in html  # 阿木还没测：右边底座空着
    # 阴影在石像下面（先输出），并且只露出左边
    assert html.index("statue_pedestals_desktop.png") < html.index("animals/statues/infp.png")
    assert "clip-path: inset(0 75.0586% 0 0)" in html  # 中线 (548 + 729) / 2 = 638.5 → 24.9414%
    # 石像脚底在石台台面正中：横版左边台面中心 (548, 414)
    expected = scene.foot_box({"x": 548, "y": 414, "scale": 0.19}, 0.9375, (2560, 1440))
    statue = style_of(html, r'<img class="statue" src="[^"]*infp.png"')
    assert f"left: {expected['left']}%; top: {expected['top']}%" in statue
    # 石像本身也能点进初见森林（不进 Tab 顺序）
    assert html.count('class="hotspot hotspot-statue" href="/forest"') == 2
    assert 'tabindex="-1" aria-hidden="true"' in html
    take_quiz(partner, ESTJ)
    assert "animals/statues/estj.png" in client.get("/").get_data(as_text=True)


# ---------- 新用户引导 ----------


def test_forest_intro_first_visit_only(client):
    html = home(client)
    assert 'id="forest-intro"' in html
    assert "去初见森林" in html
    # 第二次进入不再自动弹出，但森林标签上仍有"从这里开始"
    html = client.get("/").get_data(as_text=True)
    assert 'id="forest-intro"' not in html
    assert "从这里开始" in html
    assert "region-label is-guide" in html


def test_no_forest_guide_after_quiz(client):
    create_island(client)
    take_quiz(client, INFP)
    html = client.get("/").get_data(as_text=True)
    assert 'id="forest-intro"' not in html
    assert "从这里开始" not in html


def test_forest_intro_again_after_new_login(client, app):
    create_island(client, nickname="小雨")
    client.get("/")
    client.post("/logout")
    client.post("/login", data={"member_id": member_id(app, "小雨"), "pin": "1234"})
    assert 'id="forest-intro"' in client.get("/").get_data(as_text=True)


# ---------- 功能页背景、回忆小屋 ----------


@pytest.mark.parametrize("url, name", [
    ("/whisper", "whisper/whisper_room"),
    ("/quest", "quest/quest_board"),
    ("/forest", "forest/forest_quiz"),
    ("/forest/quiz", "forest/forest_quiz"),
    ("/settings", "mailbox/mailbox_settings"),
])
def test_feature_page_backgrounds(client, url, name):
    create_island(client)
    html = client.get(url).get_data(as_text=True)
    assert "has-scene-bg" in html
    assert f"/static/usland/assets/scenes/{name}_desktop.webp" in html
    assert f"/static/usland/assets/scenes/{name}_mobile.webp" in html


def test_memory_room_spots(client):
    create_island(client)
    html = client.get("/memories").get_data(as_text=True)
    assert "memory_room_desktop.webp" in html and "memory_room_mobile.webp" in html
    for key in ("frames", "album", "postcards"):
        assert f'data-room-spot="{key}"' in html
        assert f"memory_{key}_desktop.png" in html  # 电脑版有柔光层
    # 相框 → 照片墙，相册 → 完整时间线，明信片 → 添加回忆
    assert 'href="#photo-wall"' in html
    assert 'href="#timeline"' in html
    assert 'href="#add-memory"' in html


# ---------- 图标、Logo、配色 ----------


def test_brand_icons_and_tokens(client):
    html = home(client)
    assert "usland/assets/ui/brand/favicon.svg" in html
    assert "usland/tokens.css" in html
    # 第三版设置图标（内联，颜色跟随文字）
    assert "M19 13.5v-3l-2.1-.6" in html
    assert 'stroke="currentColor"' in html


def test_welcome_preview_uses_island_base(raw_client):
    html = raw_client.get("/").get_data(as_text=True)
    assert "island_base_desktop.webp" in html and "island_base_mobile.webp" in html
    assert "logo_usland.svg" in html


# ---------- 入口、面板、功能页 ----------


def test_waiting_slot_when_alone(client):
    html = home(client)
    assert "等 TA 来" in html
    assert "waiting-compact" in html


def test_panels_for_board_and_mailbox(client):
    html = home(client)
    assert 'id="panel-quest_board"' in html
    assert 'id="panel-mailbox"' in html
    assert html.count('data-action="panel"') == 8  # 告示牌、小信箱 × 热区和标签 × 横竖两套


def test_feature_pages(client, raw_client):
    for url in ENTRY_URLS:
        assert raw_client.get(url).status_code == 302  # 未登录跳走
    create_island(client)
    for url in ENTRY_URLS:
        resp = client.get(url)
        assert resp.status_code == 200
        assert "即将开放" not in resp.get_data(as_text=True)
    assert 'action="/logout"' in client.get("/settings").get_data(as_text=True)


def test_bottom_nav_only_when_logged_in(client):
    assert "bottom-nav" not in client.get("/").get_data(as_text=True)
    assert "bottom-nav" in home(client)


def test_reconcile_pose_only_when_delivered(client, partner, app):
    setup_pair(client, partner, app)
    take_quiz(client, INFP)
    assert "animals/reconcile/" not in client.get("/whisper").get_data(as_text=True)
    put_animal(app, "reconcile", "infp")
    html = client.get("/whisper").get_data(as_text=True)
    assert "animals/reconcile/infp.png" in html  # 拥抱动画用和好姿态
