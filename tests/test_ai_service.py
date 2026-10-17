"""services/ai.py：错误分类、key 测试、软化调用参数、人称 / 语言检查与重试、日志不含聊天内容、
.env 中的 key 不会被读取。
所有 DeepSeek 调用都被 conftest.py 的 fake_ai 替换，不会联网。"""

import json
import logging
import os

import openai

import config
from services import ai
from services.prompts import SOFTEN_EXAMPLES, SOFTEN_RETRY_REMINDER, SOFTEN_SYSTEM_PROMPT
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
    assert len(fake_ai.calls) == 1  # 结果没问题：不重试
    call = fake_ai.calls[-1]
    assert call["max_tokens"] == 400
    assert call["temperature"] == 0.3
    assert call["json_mode"] is True  # 要求模型只输出 JSON（先写说话人的情绪，再写改写）
    messages = call["messages"]
    assert messages[0] == {"role": "system", "content": SOFTEN_SYSTEM_PROMPT}
    # 系统提示词之后是示例对话（用户 / 助手交替），最后才是这次的原话
    assert len(messages) == 1 + 2 * len(SOFTEN_EXAMPLES) + 1
    assert [m["role"] for m in messages[1:-1]] == ["user", "assistant"] * len(SOFTEN_EXAMPLES)
    # 示例里助手的回答也是 JSON：先写说话的人的情绪，再写改写
    first_answer = json.loads(messages[2]["content"])
    assert set(first_answer) == {"speaker_feeling", "rewrite"}
    # 原话用标签包起来（不然模型会以为是对它说的），并写明输出语言
    assert messages[-1] == {"role": "user", "content": "<原话>你又不回我消息！</原话>\nrewrite 的语言：中文"}


def test_language_is_detected_from_original():
    assert ai.detect_lang("你是头猪") == "zh"
    assert ai.detect_lang("You never listen") == "en"
    assert ai.detect_lang("ok啦") == "zh"  # 有汉字就算中文
    assert ai.detect_lang("1234 😊") is None  # 只有数字和表情：不限制
    assert ai.soften_messages("You never listen")[-1]["content"].endswith("rewrite language: English")
    assert "语言" not in ai.soften_messages("😊")[-1]["content"]


def test_problems_found_in_output():
    # 人称反了：站在被骂的人的角度回应，并引用了原话（人类实际遇到的例子）
    assert ai.problem_with("你是头猪", "你说“你是头猪”的时候，我有点受伤，希望我们能好好说话。", "zh") == "echo"
    # 中文原话改成了英文 / 英文原话改成了中文
    assert ai.problem_with("你是头猪", "I'm really upset right now.", "zh") == "wrong_lang"
    assert ai.problem_with("You never listen", "我觉得你没在听我说话", "en") == "wrong_lang"
    # 正常的改写
    assert ai.problem_with("你是头猪", "我现在真的很生气，我们能好好聊聊吗？", "zh") is None
    assert ai.problem_with("You never listen", "I feel unheard sometimes.", "en") is None
    assert ai.problem_with("晚安", "“晚安”呀", "zh") is None  # 太短的原话不做复述检查


def test_reply_perspective_is_detected():
    """人称反了、在回应对方说过的话（人类实际遇到的两个例子）。"""
    assert ai.problem_with("你好丑", "你这样说让我有点难受，我希望你能多夸夸我。", "zh") == "reply"
    assert ai.problem_with("你真丑", "你说这话的时候我有点难过，我希望我们之间能多一些温柔的表达。", "zh") == "reply"
    assert ai.problem_with("You are ugly", "When you say that, I feel hurt.", "en") == "reply"
    # 正确的人称：说话的人表达自己的情绪
    assert ai.problem_with("你好丑", "我现在有点生你的气，嘴上忍不住想损你。", "zh") is None
    # 原话本身提到"说"：改写里出现"你说"是正常的，不算
    assert ai.problem_with("你说过会早点回来", "你说过会早点回来的，我等了好久有点失落。", "zh") is None


def test_retry_when_rewrite_takes_partners_side(app, fake_ai):
    fake_ai.reply = [
        json.dumps({"speaker_feeling": "被说丑很难过", "rewrite": "你这样说让我有点难受，我希望你能多夸夸我。"}, ensure_ascii=False),
        json.dumps({"speaker_feeling": "在生伴侣的气", "rewrite": "我现在有点生你的气，嘴上忍不住想损你。"}, ensure_ascii=False),
    ]
    with app.app_context():
        result = ai.soften("sk-test-1234567890", "你好丑")
    assert result.status == ai.OK
    assert result.text == "我现在有点生你的气，嘴上忍不住想损你。"
    assert len(fake_ai.calls) == 2


def test_retry_once_when_perspective_is_wrong(app, fake_ai):
    fake_ai.reply = ["你说“你是头猪”的时候，我有点受伤。", "我现在真的很生气，我们能好好聊聊吗？"]
    with app.app_context():
        result = ai.soften("sk-test-1234567890", "你是头猪")
    assert result.status == ai.OK
    assert result.text == "我现在真的很生气，我们能好好聊聊吗？"
    assert len(fake_ai.calls) == 2
    assert fake_ai.calls[0]["messages"][-1]["content"] == "<原话>你是头猪</原话>\nrewrite 的语言：中文"
    assert fake_ai.calls[1]["messages"][-1]["content"].endswith(SOFTEN_RETRY_REMINDER)


def test_retry_once_when_language_changes(app, fake_ai):
    fake_ai.reply = ["I'm really upset right now.", "我现在有点生气。"]
    with app.app_context():
        assert ai.soften("sk-test-1234567890", "你是头猪").text == "我现在有点生气。"


def test_give_up_after_second_bad_result(app, fake_ai, caplog):
    """两次都不合格：返回 ERROR（前端提示再试一次或直接发送），不把错误的改写给用户。"""
    fake_ai.reply = ["I'm upset.", "Still English."]
    with caplog.at_level(logging.INFO), app.app_context():
        result = ai.soften("sk-test-1234567890", "你是头猪")
    assert result.status == ai.ERROR
    assert len(fake_ai.calls) == 2
    assert "retry reason=wrong_lang" in caplog.text
    assert "你是头猪" not in caplog.text and "upset" not in caplog.text


def test_unsafe_and_api_errors_are_not_retried(app, fake_ai):
    with app.app_context():
        fake_ai.reply = "[UNSAFE]"
        assert ai.soften("sk-test-1234567890", "...").status == ai.UNSAFE
        assert len(fake_ai.calls) == 1
        fake_ai.error = FakeAPIError(429)
        assert ai.soften("sk-test-1234567890", "...").status == ai.RATE_LIMITED
        assert len(fake_ai.calls) == 2


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
