"""统一读取环境变量配置。

所有配置都来自环境变量（本地开发时可以写在 .env 里）。
其他代码只从这里拿配置，不要到处直接 os.environ。
"""

import os
import secrets
from datetime import timedelta
from pathlib import Path

from dotenv import dotenv_values

# 项目根目录（config.py 所在目录）
BASE_DIR = Path(__file__).resolve().parent

# 应用只从 .env 读取这几项配置。
# 特别注意：.env 里的 DEEPSEEK_API_KEY 只给开发者运行 test_ai.py 用，
# 应用本身不读取它——温柔传话用的 key 只能由用户在网页上填写、保存在数据库里。
ENV_KEYS = ("SECRET_KEY", "DATA_DIR", "PORT", "DEEPSEEK_MODEL", "DEMO_MODE")


def load_env_file(path):
    """读取 .env（如果存在），只把 ENV_KEYS 里的配置放进环境变量；
    不会覆盖已经设置好的系统环境变量。"""
    if not Path(path).exists():
        return
    for name, value in dotenv_values(path).items():
        if name in ENV_KEYS and value is not None:
            os.environ.setdefault(name, value)


load_env_file(BASE_DIR / ".env")


def _env_bool(name, default="0"):
    """把 "1" / "true" / "yes" 这类字符串转成 True。"""
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _load_secret_key(data_dir):
    """优先使用环境变量 SECRET_KEY；没有的话自动生成一个并保存到数据目录，
    这样重启后登录状态不会丢失。"""
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key
    key_file = data_dir / "secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    return key


class Config:
    """Flask 配置。create_app() 会在启动时读取这里的值。"""

    def __init__(self):
        # 数据目录：相对路径一律相对于项目根目录
        data_dir = Path(os.environ.get("DATA_DIR", "data"))
        if not data_dir.is_absolute():
            data_dir = BASE_DIR / data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        self.DATA_DIR = data_dir
        self.DATABASE_PATH = data_dir / "usland.db"
        self.UPLOAD_DIR = data_dir / "uploads"
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        self.SECRET_KEY = _load_secret_key(data_dir)
        self.PORT = int(os.environ.get("PORT", "8080"))
        self.DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
        self.DEMO_MODE = _env_bool("DEMO_MODE")
        # 部署在反向代理（Zenith 的 HTTPS 入口）后面时设为 1：按代理传来的 X-Forwarded-Host / -Proto
        # 判断网址，否则"来源校验"可能把每个表单提交都当成跨站而拒绝。只在真的有代理时打开（Dockerfile 里默认打开）
        self.TRUST_PROXY = _env_bool("TRUST_PROXY")

        # 温柔传话：每座小岛每天最多软化 100 次；调用 DeepSeek 超时 20 秒
        self.SOFTEN_DAILY_LIMIT = 100
        self.AI_TIMEOUT = 20

        # 登录 Cookie 的安全设置
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"
        # 登录状态保持 30 天（关掉浏览器也不会退出）
        self.PERMANENT_SESSION_LIFETIME = timedelta(days=30)

        # 第三版美术素材目录（说明见 docs/ui-v3/），services/assets.py 负责路径和"文件是否存在"
        self.USLAND_ASSET_DIR = BASE_DIR / "static" / "usland" / "assets"
        # 动物图片目录（结果立绘、海岛姿态、石像、和好姿态），测试时可以改成临时目录
        self.ANIMAL_DIR = self.USLAND_ASSET_DIR / "animals"

        # 上传大小上限：照片 ≤ 5MB，留一点余量给表单其他字段
        self.MAX_CONTENT_LENGTH = 6 * 1024 * 1024
