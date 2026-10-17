"""软化结果解析（纯函数，不需要 Flask）。"""

from services.ai import ERROR, OK, UNSAFE, parse_soften_output


def test_plain_text():
    r = parse_soften_output("你没回消息的时候我会有点不安。")
    assert r.status == OK
    assert r.text == "你没回消息的时候我会有点不安。"


def test_strips_whitespace_and_quotes():
    assert parse_soften_output('  "I feel a bit lonely."  \n').text == "I feel a bit lonely."
    assert parse_soften_output("“我有点想你。”").text == "我有点想你。"
    assert parse_soften_output("「我有点累了」").text == "我有点累了"


def test_inner_quotes_are_kept():
    # 只去掉包住整句话的成对引号，句子中间的引号保留
    assert parse_soften_output('我希望你说"晚安"再睡').text == '我希望你说"晚安"再睡'


def test_unsafe_at_start():
    r = parse_soften_output("[UNSAFE]")
    assert r.status == UNSAFE
    assert r.text == ""


def test_unsafe_with_spaces_or_lowercase():
    assert parse_soften_output("  [unsafe]  ").status == UNSAFE
    assert parse_soften_output("[UNSAFE] 原话涉及威胁").status == UNSAFE


def test_unsafe_anywhere_is_still_unsafe():
    # 比"以 [UNSAFE] 开头"更严格：出现在任何位置都不发送
    assert parse_soften_output("好的。[UNSAFE]").status == UNSAFE


def test_empty_reply_is_error():
    assert parse_soften_output("").status == ERROR
    assert parse_soften_output("   ").status == ERROR
    assert parse_soften_output(None).status == ERROR
    assert parse_soften_output('""').status == ERROR
