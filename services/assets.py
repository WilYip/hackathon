"""第三版美术素材（static/usland/assets/，说明见 docs/ui-v3/）的路径工具。

- 所有素材路径都写成"相对 static/usland/assets/ 的路径"，例如 scenes/island/desktop/island_base_desktop.webp
- 动物相关的图片（结果立绘、海岛姿态、石像、和好姿态）路径按 content/character_assets.json
  （= docs/ui-v3/integration/character_asset_contract.json）
- 文件是否存在一律在服务器端判断：缺少的图片不会出现在页面上，浏览器不会去请求不存在的图片
- 每次请求都会检查文件，所以队友把新素材放进对应路径后，刷新页面就能看到，不用重启
"""

from pathlib import Path

from flask import current_app, url_for
from markupsafe import Markup

from services import content

URL_PREFIX = "usland/assets"

_svg_cache = {}


def asset_dir():
    """素材根目录 static/usland/assets/。"""
    return Path(current_app.config["USLAND_ASSET_DIR"])


def animal_dir():
    """动物图片目录（默认 static/usland/assets/animals/，测试时可以换成临时目录）。"""
    return Path(current_app.config["ANIMAL_DIR"])


def _file(rel):
    """相对路径对应的本地文件。animals/ 下的文件在 animal_dir() 里找。"""
    if rel.startswith("animals/"):
        return animal_dir() / rel[len("animals/"):]
    return asset_dir() / rel


def exists(rel):
    return bool(rel) and _file(rel).is_file()


def url(rel):
    """素材的网址（用 url_for 生成）。"""
    return url_for("static", filename=f"{URL_PREFIX}/{rel}")


def url_if_exists(rel):
    """文件存在时返回网址，否则返回 None。"""
    return url(rel) if exists(rel) else None


def fill(pattern, **values):
    """把路径模板里的 {mode}、{side}、{code} 换成实际的值。"""
    return pattern.format(**values) if pattern else None


# ---------- 动物图片（content/character_assets.json） ----------


def contract():
    return content.load("character_assets")


def character_image(kind, code):
    """某种动物图片：kind 是 result（结果立绘）/ island（海岛姿态）/ statues（石像）/ reconcile（和好姿态）。
    文件存在时返回 {"rel": 相对路径, "src": 网址, "pivot": 脚底在画布中的高度比例}，否则返回 None。"""
    if not code:
        return None
    spec = contract()[kind]
    rel = spec["pathPattern"].removeprefix("assets/").format(code=code.lower())
    if not exists(rel):
        return None
    return {"rel": rel, "src": url(rel), "pivot": spec["pivotNormalized"][1]}


# ---------- 界面图标（ui/icons/icon_*.svg） ----------


def icon_svg(name, size=22):
    """第三版的 SVG 图标，内联输出（颜色改成 currentColor，跟随文字颜色）。没有这个图标时返回 None。"""
    path = asset_dir() / "ui" / "icons" / f"icon_{name}.svg"
    if not path.is_file():
        return None
    key = (str(path), path.stat().st_mtime)
    if key not in _svg_cache:
        svg = path.read_text(encoding="utf-8").strip()
        svg = svg.replace("#263F46", "currentColor").replace("#263f46", "currentColor")
        # 去掉原来的宽高，换成统一的 class 和无障碍属性
        svg = svg.replace(' width="24" height="24"', "", 1)
        svg = svg.replace("<svg ", '<svg class="icon" aria-hidden="true" focusable="false" '
                                    'width="{size}" height="{size}" ', 1)
        _svg_cache[key] = svg
    return Markup(_svg_cache[key].replace("{size}", str(int(size))))
