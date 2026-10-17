"""把团队提供的 PNG 素材转换成体积更小的 WebP（使用 Pillow）。

用法（在项目根目录）：
    python scripts/optimize_images.py

做的事情：
1. static/img/scene/ 和 static/img/animals/ 下的每个 .png，生成同名 .webp（保留透明背景）
2. 底图 base_desktop / base_mobile 另外生成 -1280 和 -2560 两种宽度（比原图宽的不生成，不放大）

注意（2026-10-17）：第三版美术素材（static/usland/assets/）已经按交付的格式和路径直接使用
（主岛和功能页背景是 WebP，动物和柔光层是 PNG，路径见 content/scene.json 和 content/character_assets.json），
页面不再读取 static/img/scene/ 和 static/img/animals/，所以目前不需要运行这个脚本。
保留它是为了以后需要自己压缩新素材时参考。原来的 .png 不会被删除；已经是最新的 .webp 会跳过。
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCENE_DIR = ROOT / "static" / "img" / "scene"
ANIMAL_DIR = ROOT / "static" / "img" / "animals"  # 第二版的动物图片（第三版起不再使用）

QUALITY = 85
BASE_NAMES = ("base_desktop", "base_mobile")
BASE_WIDTHS = (1280, 2560)


def is_up_to_date(src, dst):
    return dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime


def save_webp(im, dst):
    im.save(dst, "WEBP", quality=QUALITY, method=6)
    print(f"  生成 {dst.relative_to(ROOT)}（{dst.stat().st_size // 1024} KB）")


def convert(png):
    webp = png.with_suffix(".webp")
    with Image.open(png) as im:
        # 有透明通道的保留 RGBA，否则转成 RGB
        im = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
        if not is_up_to_date(png, webp):
            save_webp(im, webp)
        else:
            print(f"  跳过 {webp.relative_to(ROOT)}（已是最新）")

        if png.stem in BASE_NAMES:
            for width in BASE_WIDTHS:
                if width >= im.width:
                    continue  # 不放大
                dst = png.with_name(f"{png.stem}-{width}.webp")
                if is_up_to_date(png, dst):
                    continue
                height = round(im.height * width / im.width)
                save_webp(im.resize((width, height), Image.LANCZOS), dst)


def main():
    pngs = []
    for folder in (SCENE_DIR, ANIMAL_DIR):
        if folder.exists():
            pngs += sorted(folder.rglob("*.png"))
    if not pngs:
        print("没有找到需要转换的 PNG。")
        return
    print(f"找到 {len(pngs)} 个 PNG：")
    for png in pngs:
        print(f"- {png.relative_to(ROOT)}")
        convert(png)
    print("完成。")


if __name__ == "__main__":
    main()
