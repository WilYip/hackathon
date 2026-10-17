"""照片校验与压缩（services/images.py），以及登录保护的 /media 路由。"""

import io

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from services import images
from services.images import PhotoError, save_photo
from tests.test_auth import create_island


def make_upload(filename, fmt="JPEG", size=(200, 100), mode="RGB", color=(200, 120, 150), exif=None, raw=None):
    """构造一个像浏览器上传那样的文件对象。"""
    if raw is None:
        buf = io.BytesIO()
        im = Image.new(mode, size, color)
        kwargs = {"exif": exif} if exif is not None else {}
        im.save(buf, fmt, **kwargs)
        raw = buf.getvalue()
    return FileStorage(stream=io.BytesIO(raw), filename=filename)


def test_saves_jpeg_png_webp(tmp_path):
    for filename, fmt in (("a.jpg", "JPEG"), ("b.JPEG", "JPEG"), ("c.png", "PNG"), ("d.webp", "WEBP")):
        name = save_photo(make_upload(filename, fmt), tmp_path)
        assert images.is_media_name(name)
        with Image.open(tmp_path / name) as im:
            assert im.format == "JPEG"
            assert im.size == (200, 100)


def test_resizes_longest_side_to_1280(tmp_path):
    name = save_photo(make_upload("big.png", "PNG", size=(3000, 1500)), tmp_path)
    with Image.open(tmp_path / name) as im:
        assert im.size == (1280, 640)
    name = save_photo(make_upload("tall.jpg", size=(1000, 2560)), tmp_path)
    with Image.open(tmp_path / name) as im:
        assert im.size == (500, 1280)


def test_transparent_png_gets_white_background(tmp_path):
    name = save_photo(make_upload("clear.png", "PNG", mode="RGBA", color=(0, 0, 0, 0)), tmp_path)
    with Image.open(tmp_path / name) as im:
        r, g, b = im.getpixel((10, 10))
        assert r > 240 and g > 240 and b > 240


def test_exif_is_removed_and_rotation_applied(tmp_path):
    exif = Image.Exif()
    exif[0x0112] = 6  # 方向：需要顺时针转 90 度
    exif[0x010F] = "SecretCameraMaker"
    name = save_photo(make_upload("phone.jpg", size=(300, 100), exif=exif.tobytes()), tmp_path)
    with Image.open(tmp_path / name) as im:
        assert im.size == (100, 300)  # 已经转正
        assert len(im.getexif()) == 0  # 不带任何 EXIF
    assert b"SecretCameraMaker" not in (tmp_path / name).read_bytes()


def test_rejects_wrong_extension(tmp_path):
    with pytest.raises(PhotoError) as err:
        save_photo(make_upload("photo.gif", "GIF"), tmp_path)
    assert err.value.code == "bad_type"
    with pytest.raises(PhotoError):
        save_photo(make_upload("notes.txt", raw=b"hello"), tmp_path)


def test_rejects_fake_image_with_image_extension(tmp_path):
    # 扩展名是 .jpg，但内容不是图片
    with pytest.raises(PhotoError) as err:
        save_photo(make_upload("fake.jpg", raw=b"<html>not an image</html>"), tmp_path)
    assert err.value.code == "broken"
    # 扩展名是 .png，内容其实是 GIF
    with pytest.raises(PhotoError) as err:
        save_photo(make_upload("sneaky.png", "GIF"), tmp_path)
    assert err.value.code == "bad_type"


def test_rejects_files_over_5mb(tmp_path):
    raw = b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024)  # 刚好超过 5MB
    with pytest.raises(PhotoError) as err:
        save_photo(make_upload("huge.jpg", raw=raw), tmp_path)
    assert err.value.code == "too_large"
    assert list(tmp_path.iterdir()) == []  # 没有留下任何文件


def test_rejects_truncated_image(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), (10, 20, 30)).save(buf, "PNG")
    with pytest.raises(PhotoError):
        save_photo(make_upload("cut.png", raw=buf.getvalue()[:200]), tmp_path)


def test_media_name_pattern():
    assert images.is_media_name("0123456789abcdef0123456789abcdef.jpg")
    for bad in ("../secret_key", "..%2Fsecret_key", "abc.jpg", "0123456789abcdef0123456789abcdef.png",
                "0123456789ABCDEF0123456789ABCDEF.jpg", ""):
        assert not images.is_media_name(bad)


# ---------- /media 路由 ----------


def test_media_requires_login(client, raw_client, app):
    name = save_photo(make_upload("a.jpg"), app.config["UPLOAD_DIR"])
    assert raw_client.get(f"/media/{name}").status_code == 403  # 未登录不能看

    create_island(client)
    resp = client.get(f"/media/{name}")
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    assert "private" in resp.headers["Cache-Control"]


def test_media_rejects_bad_names_and_missing_files(client, app):
    create_island(client)
    assert client.get("/media/secret_key").status_code == 404
    assert client.get("/media/..%2Fsecret_key").status_code == 404
    assert client.get("/media/0123456789abcdef0123456789abcdef.jpg").status_code == 404
