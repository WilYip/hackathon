"""小岛首页场景（第三版美术素材，说明见 docs/ui-v3/交付必读-v3.md）。

- 两套构图：横版 desktop（2560×1440）和竖版 mobile（1440×2560，屏幕宽度 ≤700px 时使用）
- 坐标全部来自 content/scene_anchors.json（底图像素），这里换算成百分比：
  场景容器保持底图原比例，所有东西用百分比定位，所以任何屏幕大小下都和底图对齐
- 底图上叠一段 5 秒循环视频（固定机位，map.js 交叉淡入淡出循环，藏住首尾接缝）
- 五个入口：HTML 热区（可以 Tab 聚焦）+ 悬停 / 聚焦时放大的场景元素（小船、信箱、小屋、告示牌、两个石台）
- 两只动物站在野餐垫上：做过测试 → 海岛姿态（有的话）或结果立绘；没做测试 → 默认形象（白色黏土小人，左睁眼、右眯眼笑）
- 森林里的两座石像：做过测试并且石像图片存在时才显示，下面先垫一层接触阴影；否则保持空底座

脚底换算（交付必读第 3 条）：图片显示宽度 = 1024 × scale（底图像素），
图片左上角 = (x - 宽/2, y - 宽 × 脚底比例)。1536 画布的素材按同一个显示宽度换算。
"""

from services import animals, assets, content, mood
from services.i18n import tr
from flask import url_for

MODES = ("desktop", "mobile")
SIDES = ("left", "right")
RESULT_CANVAS = 1024  # 结果立绘的画布宽度，scale 以它为准


def _pct(value, total):
    return round(value / total * 100, 4)


def _anchors(mode):
    return content.load("scene_anchors")[mode]


def _cfg():
    return content.load("scene")


def _region_info():
    """把 regions.json 整理成 {id: {...}}（按文件里的顺序，也就是 Tab 键的顺序），带上当前语言的名字。"""
    info = {}
    for r in content.regions():
        info[r["id"]] = {
            "id": r["id"],
            "name": tr(r["name"]),
            "short": tr(r["short"]),
            "icon": r["icon"],
            "url": url_for(r["endpoint"]),
            "action": r["action"],
        }
    return info


def rect_box(rect, canvas):
    """[左, 上, 右, 下]（底图像素）→ 百分比 left / top / width / height。"""
    w, h = canvas
    x1, y1, x2, y2 = rect
    return {"left": _pct(x1, w), "top": _pct(y1, h), "width": _pct(x2 - x1, w), "height": _pct(y2 - y1, h)}


def foot_box(anchor, pivot, canvas):
    """按脚底锚点 {x, y, scale} 算出正方形图片的位置（百分比）。"""
    w, h = canvas
    size = RESULT_CANVAS * anchor["scale"]  # 图片显示宽度（底图像素）
    return {
        "left": _pct(anchor["x"] - size / 2, w),
        "top": _pct(anchor["y"] - size * pivot, h),
        "width": _pct(size, w),
        "height": _pct(size, h),
    }


# ---------- 两只动物 ----------


def _player_sprite(member, side):
    """一只动物在地图上用哪张图：海岛姿态 → 结果立绘 → 默认形象（没做测试）。"""
    code = member["animal_code"] if member is not None else None
    if code and animals.animal_info(code):
        for kind in ("island", "result"):
            image = assets.character_image(kind, code)
            if image:
                return {"src": image["src"], "pivot": image["pivot"], "is_slot": False}
    island = _cfg()["island"]
    return {
        "src": assets.url(assets.fill(island["player_slot"], side=side)),
        "pivot": island["player_slot_pivot"],
        "is_slot": True,
        "scale": island.get("player_slot_scale", 1),  # 默认形象比动物小一点
    }


def _players(mode, canvas, members, current_user_id):
    """野餐垫上的两只动物：第一位成员在左边，第二位在右边。"""
    result = []
    for i, side in enumerate(SIDES):
        member = members[i] if i < len(members) else None
        anchor = _anchors(mode)["players"][side]
        sprite = _player_sprite(member, side)
        avatar = animals.avatar_for(member, i) if member is not None else None
        result.append({
            "side": side,
            "member": member,
            "is_me": member is not None and member["id"] == current_user_id,
            "nickname": member["nickname"] if member is not None else None,
            "avatar": avatar,
            "img": sprite["src"],
            "is_slot": sprite["is_slot"],
            "animal_name": avatar["animal_name"] if avatar else None,
            # 心情（开心挥爪 / 委屈垂耳 / 需要空间缩小 + 小窝），见 services/mood.py
            "mood": mood.view(mood.of(member), member["nickname"]) if member is not None else None,
            "box": foot_box({**anchor, "scale": anchor["scale"] * sprite.get("scale", 1)}, sprite["pivot"], canvas),
            # 名牌：脚底正下方一点点
            "label": {"x": _pct(anchor["x"], canvas[0]), "y": _pct(anchor["y"] + canvas[1] * 0.02, canvas[1])},
            "index": i,
        })
    return result


def _statues(mode, canvas, members):
    """森林底座上的石像：做过测试、并且石像图片已经交付时才显示（服务器端判断文件是否存在）。
    接触阴影图 statue_pedestals_* 同时包含左右两个底座的阴影，用 clip 只露出有石像的那一边。"""
    anchors = _anchors(mode)["statues"]
    middle = _pct((anchors["left"]["x"] + anchors["right"]["x"]) / 2, canvas[0])
    shadow = assets.url_if_exists(assets.fill(_cfg()["island"]["statue_shadow"], mode=mode))
    result = []
    for i, side in enumerate(SIDES):
        member = members[i] if i < len(members) else None
        code = member["animal_code"] if member is not None else None
        statue = assets.character_image("statues", code)
        if not statue:
            continue  # 保持空底座
        result.append({
            "side": side,
            "src": statue["src"],
            "box": foot_box(anchors[side], statue["pivot"], canvas),
            "shadow": shadow,
            # 阴影只显示这一边：左边裁掉中线右侧，右边裁掉中线左侧
            "clip": f"inset(0 {round(100 - middle, 4)}% 0 0)" if side == "left" else f"inset(0 0 0 {middle}%)",
            "name": member["nickname"],
        })
    return result


# ---------- 五个入口 ----------


def _element(mode, canvas, region_id, r):
    """悬停时放大的场景元素：图片网址、位置（百分比），以及放大的原点（元素底边中点，百分比）。
    图片不存在时返回 None（那就只有标签抬起，没有放大效果）。"""
    src = assets.url_if_exists(assets.fill(r.get("element"), mode=mode))
    rect = _cfg()["island"].get("elements", {}).get(mode, {}).get(region_id)
    if not src or not rect:
        return None
    x1, y1, x2, y2 = rect
    return {
        "src": src,
        "box": rect_box(rect, canvas),
        "origin_x": _pct((x1 + x2) / 2, canvas[0]),
        "origin_y": _pct(y2, canvas[1]),
    }


def _regions(mode, canvas, regions):
    island = _cfg()["island"]
    hotspots = _anchors(mode)["hotspots"]
    labels = island["labels"][mode]
    items = []
    for region_id, info in regions.items():
        r = island["regions"][region_id]
        lx, ly = labels[region_id]
        items.append({
            **info,
            "box": rect_box(hotspots[r["anchor"]], canvas),
            "label": {"x": _pct(lx, canvas[0]), "y": _pct(ly, canvas[1])},
            # 悬停 / 聚焦时放大的场景元素：温柔传话-小船、小信箱-信箱、回忆小屋-小屋、约会选选选-告示牌、初见森林-两个石台
            "element": _element(mode, canvas, region_id, r),
        })
    return items


def _layout(mode, regions, members, current_user_id):
    canvas = tuple(_anchors(mode)["canvas"])
    island = _cfg()["island"]
    return {
        "name": mode,
        "ratio_w": canvas[0],
        "ratio_h": canvas[1],
        "base": assets.url(assets.fill(island["base"], mode=mode)),
        # 5 秒循环视频（和底图同构图）；scale 让视频画面和底图对齐
        "video": assets.url_if_exists(assets.fill(island.get("loop_video"), mode=mode)),
        "video_scale": island.get("loop_video_scale", 1),
        "regions": _regions(mode, canvas, regions),
        "animals": _players(mode, canvas, members, current_user_id),
        "statues": _statues(mode, canvas, members),
    }


def build_scene(members, current_user_id):
    """首页需要的全部场景数据：横版、竖版两套构图（CSS 按屏幕宽度显示其中一套）。"""
    regions = _region_info()
    return {"layouts": [_layout(mode, regions, members, current_user_id) for mode in MODES]}


# ---------- 其他页面用到的场景图 ----------


def preview_image():
    """欢迎页 / 邀请页的小岛插图：横版和竖版底图。"""
    base = _cfg()["island"]["base"]
    desktop, mobile = (_anchors(m)["canvas"] for m in MODES)
    return {
        "src": assets.url(assets.fill(base, mode="desktop")),
        "src_mobile": assets.url(assets.fill(base, mode="mobile")),
        "ratio_w": desktop[0],
        "ratio_h": desktop[1],
        "ratio_w_mobile": mobile[0],
        "ratio_h_mobile": mobile[1],
    }


def page_background(name):
    """功能页的背景图 {"desktop": 网址, "mobile": 网址}；name 是 whisper / quest / forest / memory / mailbox。"""
    pattern = _cfg()["page_backgrounds"].get(name)
    if not pattern:
        return None
    urls = {mode: assets.url_if_exists(assets.fill(pattern, mode=mode)) for mode in MODES}
    return urls if urls["desktop"] and urls["mobile"] else None


def memory_room():
    """回忆小屋的房间场景：背景 + 相框 / 相册 / 明信片三个互动区域（两套构图）。"""
    room = _cfg()["memory_room"]
    layouts = []
    for mode in MODES:
        canvas = tuple(_anchors(mode)["canvas"])
        spots = []
        for key, spot in room["spots"][mode].items():
            spots.append({
                "key": key,
                "box": rect_box(spot["rect"], canvas),
                "glow": assets.url_if_exists(spot["glow"]) if spot.get("glow") else None,
            })
        layouts.append({
            "name": mode,
            "ratio_w": canvas[0],
            "ratio_h": canvas[1],
            "background": assets.url(assets.fill(room["background"], mode=mode)),
            "spots": spots,
        })
    return layouts
