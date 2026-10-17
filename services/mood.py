"""情绪状态（VISUAL_DESIGN.md 第 13.4 节）。

- 每位成员可以在首页点自己的动物，选择当前心情：开心 / 委屈 / 需要空间 / 平静（默认）
- 心情只由用户主动选择，**不做任何推测**（不看回复速度、不看有没有登录、不看聊天内容）
- 选择 24 小时后自动恢复为"平静"
- 对方的首页和温柔传话页能看到，并显示对应动作：开心挥爪、委屈垂耳、需要空间时缩小并显示小窝
- 宠物不会因为争吵、不登录或没及时回复而生病、掉血或受惩罚
"""

from datetime import datetime, timedelta, timezone

from db import get_db
from services.i18n import t

MOODS = ("happy", "wronged", "need_space", "calm")
DEFAULT = "calm"
EXPIRE_AFTER = timedelta(hours=24)

# 每种心情用的图标（templates/_icons.html）
ICONS = {"happy": "sun", "wronged": "drop", "need_space": "cottage", "calm": "leaf"}


def _now():
    return datetime.now(timezone.utc)


def effective(mood, set_at, now=None):
    """纯函数：现在应该显示哪种心情。没选过、值不对、超过 24 小时 → 平静。"""
    if mood not in MOODS or not set_at:
        return DEFAULT
    try:
        chosen = datetime.fromisoformat(set_at)
    except ValueError:
        return DEFAULT
    if chosen.tzinfo is None:
        chosen = chosen.replace(tzinfo=timezone.utc)
    if (now or _now()) - chosen >= EXPIRE_AFTER:
        return DEFAULT
    return mood


def of(member):
    """一位成员现在的心情。"""
    if member is None:
        return DEFAULT
    keys = member.keys()
    if "mood" not in keys:
        return DEFAULT
    return effective(member["mood"], member["mood_set_at"])


def set_mood(member_id, mood):
    """保存自己的心情；不合法时抛出 ValueError。"""
    if mood not in MOODS:
        raise ValueError("unknown mood")
    db = get_db()
    db.execute(
        "UPDATE members SET mood = ?, mood_set_at = ? WHERE id = ?",
        (mood, _now().isoformat(), member_id),
    )
    db.commit()


def choose(member_id, picked, current):
    """在心情选择窗口里点了一个按钮，返回最后的心情：
    - picked 是 "clear"（清除心情）→ 回到平静
    - 再点一次当前已经选中的心情 → 视为取消，回到平静
    - 否则保存新的心情
    不合法时抛出 ValueError。"""
    if picked == "clear" or picked == current:
        picked = DEFAULT
    set_mood(member_id, picked)
    return picked


def view(key, nickname=None):
    """页面显示用：图标、名字，以及给对方看的一句温柔提示。"""
    return {
        "key": key,
        "icon": ICONS[key],
        "label": t("mood." + key),
        "hint": t("mood.partner_hint." + key, name=nickname) if nickname else None,
    }


def options():
    """心情选择窗口里的四个选项（平静放在最后）。"""
    return [view(key) for key in MOODS]
