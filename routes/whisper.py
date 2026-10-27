"""温柔传话（传话码头）。

页面：
- GET  /whisper                  聊天页；本岛还没有 API key 时，页面一打开就弹出"点亮传话魔法"
接口（都需要登录，返回 JSON）：
- POST /api/whisper/key          测试并保存 API key（只返回末尾 4 位）
- GET  /api/whisper/messages     拉取消息（?after=<id> 只取新消息），同时标记已读
- POST /api/whisper/soften       软化原话，只返回预览，不保存
- POST /api/whisper/send         发送（软化版 / 改过的版本 / 直接发送）
- POST /api/whisper/reconcile    按下"和好"

隐私：API key 永远不返回给前端；原话只返回给发送者本人；日志不记录聊天内容。
"""

from flask import Blueprint, current_app, g, jsonify, render_template, request

from services import ai, animals, auth, demo, whisper
from services.auth import api_login_required, login_required
from services.i18n import t

bp = Blueprint("whisper", __name__)

MAX_FINAL_LENGTH = 1000  # 软化后的版本最长约为原话的两倍

# 前端脚本要用的文字（按当前语言传给 static/js/whisper.js）
_JS_STRINGS = [
    "empty", "load_failed", "softening", "show_original", "hide_original", "original_label",
    "empty_input", "too_long", "send_failed", "reconcile", "reconcile_waiting", "reconcile_partner",
    "key.testing", "key.success", "key.format", "key.show", "key.hide",
]
_ERROR_CODES = ["invalid_key", "no_balance", "network", "rate_limited", "error", "limit", "key_invalid_now"]


def _js_strings():
    strings = {name: t("whisper." + name) for name in _JS_STRINGS}
    strings.update({"errors." + code: t("whisper.errors." + code) for code in _ERROR_CODES})
    return strings


def _partner():
    """另一半；还没加入时返回 None。"""
    return auth.get_partner(g.user["id"])


def _json_body():
    return request.get_json(silent=True) or {}


# ---------- 页面 ----------


@bp.get("/whisper")
@login_required
def index():
    members = auth.get_members()
    if len(members) < 2:
        # 只有一个人：显示"等 TA 加入"
        return render_template("whisper.html", alone=True)

    # 两人的头像：初见森林测出的动物（见 services/animals.py）
    people = animals.pair(members, g.user["id"])

    key = whisper.get_api_key()
    return render_template(
        "whisper.html",
        alone=False,
        me=people["me"],
        partner=people["partner"],
        # 演示版不需要 key：温柔转达用示范改写（services/demo.soften）
        needs_key=key is None and not demo.enabled(),
        masked_key=whisper.mask_key(key),  # 只有末尾 4 位
        reconcile=whisper.reconcile_state(g.user["id"]),
        hug_id=whisper.latest_hug_id(),
        js_strings=_js_strings(),
    )


# ---------- API key ----------


@bp.post("/api/whisper/key")
@demo.blocked(api=True)  # 演示版不接受 API key（大家共用，会被刷光额度）
@api_login_required
def save_key():
    """用户在弹窗里填写的 key：先发一个极小的请求测试，成功才保存。"""
    key = (_json_body().get("api_key") or "").strip()
    if not whisper.looks_like_key(key):
        return jsonify({"ok": False, "error": "format", "message": t("whisper.key.format")}), 400

    result = ai.check_key(key)
    if result != ai.OK:
        return jsonify({"ok": False, "error": result, "message": t("whisper.errors." + result)})

    whisper.save_api_key(key)
    return jsonify({"ok": True, "masked": whisper.mask_key(key), "message": t("whisper.key.success")})


# ---------- 消息 ----------


@bp.get("/api/whisper/messages")
@api_login_required
def messages():
    me = g.user["id"]
    after = request.args.get("after", default=0, type=int)
    rows = whisper.list_messages(after)
    if rows:
        # 页面只在可见时轮询，拉到的消息就算已读
        whisper.mark_read(me, rows[-1]["id"])
    # 两人现在的心情（只是用户自己选的状态，不含任何推测），页面据此更新头像动作和提示
    people = animals.pair(auth.get_members(), me)
    moods = {who: {k: p["mood"][k] for k in ("key", "label", "hint")}
             for who, p in people.items() if p is not None}
    return jsonify({
        "messages": [whisper.message_to_json(r, me) for r in rows],
        "reconcile": whisper.reconcile_state(me),
        "hug_id": whisper.latest_hug_id(),
        "moods": moods,
    })


@bp.post("/api/whisper/soften")
@api_login_required
def soften():
    """把原话交给 DeepSeek 软化，只返回预览，不保存任何内容。"""
    if _partner() is None:
        return jsonify({"error": "partner_missing"}), 409
    text = (_json_body().get("text") or "").strip()
    if not text:
        return jsonify({"error": "empty", "message": t("whisper.empty_input")}), 400
    if len(text) > ai.MAX_ORIGINAL_LENGTH:
        return jsonify({"error": "too_long", "message": t("whisper.too_long")}), 400

    if demo.enabled():
        # 演示版：预先写好的示范改写，不调用 AI、不计入每日次数
        return jsonify({"status": "ok", "softened": demo.soften(text), "demo": True})

    key = whisper.get_api_key()
    if key is None:
        return jsonify({"status": "need_key"}), 409

    if not whisper.try_use_soften(current_app.config["SOFTEN_DAILY_LIMIT"]):
        return jsonify({"status": "limit", "message": t("whisper.errors.limit")})

    result = ai.soften(key, text)
    if result.status == ai.OK:
        return jsonify({"status": "ok", "softened": result.text})
    if result.status == ai.UNSAFE:
        # 不发送、不显示改写，前端显示安全卡片
        return jsonify({"status": "unsafe"})
    code = "key_invalid_now" if result.status == ai.INVALID_KEY else result.status
    return jsonify({"status": "error", "code": code, "message": t("whisper.errors." + code)})


@bp.post("/api/whisper/send")
@api_login_required
def send():
    """发送消息。
    - 直接发送：text 是原话，没有 original
    - 温柔转达：text 是软化版（或"我再改改"之后的版本），original 是原话（只有自己看得到）"""
    if _partner() is None:
        return jsonify({"error": "partner_missing"}), 409
    data = _json_body()
    text = (data.get("text") or "").strip()
    original = (data.get("original") or "").strip() or None
    if not text:
        return jsonify({"error": "empty", "message": t("whisper.empty_input")}), 400
    if len(text) > MAX_FINAL_LENGTH or (original and len(original) > ai.MAX_ORIGINAL_LENGTH):
        return jsonify({"error": "too_long", "message": t("whisper.too_long")}), 400
    if original is None and len(text) > ai.MAX_ORIGINAL_LENGTH:
        return jsonify({"error": "too_long", "message": t("whisper.too_long")}), 400

    me = g.user["id"]
    row = whisper.add_message(me, text, original)
    whisper.mark_read(me, row["id"])  # 自己发的不算未读
    return jsonify({"message": whisper.message_to_json(row, me)})


# ---------- 和好 ----------


@bp.post("/api/whisper/reconcile")
@api_login_required
def reconcile():
    if _partner() is None:
        return jsonify({"error": "partner_missing"}), 409
    me = g.user["id"]
    hug_id = whisper.press_reconcile(me)
    return jsonify({
        "reconcile": whisper.reconcile_state(me),
        "hug_id": hug_id or whisper.latest_hug_id(),
        "hugged": hug_id is not None,
    })
