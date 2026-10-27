"""Usland 应用入口。

本地运行：python app.py   然后打开 http://localhost:8080
部署运行：gunicorn "app:create_app()"
"""

import logging
from urllib.parse import urlparse

from flask import Flask, abort, flash, g, redirect, request
from werkzeug.middleware.proxy_fix import ProxyFix

import db
from config import Config
from routes import auth as auth_routes
from routes import demo as demo_routes
from routes import forest, game, island, memories, quest, settings, whisper
from routes.settings import MOTION_COOKIE
from services import animals, assets, auth, content, demo, i18n, scene, sound


def _same_origin(url):
    """判断 Origin / Referer 中的地址是否与当前网站同源。"""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.netloc == request.host


def create_app(test_config=None):
    """应用工厂：创建并配置 Flask 应用。
    test_config 是给测试用的，可以覆盖部分配置。"""
    app = Flask(__name__)
    app.config.from_object(Config())
    if test_config:
        app.config.update(test_config)

    # 在 Zenith 这类反向代理后面：信任前面一层代理传来的客户端地址、协议和主机名
    if app.config.get("TRUST_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # 日志：记录 INFO 级别（例如 DeepSeek 调用的结果类型和耗时；从不记录聊天内容）
    app.logger.setLevel(logging.INFO)

    # 数据库和中英文
    db.init_app(app)
    i18n.init_app(app)

    # 注册各功能的路由（后续里程碑在这里追加）
    app.register_blueprint(island.bp)
    app.register_blueprint(auth_routes.bp)
    for feature in (whisper, quest, forest, memories, settings, game, demo_routes):
        app.register_blueprint(feature.bp)

    @app.before_request
    def check_origin():
        """所有修改数据的请求必须是 POST，并且来自本站页面（简单的 CSRF 防护）。"""
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        source = request.headers.get("Origin") or request.headers.get("Referer")
        if not source or not _same_origin(source):
            abort(403)

    @app.before_request
    def demo_reset():
        """演示模式：演示小岛不存在或已经超过 6 小时，就先恢复成初始状态（见 services/demo.py）。"""
        if app.config.get("DEMO_MODE") and request.endpoint != "static":
            demo.maybe_reset()

    @app.before_request
    def load_user():
        """读取当前登录的成员（g.user）和小岛（g.island）。"""
        auth.load_current_user()

    @app.errorhandler(413)
    def too_large(error):
        """上传的内容超过 MAX_CONTENT_LENGTH（照片太大）：提示后回到原来的页面。"""
        flash(i18n.t("photo.errors.too_large"), "error")
        back = request.referrer or ""
        return redirect(back if back and _same_origin(back) else "/")

    # 声音（static/js/sound.js）：清单和"刚完成的操作"音效，在 base.html 里输出
    app.jinja_env.globals["sound_manifest"] = sound.manifest
    app.jinja_env.globals["sound_cues"] = sound.take_cues
    # 第三版美术素材：功能页背景、SVG 图标（见 services/scene.py、services/assets.py）
    app.jinja_env.globals["page_background"] = scene.page_background
    app.jinja_env.globals["ui_icon"] = assets.icon_svg
    app.jinja_env.globals["asset_url"] = assets.url

    @app.context_processor
    def inject_user():
        """模板中可以直接使用 current_user、island、members、member_avatars（顶部栏的两人头像），
        以及顶部导航用的 regions。"""
        user = g.get("user")
        members = auth.get_members() if user else []
        return {
            "current_user": user,
            "island": g.get("island"),
            "members": members,
            "member_avatars": animals.everyone(members, user["id"]) if user else [],
            # 导航只放五个主要功能；长凳五子棋只在地图上（"nav": false）
            "regions": [r for r in content.regions() if r.get("nav", True)],
            # 小信箱里打开了"减少动态效果"（只存在这台设备的 Cookie 里）
            "reduce_motion": request.cookies.get(MOTION_COOKIE) == "reduce",
            # 演示模式的信息（横幅、登录页一键进入、各页面的限制提示）
            "demo": demo.view(),
        }

    return app


if __name__ == "__main__":
    app = create_app()
    # 修改模板后刷新页面即可看到变化。
    # 注意：create_app() 里已经用到了模板引擎（注册全局函数），引擎那时就建好了，
    # 只改配置不会生效，所以要直接打开引擎的 auto_reload
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    # 监听 0.0.0.0，同一 Wi-Fi 下的手机也能访问。
    # 注意：不开启 debug 调试器，因为局域网里的人也能访问到它（有安全风险）；
    # use_reloader=True 让修改 .py 文件后自动重启。
    app.run(host="0.0.0.0", port=app.config["PORT"], debug=False, use_reloader=True)
