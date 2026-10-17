"""测试共用的工具（pytest 会自动加载这个文件）。"""

import pytest

from app import create_app
from services import ai

# 本站地址：测试客户端默认的主机名是 localhost
ORIGIN = "http://localhost"


class FakeDeepSeek:
    """测试用的假 DeepSeek：记录每次请求，按设置返回文字或抛出异常。
    用法：fake_ai.reply = "改写后的话"；fake_ai.error = FakeAPIError(401)
    reply 也可以是列表：按顺序每次返回一个（用来测"第一次不合格、重试一次"）"""

    def __init__(self):
        self.calls = []
        self.reply = "（模拟的温柔版本）"
        self.error = None

    def __call__(self, api_key, messages, max_tokens, temperature, json_mode=False):
        self.calls.append({"api_key": api_key, "messages": messages, "max_tokens": max_tokens,
                           "temperature": temperature, "json_mode": json_mode})
        if self.error is not None:
            raise self.error
        if isinstance(self.reply, list):
            return self.reply.pop(0)
        return self.reply


class FakeAPIError(Exception):
    """模拟 openai 的 HTTP 错误（只需要 status_code）。"""

    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch):
    """所有测试自动生效：
    - 把真正调用 DeepSeek 的 ai._chat 换成假的，任何测试都不会联网、不会花钱
    - 删掉环境变量里的 DEEPSEEK_API_KEY，确保应用不会用到开发者 .env 里的 key"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    fake = FakeDeepSeek()
    monkeypatch.setattr(ai, "_chat", fake)
    return fake


@pytest.fixture
def app(tmp_path, monkeypatch):
    # 每个测试使用独立的临时数据目录，不影响真实的 data/
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    # 动物图片目录用临时目录：默认是空的（结果立绘、石像都"还没交付"），测试里用 put_animal 放图片。
    # 其他第三版素材（底图、柔光层、图标）直接用真实的 static/usland/assets/
    animal_dir = tmp_path / "animals"
    animal_dir.mkdir()
    return create_app({"TESTING": True, "ANIMAL_DIR": animal_dir})


def put_animal(app, kind, code, size=(64, 64)):
    """在测试用的动物目录里放一张图片：kind 是 result / island / statues / reconcile。"""
    from PIL import Image

    path = app.config["ANIMAL_DIR"] / kind / f"{code}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (255, 200, 220, 255)).save(path)
    return path


@pytest.fixture
def raw_client(app):
    """不带 Origin 头的客户端，用来测试来源校验。"""
    return app.test_client()


def make_client(app):
    """带 Origin 头的客户端，模拟从本站页面发出的请求。"""
    client = app.test_client()
    client.environ_base["HTTP_ORIGIN"] = ORIGIN
    return client


@pytest.fixture
def client(app):
    return make_client(app)


@pytest.fixture
def partner(app):
    """第二个浏览器（另一半），有自己独立的 Cookie。"""
    return make_client(app)
