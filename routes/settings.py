"""小信箱：小岛设置（USLAND_SPEC.md 第 10 节）。

- GET  /settings                 设置页
- POST /settings/profile         修改小岛名、自己的昵称、语言
- POST /settings/key             填写 / 替换 DeepSeek API key（先测试，成功才保存）
- POST /settings/key/test        测试当前保存的 key 还能不能用
- POST /settings/key/delete      删除 key
- POST /settings/motion          减少动态效果（只存在这台设备的 Cookie 里）
- POST /settings/reset-code      另一半忘记 PIN 时，为 TA 生成一次性重置码（只显示一次）
退出登录用 auth.logout（POST /logout）。
API key 永远不返回给前端：页面上只显示末尾 4 位，例如 sk-****a3f9。
"""

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from db import get_db
from services import ai, auth, sound, whisper
from services.auth import login_required
from services.i18n import LANG_COOKIE, SUPPORTED_LANGS, t

bp = Blueprint("settings", __name__)

# 刚生成的重置码：存在 session 里，设置页显示一次后就删掉（数据库里只有哈希）
RESET_CODE_SHOWN = "reset_code_shown"

# "减少动态效果"开关的 Cookie：值为 reduce 时全站关闭动画（系统设置了减少动态效果时也会关闭）
MOTION_COOKIE = "motion"


def _back():
    return redirect(url_for("settings.index"))


@bp.get("/settings")
@login_required
def index():
    key = whisper.get_api_key()
    return render_template(
        "settings.html",
        masked_key=whisper.mask_key(key),  # 只有末尾 4 位
        has_key=key is not None,
        partner=auth.get_partner(g.user["id"]),
        reset_minutes=auth.RESET_CODE_MINUTES,
        new_reset_code=session.pop(RESET_CODE_SHOWN, None),
    )


@bp.post("/settings/reset-code")
@login_required
def reset_code():
    """另一半忘记了 PIN：生成一次性重置码，跳回设置页显示一次。"""
    partner = auth.get_partner(g.user["id"])
    if partner is None:
        flash(t("settings.reset_needs_partner"), "error")
        return _back()
    code, _expires = auth.create_reset_code(partner["id"])
    session[RESET_CODE_SHOWN] = code
    sound.cue("ui_success")
    return _back()


@bp.post("/settings/profile")
@login_required
def profile():
    island_name = (request.form.get("island_name") or "").strip()
    nickname = (request.form.get("nickname") or "").strip()
    lang = request.form.get("lang", "")

    if not island_name or len(island_name) > auth.ISLAND_NAME_MAX:
        flash(t("errors.island_name"), "error")
        return _back()
    if not nickname or len(nickname) > auth.NICKNAME_MAX:
        flash(t("errors.nickname"), "error")
        return _back()
    partner = auth.get_partner(g.user["id"])
    if partner is not None and partner["nickname"] == nickname:
        # 登录时按昵称选人，两人的昵称不能一样
        flash(t("errors.nickname_taken"), "error")
        return _back()
    if lang not in SUPPORTED_LANGS:
        lang = g.user["lang"]

    db = get_db()
    db.execute("UPDATE island SET name = ? WHERE id = 1", (island_name,))
    db.execute("UPDATE members SET nickname = ?, lang = ? WHERE id = ?", (nickname, lang, g.user["id"]))
    db.commit()
    g.user_lang = lang  # 提示文字用新的语言
    flash(t("settings.saved"), "info")
    sound.cue("ui_success")
    resp = _back()
    resp.set_cookie(LANG_COOKIE, lang, max_age=365 * 24 * 3600, httponly=True, samesite="Lax")
    return resp


@bp.post("/settings/key")
@login_required
def save_key():
    """替换 key：先发一个极小的请求测试，成功才保存。"""
    key = (request.form.get("api_key") or "").strip()
    if not whisper.looks_like_key(key):
        flash(t("whisper.key.format"), "error")
        return _back()
    result = ai.check_key(key)
    if result != ai.OK:
        flash(t("whisper.errors." + result), "error")
        return _back()
    whisper.save_api_key(key)
    flash(t("settings.key_saved"), "info")
    sound.cue("ui_success")
    return _back()


@bp.post("/settings/key/test")
@login_required
def test_key():
    key = whisper.get_api_key()
    if key is None:
        flash(t("settings.key_none"), "error")
        return _back()
    result = ai.check_key(key)
    if result == ai.OK:
        flash(t("settings.key_ok"), "info")
        sound.cue("ui_success")
    else:
        flash(t("whisper.errors." + result), "error")
    return _back()


@bp.post("/settings/key/delete")
@login_required
def delete_key():
    whisper.save_api_key(None)
    flash(t("settings.key_deleted"), "info")
    sound.cue("ui_success")
    return _back()


@bp.post("/settings/motion")
@login_required
def motion():
    """减少动态效果：打开后所有动画都不播放（初见森林的散步、揭晓、撒花等），功能不受影响。"""
    reduce = request.form.get("reduce") == "1"
    flash(t("settings.motion_saved"), "info")
    resp = _back()
    resp.set_cookie(MOTION_COOKIE, "reduce" if reduce else "full", max_age=365 * 24 * 3600,
                    httponly=True, samesite="Lax")
    return resp
