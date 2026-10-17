"""长凳五子棋：输赢判断（纯函数）、轮流落子、认输、新局、页面和接口、地图上的长凳入口。"""

import json

from services import gomoku
from tests.test_auth import create_island, invite_code, join_island


def pair(client, partner, app):
    """小雨创建小岛，阿木加入，两人都登录着。"""
    create_island(client, nickname="小雨")
    join_island(partner, invite_code(app), nickname="阿木")


def move(client, row, col):
    return client.post("/game/move", json={"row": row, "col": col})


# ---------- 纯函数 ----------


def test_five_in_a_row_in_every_direction():
    def black_line(points):
        # 黑白交替：黑子下在 points，白子下在远处不相干的位置
        moves = []
        for i, p in enumerate(points):
            moves.append(p)
            if i < len(points) - 1:
                moves.append((14, i))
        return moves

    assert gomoku.winning_line(black_line([(7, c) for c in range(3, 8)])) == [(7, c) for c in range(3, 8)]
    assert gomoku.winning_line(black_line([(r, 2) for r in range(5)]))
    assert gomoku.winning_line(black_line([(i, i) for i in range(5)]))
    assert gomoku.winning_line(black_line([(i, 10 - i) for i in range(5)]))
    # 最后一手下在中间也算
    assert gomoku.winning_line(black_line([(7, 3), (7, 4), (7, 6), (7, 7), (7, 5)]))
    # 四颗不算
    assert gomoku.winning_line(black_line([(7, c) for c in range(3, 7)])) is None
    # 长连（六颗）也算赢
    assert len(gomoku.winning_line(black_line([(7, c) for c in range(2, 8)]))) == 6


def test_colors_alternate():
    assert gomoku.color_to_move([]) == "black"
    assert gomoku.color_to_move([(7, 7)]) == "white"
    assert gomoku.board_of([(7, 7), (7, 8)]) == {(7, 7): "black", (7, 8): "white"}


# ---------- 对局 ----------


def test_full_game_and_turns(client, partner, app):
    pair(client, partner, app)
    # 还没开局
    assert client.get("/api/game/state").get_json()["status"] is None
    assert move(client, 7, 7).status_code == 409

    # 小雨开局：执黑先下
    state = client.post("/game/new", json={}).get_json()["state"]
    assert state["my_color"] == "black" and state["turn"] == "me"
    assert partner.get("/api/game/state").get_json()["turn"] == "partner"

    # 不是自己的回合 / 已经有子 / 不在棋盘上
    assert move(partner, 0, 0).get_json()["code"] == "not_your_turn"
    assert move(client, 7, 7).get_json()["ok"] is True
    assert move(partner, 7, 7).get_json()["code"] == "occupied"
    assert move(partner, 15, 0).get_json()["code"] == "out_of_range"

    # 黑棋在第 7 行连成五子
    for c in range(1, 5):
        move(partner, 0, c)
        move(client, 7, 7 + c)
    mine = client.get("/api/game/state").get_json()
    theirs = partner.get("/api/game/state").get_json()
    assert mine["status"] == "won" and mine["result"] == "win" and mine["turn"] is None
    assert theirs["result"] == "lose"
    assert mine["win_line"] == [[7, c] for c in range(7, 12)]
    # 结束后不能再下
    assert move(partner, 1, 1).get_json()["code"] == "finished"

    # 阿木开新的一局：这次阿木执黑
    state = partner.post("/game/new", json={}).get_json()["state"]
    assert state["my_color"] == "black" and state["moves"] == []
    assert client.get("/api/game/state").get_json()["my_color"] == "white"


def test_cannot_start_while_playing_then_resign(client, partner, app):
    pair(client, partner, app)
    client.post("/game/new", json={})
    assert partner.post("/game/new", json={}).get_json()["code"] == "still_playing"
    state = partner.post("/game/resign", json={}).get_json()["state"]
    assert state["status"] == "resigned" and state["result"] == "lose"
    assert client.get("/api/game/state").get_json()["result"] == "win"


def test_version_changes_for_polling(client, partner, app):
    pair(client, partner, app)
    client.post("/game/new", json={})
    v1 = partner.get("/api/game/state").get_json()["version"]
    move(client, 7, 7)
    assert partner.get("/api/game/state").get_json()["version"] != v1


def test_alone_cannot_play(client):
    create_island(client)
    html = client.get("/game").get_data(as_text=True)
    assert "data-wait-partner" in html and "data-board" not in html
    assert client.post("/game/new", json={}).get_json()["code"] == "no_partner"


# ---------- 页面（没有 JavaScript 也能下） ----------


def test_page_works_without_javascript(client, partner, app):
    pair(client, partner, app)
    html = client.get("/game").get_data(as_text=True)
    assert "长凳五子棋" in html
    assert html.count('name="cell"') == 225
    assert "还没开始下棋" in html

    # 普通表单：开局、落子，跳回棋盘页
    assert client.post("/game/new").headers["Location"] == "/game"
    assert client.post("/game/move", data={"cell": "7,7"}).headers["Location"] == "/game"
    html = client.get("/game").get_data(as_text=True)
    assert 'value="7,7"' in html and "stone-black is-last" in html
    assert "等 阿木 落子" in html
    # 还没轮到时，所有交叉点都不能点
    assert html.count("disabled") >= 225

    # 出错时显示一次性提示
    client.post("/game/move", data={"cell": "0,0"})
    assert "还没轮到你哦" in client.get("/game").get_data(as_text=True)
    state = json.loads(html.split('id="gomoku-state">')[1].split("</script>")[0])
    assert state["moves"] == [[7, 7]]


def test_game_needs_login(raw_client):
    assert raw_client.get("/game").status_code == 302
    assert raw_client.get("/api/game/state").status_code == 401


# ---------- 地图上的长凳入口 ----------


def test_bench_on_map_but_not_in_nav(client):
    create_island(client)
    html = client.get("/").get_data(as_text=True)
    # 两套构图各一个长凳热区（贴着长凳轮廓）和"长凳五子棋"标签
    assert html.count('class="hotspot" href="/game"') == 2
    assert "长凳五子棋" in html
    # 竖版底图里没有长凳：额外叠一张长凳图
    assert html.count('class="scene-prop"') == 1 and "bench_mobile.png" in html
    # 顶部和底部导航仍然只有五个功能
    nav = html.split('class="topnav"')[1].split("</nav>")[0]
    assert "/game" not in nav and nav.count("topnav-link") == 5
    bottom = html.split('class="bottom-nav')[1].split("</nav>")[0]
    assert "/game" not in bottom


def test_forest_peek_animal_removed(client):
    create_island(client)
    html = client.get("/").get_data(as_text=True)
    assert 'class="peek"' not in html


# ---------- 道具互动 ----------


def test_props_reach_partner(client, partner, app):
    pair(client, partner, app)
    resp = client.post("/game/prop", json={"kind": "tomato"})
    assert resp.status_code == 200 and resp.get_json()["ok"] is True
    # 对方轮询时看到"partner 扔的番茄"；自己看到的是"me"
    theirs = partner.get("/api/game/state").get_json()["props"]
    assert theirs[-1]["kind"] == "tomato" and theirs[-1]["from"] == "partner"
    assert client.get("/api/game/state").get_json()["props"][-1]["from"] == "me"
    # 没开局也能扔（道具和棋局无关），三种都可以
    assert partner.post("/game/prop", json={"kind": "coffee"}).status_code == 200


def test_props_validation_and_cooldown(client, partner, app):
    pair(client, partner, app)
    assert client.post("/game/prop", json={"kind": "brick"}).get_json()["code"] == "bad_prop"
    assert client.post("/game/prop", json={"kind": "egg"}).status_code == 200
    too_fast = client.post("/game/prop", json={"kind": "egg"})
    assert too_fast.status_code == 429 and too_fast.get_json()["code"] == "too_fast"


def test_props_need_partner(client):
    create_island(client)
    assert client.post("/game/prop", json={"kind": "coffee"}).get_json()["code"] == "no_partner"


def test_prop_buttons_and_images_on_page(client, partner, app):
    pair(client, partner, app)
    html = client.get("/game").get_data(as_text=True)
    assert "给阿姨倒一杯卡布奇诺" in html and "扔番茄" in html and "扔鸡蛋" in html
    assert 'data-props role="group"' in html and "hidden>" in html  # 没有 JS 时隐藏
    for name in ("coffee", "tomato", "egg", "splash", "trophy", "tear_smile", "handshake", "sparkles"):
        assert f"/static/usland/assets/ui/fun/{name}.png" in html


def test_fun_images_exist_and_are_credited():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for name in ("coffee", "tomato", "egg", "splash", "trophy", "tear_smile", "handshake", "sparkles"):
        assert (root / "static/usland/assets/ui/fun" / f"{name}.png").is_file()
    assert "Fluent Emoji" in (root / "docs/credits.md").read_text(encoding="utf-8")
    assert (root / "docs/licenses/fluent_emoji_MIT.txt").is_file()


# ---------- 结算画面的数据 ----------


def test_settle_data_and_record(client, partner, app):
    pair(client, partner, app)
    client.post("/game/new", json={})
    assert client.get("/api/game/state").get_json()["settle"] is None  # 进行中没有结算
    # 小雨连成五子赢第一局
    move(client, 7, 7)
    for c in range(1, 5):
        move(partner, 0, c)
        move(client, 7, 7 + c)
    mine = client.get("/api/game/state").get_json()
    assert mine["settle"]["moves"] == 9
    assert mine["settle"]["seconds"] >= 0
    assert mine["settle"]["record"] == {"me": 1, "partner": 0, "draw": 0}
    assert mine["resigned_by"] is None
    # 第二局小雨认输：阿木 1 胜
    partner.post("/game/new", json={})
    client.post("/game/resign", json={})
    theirs = partner.get("/api/game/state").get_json()
    assert theirs["resigned_by"] == "partner" and theirs["result"] == "win"
    assert theirs["settle"]["record"] == {"me": 1, "partner": 1, "draw": 0}
    assert client.get("/api/game/state").get_json()["resigned_by"] == "me"


def test_settle_dialog_on_page(client, partner, app):
    pair(client, partner, app)
    html = client.get("/game").get_data(as_text=True)
    assert 'class="panel gomoku-settle" data-settle' in html
    assert "再来一局" in html and "看看棋盘" in html and "回到小岛" in html
