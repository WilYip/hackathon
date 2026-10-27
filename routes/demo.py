"""演示模式的两个入口（只在 DEMO_MODE=1 时可用，否则 404）。说明见 services/demo.py。

- POST /demo/enter   在登录页点"以 Wilson / Yvette 进入"：不用输 PIN
- POST /demo/reset   在小信箱里点"恢复演示小岛"：马上把小岛恢复成初始状态
"""

from flask import Blueprint, abort, flash, redirect, request, session, url_for

from db import get_db
from services import auth, demo, sound
from services.i18n import get_lang, t

bp = Blueprint("demo", __name__)


@bp.before_request
def only_in_demo():
    if not demo.enabled():
        abort(404)


@bp.post("/demo/enter")
def enter():
    member = auth.get_member(request.form.get("member_id", type=int) or 0)
    if member is None:
        flash(t("errors.choose_member"), "error")
        return redirect(url_for("auth.login"))
    lang = get_lang()  # 进去以后沿用访客现在看到的语言
    auth.log_in(member["id"])
    db = get_db()
    db.execute("UPDATE members SET lang = ? WHERE id = ?", (lang, member["id"]))
    db.commit()
    sound.cue("ui_success")
    return redirect(url_for("island.index"))


@bp.post("/demo/reset")
def reset():
    demo.reset()
    session.clear()  # 恢复后大家都回到登录页重新选人
    flash(t("demo.reset_done"), "info")
    return redirect(url_for("auth.login"))
