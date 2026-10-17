"""services/ai.py：错误分类、key 测试、软化调用参数、日志不含聊天内容、.env 中的 key 不会被读取。
所有 DeepSeek 调用都被 conftest.py 的 fake_ai 替换，不会联网。"""

import logging
import os

import openai

import config
from services import ai
from services.prompts import SOFTEN_SYSTEM_PROMPT
from tests.conftest import FakeAPIError


def test_classify_errors():
    assert ai.classify_error(FakeAPIError(401)) == ai.INVALID_KEY
    assert ai.classify_error(FakeAPIError(402)) == ai.NO_BALANCE
    assert ai.classify_error(FakeAPIError(429)) == ai.RATE_LIMITED
    assert ai.classify_error(FakeAPIError(500)) == ai.ERROR
    assert ai.classify_error(TimeoutError()) == ai.NETWORK
    assert ai.classify_error(ConnectionError()) == ai.NETWORK
    assert ai.classify_error(ValueError("x")) == ai.ERROR


def test_openai_connection_errors_are_network():
    # openai 的超时异常是 APIConnectionError 的子类
    assert issubclass(openai.APITimeoutError, openai.APIConnectionError)


def test_check_key(app, fake_ai):
    with app.app_context():
        assert ai.check_key("sk-test-1234567890") == ai.OK
        call = fake_ai.calls[-1]
        assert call["api_key"] == "sk-test-1234567890"
        assert call["max_tokens"] == 5  # 极小的测试请求

        fake_ai.error = FakeAPIError(401)
        assert ai.check_key("sk-wrong-1234567890") == ai.INVALID_KEY
        fake_ai.error = FakeAPIError(402)
        assert ai.check_key("sk-poor-1234567890") == ai.NO_BALANCE
        fake_ai.error = TimeoutError()
        assert ai.check_key("sk-slow-1234567890") == ai.NETWORK


def test_soften_call_parameters(app, fake_ai):
    fake_ai.reply = "我有点不安，希望你能多回我一下。"
    with app.app_context():
        result = ai.soften("sk-test-1234567890", "你又不回我消息！")
    assert result.status == ai.OK
    assert result.text == "我有点不安，希望你能多回我一下。"
    call = fake_ai.calls[-1]
    assert call["max_tokens"] == 300
    assert call["temperature"] == 0.7
    assert call["messages"][0] == {"role": "system", "content": SOFTEN_SYSTEM_PROMPT}
    assert call["messages"][1] == {"role": "user", "content": "你又不回我消息！"}


def test_soften_unsafe_and_errors(app, fake_ai):
    with app.app_context():
        fake_ai.reply = "[UNSAFE]"
        assert ai.soften("sk-test-1234567890", "...").status == ai.UNSAFE
        fake_ai.error = FakeAPIError(402)
        assert ai.soften("sk-test-1234567890", "...").status == ai.NO_BALANCE


def test_logs_never_contain_message_or_key(app, fake_ai, caplog):
    secret_text = "这是一句绝对不能出现在日志里的话"
    fake_ai.reply = "这是改写后也不能出现在日志里的话"
    with caplog.at_level(logging.INFO), app.app_context():
        ai.soften("sk-secret-key-abcd", secret_text)
        ai.check_key("sk-secret-key-abcd")
    logged = caplog.text
    assert "result=ok" in logged  # 只记录结果类型和耗时
    assert secret_text not in logged
    assert fake_ai.reply not in logged
    assert "sk-secret-key-abcd" not in logged


def test_env_file_key_is_not_loaded(tmp_path, monkeypatch):
    # .env 里的 DEEPSEEK_API_KEY 只给开发者的 test_ai.py 用，应用不会把它读进环境变量
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # 先 setenv 再 delenv：测试结束后 monkeypatch 会把 DEEPSEEK_MODEL 恢复成"不存在"
    monkeypatch.setenv("DEEPSEEK_MODEL", "placeholder")
    monkeypatch.delenv("DEEPSEEK_MODEL")
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=sk-from-env-file\nDEEPSEEK_MODEL=test-model\n", encoding="utf-8")
    config.load_env_file(env_file)
    assert "DEEPSEEK_API_KEY" not in os.environ
    assert os.environ["DEEPSEEK_MODEL"] == "test-model"  # 普通配置照常读取
