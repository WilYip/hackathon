"""账号与小岛：创建小岛、邀请码、加入、登录、退出。

页面流程：
- 还没有小岛        → 欢迎页 → /create 创建小岛 → /invite 显示邀请码
- 有小岛、未登录    → /login 登录；第二个人点"用邀请码加入" → /join
- 已登录            → 首页（M3 起是小岛地图）
"""

import sqlite3

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from db import get_db
from services import animals, auth, scene, sound
from services.i18n import SUPPORTED_LANGS, get_lang, t

bp = Blueprint("auth", __name__)


def _clean(field):
    """读取表单字段并去掉首尾空格。"""
    return (request.form.get(field) or "").strip()


def _check_profile(nickname, pin, pin_confirm):
    """检查昵称和 PIN，返回错误提示（没有错误返回 None）。"""
    if not nickname or len(nickname) > auth.NICKNAME_MAX:
        return t("errors.nickname")
    if not auth.is_valid_pin(pin):
        return t("errors.pin_format")
    if pin != pin_confirm:
        return t("errors.pin_mismatch")
    return None


# ---------- 创建小岛 ----------


@bp.route("/create", methods=["GET", "POST"])
def create():
    if g.user:
        return redirect(url_for("island.index"))
    if auth.get_island():
        # 小岛已经存在，一个实例只能有一座小岛
        return redirect(url_for("auth.login"))

    form = {"island_name": "", "nickname": "", "lang": get_lang()}
    error = None

    if request.method == "POST":
        form = {
            "island_name": _clean("island_name"),
            "nickname": _clean("nickname"),
            "lang": request.form.get("lang", "zh"),
        }
        pin = request.form.get("pin", "")
        pin_confirm = request.form.get("pin_confirm", "")
        if form["lang"] not in SUPPORTED_LANGS:
            form["lang"] = "zh"

        if not form["island_name"] or len(form["island_name"]) > auth.ISLAND_NAME_MAX:
            error = t("errors.island_name")
        else:
            error = _check_profile(form["nickname"], pin, pin_confirm)

        if error is None:
            db = get_db()
            try:
                # 小岛 id 固定为 1：如果两个人同时点创建，第二个会触发主键冲突
                db.execute(
                    "INSERT INTO island (id, name, invite_code) VALUES (1, ?, ?)",
                    (form["island_name"], auth.generate_invite_code()),
                )
                cur = db.execute(
                    "INSERT INTO members (nickname, pin_hash, lang) VALUES (?, ?, ?)",
                    (form["nickname"], auth.hash_pin(pin), form["lang"]),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                return redirect(url_for("auth.login"))

            auth.log_in(cur.lastrowid)
            sound.cue("ui_success")
            return redirect(url_for("auth.invite"))

    return render_template("auth/create.html", form=form, error=error)


@bp.get("/invite")
@auth.login_required
def invite():
    """创建成功后：显示邀请码，等 TA 加入。两人到齐后直接回首页。"""
    if len(auth.get_members()) >= auth.MAX_MEMBERS:
        return redirect(url_for("island.index"))
    return render_template("auth/invite.html", preview=scene.preview_image())


# ---------- 加入小岛 ----------


@bp.route("/join", methods=["GET", "POST"])
def join():
    if g.user:
        return redirect(url_for("island.index"))
    island = auth.get_island()
    if island is None:
        return redirect(url_for("island.index"))
    if len(auth.get_members()) >= auth.MAX_MEMBERS:
        return render_template("auth/join.html", full=True, form={}, error=None)

    form = {"invite_code": "", "nickname": ""}
    error = None

    if request.method == "POST":
        form = {
            "invite_code": auth.normalize_invite_code(request.form.get("invite_code")),
            "nickname": _clean("nickname"),
        }
        pin = request.form.get("pin", "")
        pin_confirm = request.form.get("pin_confirm", "")

        if form["invite_code"] != island["invite_code"]:
            error = t("errors.invite_wrong")
        else:
            error = _check_profile(form["nickname"], pin, pin_confirm)

        if error is None:
            db = get_db()
            # BEGIN IMMEDIATE：加写锁后再数人数，防止两个人同时加入导致超过两人
            db.execute("BEGIN IMMEDIATE")
            members = db.execute("SELECT nickname FROM members").fetchall()
            if len(members) >= auth.MAX_MEMBERS:
                db.rollback()
                return render_template("auth/join.html", full=True, form={}, error=None)
            if any(m["nickname"] == form["nickname"] for m in members):
                # 登录时要按昵称选人，所以两人的昵称不能一样
                db.rollback()
                error = t("errors.nickname_taken")
            else:
                cur = db.execute(
                    "INSERT INTO members (nickname, pin_hash, lang) VALUES (?, ?, ?)",
                    (form["nickname"], auth.hash_pin(pin), get_lang()),
                )
                db.commit()
                auth.log_in(cur.lastrowid)
                sound.cue("ui_success")
                return redirect(url_for("island.index"))

    return render_template("auth/join.html", full=False, form=form, error=error)


# ---------- 登录 / 退出 ----------


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("island.index"))
    island = auth.get_island()
    if island is None:
        return redirect(url_for("island.index"))

    members = auth.get_members()
    selected_id = None
    error = None

    if request.method == "POST":
        selected_id = request.form.get("member_id", type=int)
        member = auth.get_member(selected_id) if selected_id else None
        if member is None:
            error = t("errors.choose_member")
        else:
            result, number = auth.check_pin(member, request.form.get("pin", ""))
            if result == "ok":
                auth.log_in(member["id"])
                sound.cue("ui_success")
                return redirect(url_for("island.index"))
            if result == "locked":
                error = t("errors.locked", minutes=number)
            else:
                error = t("errors.pin_wrong", left=number)
            sound.cue("ui_error")  # 登录失败：主要靠文字提示；提示音默认关闭（小信箱里可以打开）

    can_join = len(members) < auth.MAX_MEMBERS
    return render_template(
        "auth/login.html", island=island, members=members, people=animals.everyone(members),
        selected_id=selected_id, error=error, can_join=can_join,
    )


@bp.post("/logout")
def logout():
    auth.log_out()
    return redirect(url_for("island.index"))


# ---------- 等待另一半 ----------


@bp.get("/api/island/status")
@auth.login_required
def island_status():
    """等待页每 4 秒查询一次：另一半加入了没有。"""
    return jsonify({"member_count": len(auth.get_members())})
