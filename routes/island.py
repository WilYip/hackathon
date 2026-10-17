"""首页（小岛地图）与语言切换。

首页根据状态显示不同页面：
- 还没有小岛        → 欢迎页（创建）
- 有小岛但没登录    → 跳转登录页
- 已登录            → 小岛场景（第三版素材，见 services/scene.py）
"""

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from db import get_db
from services import auth, mood, quest, scene, whisper
from services.auth import login_required
from services.i18n import LANG_COOKIE, PICKED_LANG, SUPPORTED_LANGS, t

bp = Blueprint("island", __name__)


@bp.get("/")
def index():
    if g.user:
        # ?hotspots=1：调试模式，显示所有热区和图层边框，方便对齐坐标
        debug = request.args.get("hotspots") == "1"
        # 还没做初见森林测试：森林入口一直有"从这里开始"的小提示；
        # 第一次进入小岛时（这次登录里第一次）另外弹出一个温和的引导窗口
        needs_forest = not g.user["animal_code"]
        forest_intro = needs_forest and not session.get("forest_intro_seen")
        if forest_intro:
            session["forest_intro_seen"] = True
        return render_template(
            "map.html",
            scene=scene.build_scene(auth.get_members(), g.user["id"]),
            debug=debug,
            needs_forest=needs_forest,
            forest_intro=forest_intro,
            # 传话码头的未读消息数：有未读时显示信封标记和文字
            whisper_unread=whisper.unread_count(g.user["id"]),
            # 告示牌提示：your_turn 轮到我选 / proposal 对方提议了任务；没有则为 None
            quest_attention=quest.attention(g.user["id"]),
            # 心情选择窗口（点自己的动物时打开）
            mood_options=mood.options(),
            my_mood=mood.of(g.user),
        )
    if auth.get_island() is None:
        return render_template("welcome.html", preview=scene.preview_image())
    return redirect(url_for("auth.login"))


def _safe_next(default="/"):
    """只允许跳回本站路径，防止被利用跳转到外部网站。"""
    next_url = request.form.get("next", default)
    if not next_url.startswith("/") or next_url.startswith("//"):
        return default
    return next_url


@bp.post("/mood")
@login_required
def set_mood():
    """在首页点自己的动物后选择心情（只能设置自己的心情）。
    "清除心情"或再点一次当前的心情 = 取消，回到平静。"""
    picked = request.form.get("mood", "")
    current = mood.of(g.user)
    try:
        result = mood.choose(g.user["id"], picked, current)
        cleared = result == mood.DEFAULT and current != mood.DEFAULT
        flash(t("mood.cleared") if cleared else t("mood.saved"), "info")
    except ValueError:
        flash(t("mood.invalid"), "error")
    return redirect(_safe_next())


@bp.post("/lang")
def set_lang():
    """切换语言：保存到 Cookie（一年有效）；已登录的用户同时保存到数据库。
    然后回到原来的页面。"""
    lang = request.form.get("lang", "")
    # 只允许跳回本站路径，防止被利用跳转到外部网站
    next_url = request.form.get("next", "/")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"

    resp = redirect(next_url)
    if lang in SUPPORTED_LANGS:
        resp.set_cookie(
            LANG_COOKIE, lang, max_age=365 * 24 * 3600, httponly=True, samesite="Lax"
        )
        if g.user:
            db = get_db()
            db.execute("UPDATE members SET lang = ? WHERE id = ?", (lang, g.user["id"]))
            db.commit()
        else:
            # 还没登录（例如在登录页）：登录后用的是数据库里的语言，
            # 所以先记下来，登录成功时再存进数据库；否则刚切换的语言登录后又会变回去
            session[PICKED_LANG] = lang
    return resp
