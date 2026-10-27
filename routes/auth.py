"""账号与小岛：创建小岛、邀请码、加入、登录、退出、修改 PIN、忘记 PIN、创建新角色。

页面流程：
- 还没有小岛        → 欢迎页 → /create 创建小岛 → /invite 显示邀请码
- 有小岛、未登录    → /login 登录；第二个人点"用邀请码加入" → /join
                      登录页下方还有：/pin/change 修改 PIN、/pin/forgot 忘记 PIN（用另一半生成的重置码）、
                      /character/new 创建新角色（验证 PIN 后换昵称，动物和心情清空，回到默认形象）
- 已登录            → 首页（M3 起是小岛地图）
"""

import sqlite3

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for

from db import get_db
from services import animals, auth, demo, scene, sound
from services.i18n import PICKED_LANG, SUPPORTED_LANGS, get_lang, t

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


def _check_new_pin(pin, pin_confirm):
    """新 PIN 的格式和两次输入是否一致，返回错误提示（没有错误返回 None）。"""
    if not auth.is_valid_pin(pin):
        return t("errors.pin_format")
    if pin != pin_confirm:
        return t("errors.pin_mismatch")
    return None


def _secret_error(result, number, wrong_key="errors.pin_wrong"):
    """把 check_pin / check_reset_code 的结果换成提示文字。"""
    if result == "locked":
        return t("errors.locked", minutes=number)
    if result == "none":
        return t("errors.reset_none")
    return t(wrong_key, left=number)


def _log_in_keeping_lang(member):
    """登录，并把"登录前在页面右上角选的语言"存成这位成员的语言。
    （登录后用的是数据库里的语言；不这样做的话，登录页刚切换的语言登录后又会变回去。）"""
    picked = session.get(PICKED_LANG)
    auth.log_in(member["id"])
    if picked in SUPPORTED_LANGS and picked != member["lang"]:
        db = get_db()
        db.execute("UPDATE members SET lang = ? WHERE id = ?", (picked, member["id"]))
        db.commit()


def _members_page(template, **extra):
    """登录页和登录页下的三个小页面都要"先选你是谁"：准备小岛、成员和头像。"""
    members = auth.get_members()
    extra.setdefault("selected_id", None)
    extra.setdefault("error", None)
    return render_template(template, island=auth.get_island(), members=members,
                           people=animals.everyone(members), **extra)


def _picked_member():
    """表单里选中的成员：返回 (成员 id, 成员)，没选或不存在时成员是 None。"""
    member_id = request.form.get("member_id", type=int)
    return member_id, (auth.get_member(member_id) if member_id else None)


# ---------- 创建小岛 ----------


@bp.route("/create", methods=["GET", "POST"])
@demo.blocked()  # 演示小岛是大家共用的：不能改（见 services/demo.py）
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
@demo.blocked()  # 演示小岛是大家共用的：不能改（见 services/demo.py）
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

    selected_id = None
    error = None

    if request.method == "POST":
        selected_id, member = _picked_member()
        if member is None:
            error = t("errors.choose_member")
        else:
            result, number = auth.check_pin(member, request.form.get("pin", ""))
            if result == "ok":
                _log_in_keeping_lang(member)
                sound.cue("ui_success")
                return redirect(url_for("island.index"))
            error = _secret_error(result, number)
            sound.cue("ui_error")  # 登录失败：主要靠文字提示；提示音默认关闭（小信箱里可以打开）

    can_join = len(auth.get_members()) < auth.MAX_MEMBERS
    return _members_page("auth/login.html", selected_id=selected_id, error=error, can_join=can_join)


# ---------- 修改 PIN / 忘记 PIN / 创建新角色（入口都在登录页下方） ----------


def _not_for_now():
    """这几个页面只给"有小岛、还没登录"的人用；不是的话返回要跳转的地方，是的话返回 None。"""
    if g.user or auth.get_island() is None:
        return redirect(url_for("island.index"))
    return None


@bp.route("/pin/change", methods=["GET", "POST"])
@demo.blocked()  # 演示小岛是大家共用的：不能改（见 services/demo.py）
def change_pin():
    """记得现在的 PIN，想换一个新的。"""
    away = _not_for_now()
    if away:
        return away
    selected_id = None
    error = None

    if request.method == "POST":
        selected_id, member = _picked_member()
        pin = request.form.get("pin", "")
        if member is None:
            error = t("errors.choose_member")
        else:
            # 先检查新 PIN 的格式（不算错误次数），再核对现在的 PIN
            error = _check_new_pin(pin, request.form.get("pin_confirm", ""))
            if error is None:
                result, number = auth.check_pin(member, request.form.get("current_pin", ""))
                if result == "ok":
                    auth.set_pin(member["id"], pin)
                    flash(t("pin.changed"), "info")
                    sound.cue("ui_success")
                    return redirect(url_for("auth.login"))
                error = _secret_error(result, number)
        sound.cue("ui_error")

    return _members_page("auth/change_pin.html", selected_id=selected_id, error=error)


@bp.route("/pin/forgot", methods=["GET", "POST"])
@demo.blocked()  # 演示小岛是大家共用的：不能改（见 services/demo.py）
def forgot_pin():
    """忘记了 PIN：用另一半在小信箱里生成的重置码设置新 PIN。
    小岛上只有一个人时，没人能生成重置码，页面提示运行 scripts/reset_pin.py。"""
    away = _not_for_now()
    if away:
        return away
    selected_id = None
    error = None

    if request.method == "POST":
        selected_id, member = _picked_member()
        pin = request.form.get("pin", "")
        if member is None:
            error = t("errors.choose_member")
        else:
            error = _check_new_pin(pin, request.form.get("pin_confirm", ""))
            if error is None:
                result, number = auth.check_reset_code(member, request.form.get("reset_code", ""))
                if result == "ok":
                    auth.set_pin(member["id"], pin)  # 同时作废重置码
                    flash(t("pin.reset_done"), "info")
                    sound.cue("ui_success")
                    return redirect(url_for("auth.login"))
                error = _secret_error(result, number, "errors.reset_wrong")
        sound.cue("ui_error")

    solo = len(auth.get_members()) < auth.MAX_MEMBERS
    return _members_page("auth/forgot_pin.html", selected_id=selected_id, error=error, solo=solo)


@bp.route("/character/new", methods=["GET", "POST"])
@demo.blocked()  # 演示小岛是大家共用的：不能改（见 services/demo.py）
def new_character():
    """创建新角色：验证 PIN 后换一个昵称重新开始，森林小动物和心情清空（回到默认形象）。"""
    away = _not_for_now()
    if away:
        return away
    selected_id = None
    error = None
    nickname = ""

    if request.method == "POST":
        selected_id, member = _picked_member()
        nickname = _clean("nickname")
        if member is None:
            error = t("errors.choose_member")
        elif not nickname or len(nickname) > auth.NICKNAME_MAX:
            error = t("errors.nickname")
        elif any(m["nickname"] == nickname and m["id"] != member["id"] for m in auth.get_members()):
            error = t("errors.nickname_taken")  # 登录时按昵称选人，两人的昵称不能一样
        elif not request.form.get("confirm"):
            error = t("errors.confirm_rebuild")
        else:
            result, number = auth.check_pin(member, request.form.get("pin", ""))
            if result == "ok":
                auth.rebuild_character(member["id"], nickname)
                _log_in_keeping_lang(member)
                flash(t("character.done"), "info")
                sound.cue("ui_success")
                return redirect(url_for("island.index"))
            error = _secret_error(result, number)
        sound.cue("ui_error")

    return _members_page("auth/new_character.html", selected_id=selected_id, error=error, nickname=nickname)


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
