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


def test_strips_prefixes_and_tags():
    # 模型偶尔会加"改写后："之类的前缀，或者把 <原话> 标签也抄出来
    assert parse_soften_output("改写后：我现在有点生气。").text == "我现在有点生气。"
    assert parse_soften_output("温柔版: 我有点累了").text == "我有点累了"
    assert parse_soften_output("Rewritten: I feel a bit lonely.").text == "I feel a bit lonely."
    assert parse_soften_output("<原话>我有点想你</原话>").text == "我有点想你"
    # 句子中间的冒号不受影响
    assert parse_soften_output("我想说：今天辛苦了").text == "我想说：今天辛苦了"


def test_json_answer():
    # 模型按要求输出 JSON：只把 rewrite 给用户，speaker_feeling 不显示
    r = parse_soften_output('{"speaker_feeling": "在生伴侣的气", "rewrite": "我现在有点生你的气。"}')
    assert r.status == OK
    assert r.text == "我现在有点生你的气。"
    assert parse_soften_output('{"rewrite": "  “我有点想你。”  "}').text == "我有点想你。"


def test_json_unsafe_and_broken_json():
    assert parse_soften_output('{"unsafe": true}').status == UNSAFE
    assert parse_soften_output('{"speaker_feeling": "x"}').status == ERROR  # 没有 rewrite
    assert parse_soften_output('{"rewrite": 123}').status == ERROR
    # 不是 JSON：整段当成改写（兼容）
    assert parse_soften_output("我现在有点生气").text == "我现在有点生气"
