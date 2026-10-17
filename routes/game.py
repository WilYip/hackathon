"""长凳五子棋（首页右下角的长凳）。完全不使用 AI。

- GET  /game              棋盘页（服务器直接画好棋盘：没有 JavaScript 也能用表单下棋）
- GET  /api/game/state    轮询：这一局的最新情况（static/js/game.js 每 2.5 秒问一次）
- POST /game/move         落子（表单字段 cell="行,列"，或 JSON {"row", "col"}）
- POST /game/new          开新的一局（开局的人执黑先下）
- POST /game/resign       认输
- POST /game/prop         道具互动：倒卡布奇诺 / 扔番茄 / 扔鸡蛋（JSON {"kind"}），对方轮询时看到并播放动画
POST 请求带 JSON（页面脚本）时返回 JSON；普通表单提交时跳回 /game，出错用一次性提示。
"""

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from services import animals, auth, gomoku, sound
from services.auth import api_login_required, login_required
from services.gomoku import GomokuError
from services.i18n import t

bp = Blueprint("game", __name__)


def _state():
    """这一局的情况 + 最近的道具（页面只播放 id 比上次看到的大的）。"""
    state = gomoku.view(gomoku.current_game(), g.user["id"])
    state["props"] = gomoku.recent_props(g.user["id"])
    return state


def _done(sound_name=None):
    """操作成功：页面脚本拿到最新情况；普通表单跳回棋盘页。"""
    if request.is_json:
        return jsonify({"ok": True, "state": _state()})
    if sound_name:
        sound.cue(sound_name)
    return redirect(url_for("game.index"))


def _failed(error):
    """不能这样下：页面脚本拿到错误代码和提示（以及最新情况，用来纠正画面）；普通表单显示提示。"""
    message = t(f"game.errors.{error.code}")
    if request.is_json:
        return jsonify({"ok": False, "code": error.code, "message": message, "state": _state()}), 409
    flash(message, "error")
    return redirect(url_for("game.index"))


@bp.get("/game")
@login_required
def index():
    partner = auth.get_partner(g.user["id"])
    people = animals.pair(auth.get_members(), g.user["id"])
    return render_template("game.html", state=_state(), partner=partner, people=people, size=gomoku.SIZE)


@bp.get("/api/game/state")
@api_login_required
def api_state():
    return jsonify(_state())


@bp.post("/game/move")
@login_required
def move():
    data = request.get_json(silent=True) or {}
    try:
        if request.is_json:
            row, col = int(data.get("row")), int(data.get("col"))
        else:
            row, col = (int(v) for v in (request.form.get("cell") or "").split(","))
    except (TypeError, ValueError):
        return _failed(GomokuError("out_of_range"))
    try:
        game = gomoku.play(g.user["id"], row, col)
    except GomokuError as error:
        return _failed(error)
    return _done("quest_complete" if game["status"] == gomoku.WON else None)


@bp.post("/game/new")
@login_required
def new():
    partner = auth.get_partner(g.user["id"])
    try:
        gomoku.start(g.user["id"], partner["id"] if partner else None)
    except GomokuError as error:
        return _failed(error)
    return _done("ui_success")


@bp.post("/game/resign")
@login_required
def resign():
    try:
        gomoku.resign(g.user["id"])
    except GomokuError as error:
        return _failed(error)
    return _done()


@bp.post("/game/prop")
@login_required
def prop():
    """道具互动（只有页面脚本会调用，返回 JSON）。"""
    if auth.get_partner(g.user["id"]) is None:
        return jsonify({"ok": False, "code": "no_partner", "message": t("game.errors.no_partner")}), 409
    kind = (request.get_json(silent=True) or {}).get("kind", "")
    try:
        prop_id = gomoku.throw_prop(g.user["id"], kind)
    except GomokuError as error:
        status = 429 if error.code == "too_fast" else 400
        return jsonify({"ok": False, "code": error.code, "message": t(f"game.errors.{error.code}")}), status
    return jsonify({"ok": True, "id": prop_id})
