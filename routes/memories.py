"""回忆小屋：回忆时间线、手动添加回忆，以及照片访问路由 /media/<文件名>。

- GET  /memories        时间线（新的在前），卡片式：日期、类型图标、标题、一句话、照片
- POST /memories/add    手动添加一条回忆（一句话必填 ≤140 字 + 照片可选）
- GET  /media/<文件名>  照片：只能登录后访问，未登录 403；文件名不符合格式 404（防止路径穿越）
完全不使用 AI。
"""

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   send_from_directory, url_for)

from services import demo, images, memories, scene, sound
from services.auth import login_required
from services.i18n import t

bp = Blueprint("memories", __name__)


def _page(form_errors=None, form_note="", status=200):
    items = [memories.to_view(row) for row in memories.list_memories()]
    return render_template(
        "memories.html",
        items=items,
        # 有照片的回忆：点相框打开的照片墙
        photo_items=[m for m in items if m["photo"]],
        # 房间场景：相框 / 相册 / 明信片三个互动区域（第三版素材，见 content/scene.json 的 memory_room）
        room=scene.memory_room(),
        note_max=memories.NOTE_MAX,
        form_errors=form_errors,
        form_note=form_note,
    ), status


@bp.get("/memories")
@login_required
def index():
    return _page()


@bp.post("/memories/add")
@login_required
def add():
    note = (request.form.get("note") or "").strip()
    errors = {}
    if not note:
        errors["note"] = t("memories.errors.note_required")
    elif len(note) > memories.NOTE_MAX:
        errors["note"] = t("memories.errors.note_too_long")

    photo_name = None
    # 演示小岛大家共用：不保存照片，只保存文字
    upload = None if demo.enabled() else request.files.get("photo")
    if not errors and images.has_file(upload):
        try:
            photo_name = images.save_photo(upload, current_app.config["UPLOAD_DIR"])
        except images.PhotoError as error:
            errors["photo"] = t("photo.errors." + error.code)

    if errors:
        # 出错时重新显示页面并自动打开添加窗口，已写的文字保留
        return _page(form_errors=errors, form_note=note, status=400)

    memories.add_manual(g.user["id"], note, photo_name)
    flash(t("memories.added"), "info")
    sound.cue("memory_save")
    return redirect(url_for("memories.index"))


@bp.get("/media/<filename>")
def media(filename):
    """提供上传的照片。只有小岛成员登录后才能看。"""
    if g.get("user") is None:
        abort(403)
    if not images.is_media_name(filename):
        abort(404)
    resp = send_from_directory(current_app.config["UPLOAD_DIR"], filename, mimetype="image/jpeg")
    # private：只允许浏览器自己缓存，不允许中间的代理服务器缓存
    resp.headers["Cache-Control"] = "private, max-age=86400"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp
