"""上传照片的校验和压缩（约会选选选完成任务、回忆小屋手动添加都会用到）。

规则（USLAND_SPEC.md 第 7.1 节）：
- 只接受 jpg / png / webp，最大 5MB
- 不只看扩展名：用 Pillow 真正打开图片，确认文件内容也是这三种格式
- 压缩成最长边 1280px 的 JPEG，随机文件名，保存到 DATA_DIR/uploads/
- 重新保存时不带 EXIF（手机照片里可能有 GPS 位置），并按 EXIF 方向把照片转正
照片只能通过需要登录的 /media/<文件名> 访问（见 routes/memories.py）。
"""

import io
import re
import secrets
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024  # 5MB
MAX_SIDE = 1280
JPEG_QUALITY = 85
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PIXELS = 40_000_000  # 超过 4000 万像素的图片拒绝（防止"解压炸弹"占满内存）

# 保存后的文件名：32 位十六进制 + .jpg，/media 路由只认这种名字（防止路径穿越）
MEDIA_NAME = re.compile(r"^[0-9a-f]{32}\.jpg$")


class PhotoError(Exception):
    """照片不合格。code：bad_type 格式不对 / too_large 太大 / broken 打不开。"""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def is_media_name(name):
    return bool(MEDIA_NAME.match(name or ""))


def has_file(file_storage):
    """表单里是否真的选了文件（没选时浏览器也会提交一个空文件字段）。"""
    return file_storage is not None and bool(file_storage.filename)


def save_photo(file_storage, upload_dir):
    """校验并压缩上传的照片，返回保存后的文件名；不合格时抛出 PhotoError。"""
    ext = Path(file_storage.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise PhotoError("bad_type")

    # 最多读 5MB + 1 字节：读到第 5MB+1 个字节就说明超了
    data = file_storage.stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise PhotoError("too_large")
    if not data:
        raise PhotoError("broken")

    try:
        with warnings.catch_warnings():
            # 像素过多时 Pillow 只发警告，这里把警告也当成错误
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format not in ALLOWED_FORMATS:
                    raise PhotoError("bad_type")
                if probe.width * probe.height > MAX_PIXELS:
                    raise PhotoError("too_large")
                probe.verify()  # 检查文件是否完整

            # verify() 之后不能再用，需要重新打开
            with Image.open(io.BytesIO(data)) as im:
                im = ImageOps.exif_transpose(im)  # 按拍摄方向转正
                im = _to_rgb(im)
                im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
                name = secrets.token_hex(16) + ".jpg"
                Path(upload_dir).mkdir(parents=True, exist_ok=True)
                # 不传 exif 参数，保存出来的 JPEG 就不带 EXIF（包括 GPS）
                im.save(Path(upload_dir) / name, "JPEG", quality=JPEG_QUALITY, optimize=True)
                return name
    except PhotoError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PhotoError("broken") from None
    except (OSError, ValueError, SyntaxError):
        # 文件损坏、截断等
        raise PhotoError("broken") from None


def _to_rgb(im):
    """JPEG 不支持透明：透明背景铺成白色，其他模式统一转成 RGB。"""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        background = Image.new("RGB", im.size, (255, 255, 255))
        background.paste(im, mask=im.getchannel("A"))
        return background
    return im.convert("RGB")


def delete_photo(name, upload_dir):
    """删除一张照片（例如保存回忆失败时清理）。"""
    if is_media_name(name):
        (Path(upload_dir) / name).unlink(missing_ok=True)
