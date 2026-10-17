"""全站统一的动物头像（首页名牌、顶部栏、温柔传话、约会选选选、初见森林、登录页都用这里）。

图片是第三版美术素材（static/usland/assets/，路径规则见 content/character_assets.json）：
    animals/result/<代码小写>.png      16 种动物的结果立绘（1024×1024 透明画布）
    animals/reconcile/<代码小写>.png   和好姿态（等待队友交付，到位后温柔传话的拥抱动画自动使用）
    ui/placeholders/avatar_placeholder.png   还没做测试时的默认形象头像（白色黏土小人的头部特写）
    animals/spirit.webp                （可选）初见森林里引导测试的森林小精灵

规则（交付必读第 4 条）：
- 做过测试：用对应动物的结果立绘；图片缺失 → 圆形占位头像，写动物名首字（如"兔"）
- 没做过测试：中性占位头像，不显示任何人格动物
文件是否存在都在服务器端判断，不让浏览器请求不存在的图片。不在代码里绘制任何动物插画。
"""

from flask import url_for

from services import assets, content, mood
from services.i18n import tr

IMAGE_EXTS = (".webp", ".png")
PLACEHOLDER = "ui/placeholders/avatar_placeholder.png"


def find_image(name):
    """动物目录根下的 name.webp 或 name.png（目前只有可选的 spirit）；都没有返回 None。"""
    for ext in IMAGE_EXTS:
        path = assets.animal_dir() / f"{name}{ext}"
        if path.exists():
            return path
    return None


def image_url(path):
    return assets.url(f"animals/{path.name}")


def animal_info(code):
    """动物的文案（content/animals.json），没有则 None。"""
    if not code:
        return None
    return content.load("animals")["animals"].get(code)


def avatar_for(member, index):
    """一位成员的头像信息。index 是加入顺序（0 或 1），决定占位底色。
    返回 {"src": 图片网址或 None, "initial": 占位头像上的字, "animal_name": 动物名（没做测试为 None）,
          "code": 动物代码, "index": 1 或 2, "is_placeholder": 是否是测试前的中性占位}"""
    code = member["animal_code"] if member is not None else None
    animal = animal_info(code)
    if animal is not None:
        image = assets.character_image("result", code)
        return {
            "src": image["src"] if image else None,
            "initial": tr(animal["initial"]),
            "animal_name": tr(animal["name"]),
            "code": code,
            "index": index + 1,
            "is_placeholder": False,
        }
    # 还没做测试：中性占位头像
    return {
        "src": assets.url_if_exists(PLACEHOLDER),
        "initial": member["nickname"][:1] if member is not None else "?",
        "animal_name": None,
        "code": None,
        "index": index + 1,
        "is_placeholder": True,
    }


def person(member, index, viewer_id=None):
    """页面上显示一个人需要的全部信息：昵称 + 头像。"""
    info = avatar_for(member, index)
    info.update({"id": member["id"], "nickname": member["nickname"],
                 "is_me": viewer_id is not None and member["id"] == viewer_id,
                 # 现在的心情（VISUAL_DESIGN 13.4），见 services/mood.py
                 "mood": mood.view(mood.of(member), member["nickname"]),
                 # 和好姿态（等待队友交付）：有图片时温柔传话的拥抱动画用它，否则用头像
                 "reconcile_src": (assets.character_image("reconcile", info["code"]) or {}).get("src")})
    return info


def everyone(members, viewer_id=None):
    """按加入顺序排列的所有成员（顶部栏、登录页用）。"""
    return [person(m, i, viewer_id) for i, m in enumerate(members)]


def pair(members, viewer_id):
    """{"me": 我, "partner": 另一半（还没加入时为 None）}"""
    result = {"me": None, "partner": None}
    for p in everyone(members, viewer_id):
        result["me" if p["is_me"] else "partner"] = p
    return result


def spirit_url():
    """森林小精灵的图片（可选）。"""
    path = find_image("spirit")
    return image_url(path) if path else None
