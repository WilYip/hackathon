"""全站声音：服务器这边只做两件小事，真正的播放都在浏览器里（static/js/sound.js）。

1. manifest()：把 content/audio_manifest.json 整理成浏览器要用的精简清单
   （网址、类别、建议音量、是否循环、时长）。只是文字信息，声音文件要等用户开启声音后才会加载。
2. cue() / take_cues()：自己刚完成的操作（保存成功、登录成功、添加回忆……）在跳转后的页面上播放一次。
   做法和 flash 提示一样：存在 session 里，页面显示一次就删掉，所以刷新页面不会再响。
声音素材的来源和授权见 docs/credits.md 和 static/audio/credits.html。
"""

from flask import request, session, url_for

from services import content

SESSION_KEY = "sound_cues"


def manifest():
    """{"bgm_island": {"src": "/static/audio/bgm/bgm_island.mp3", "cat": "bgm", "vol": 0.32,
                       "loop": true, "dur": 329.68, "xfade": 2}, ...}"""
    result = {}
    for asset in content.load("audio_manifest")["assets"]:
        path = asset["path"]
        if not path.startswith("static/"):
            continue
        result[asset["id"]] = {
            "src": url_for("static", filename=path[len("static/"):]),
            "cat": asset["category"],
            "vol": asset.get("recommended_volume", 0.5),
            "loop": bool(asset.get("loop")),
            "dur": asset.get("duration_seconds"),
            "xfade": asset.get("loop_crossfade_seconds"),
        }
    return result


def cue(sound, endpoint=None):
    """在下一个显示的页面上播放一次音效。endpoint 不为空时，只在那个页面播放（例如只在森林页）。"""
    cues = session.get(SESSION_KEY, [])
    cues.append({"sound": sound, "endpoint": endpoint})
    session[SESSION_KEY] = cues[-5:]  # 最多留 5 个，防止越积越多


def take_cues():
    """当前页面要播放的音效（取出后就删掉）。在 base.html 里调用。"""
    cues = session.get(SESSION_KEY)
    if not cues:
        return []
    now = [c["sound"] for c in cues if c["endpoint"] in (None, request.endpoint)]
    rest = [c for c in cues if c["endpoint"] not in (None, request.endpoint)]
    if rest:
        session[SESSION_KEY] = rest
    else:
        session.pop(SESSION_KEY, None)
    return now
