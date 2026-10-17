"""长凳五子棋：两个人轮流落子（各用自己的设备，页面轮询同步）。

规则：15×15 棋盘；谁开新的一局谁执黑先下；横、竖、斜任意方向连成五颗（或更多）同色棋子就赢；
下满了算平局；进行中可以认输。没有禁手，适合轻松地玩。

纯函数（不碰数据库，方便测试）：winning_line、is_my_turn ……
数据库操作：current_game、start、play、resign —— 会出错的地方抛 GomokuError(code)，code 用于提示文字。
"""

import json

from db import get_db

SIZE = 15
WIN = 5
DIRECTIONS = ((0, 1), (1, 0), (1, 1), (1, -1))  # 横、竖、两条斜线

PLAYING, WON, RESIGNED, DRAW = "playing", "won", "resigned", "draw"


class GomokuError(Exception):
    """不能这样下：code 是 not_your_turn / occupied / out_of_range / finished / no_game / no_partner / still_playing。"""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ---------- 纯函数 ----------


def board_of(moves):
    """{(行, 列): "black" / "white"}。第 0、2、4… 手是黑棋。"""
    return {(r, c): ("black" if i % 2 == 0 else "white") for i, (r, c) in enumerate(moves)}


def winning_line(moves):
    """最后一手有没有连成五子：有的话返回这一串棋子的坐标列表（≥5 颗），没有返回 None。"""
    if not moves:
        return None
    board = board_of(moves)
    r0, c0 = moves[-1]
    color = board[(r0, c0)]
    for dr, dc in DIRECTIONS:
        line = [(r0, c0)]
        for sign in (1, -1):
            r, c = r0 + dr * sign, c0 + dc * sign
            while board.get((r, c)) == color:
                line.append((r, c))
                r, c = r + dr * sign, c + dc * sign
        if len(line) >= WIN:
            return sorted(line)
    return None


def color_to_move(moves):
    return "black" if len(moves) % 2 == 0 else "white"


def color_of(game, member_id):
    if member_id == game["black_id"]:
        return "black"
    if member_id == game["white_id"]:
        return "white"
    return None


# ---------- 数据库 ----------


def current_game():
    """最近的一局（没有下过返回 None）。"""
    return get_db().execute("SELECT * FROM gomoku_games ORDER BY id DESC LIMIT 1").fetchone()


def moves_of(game):
    return [tuple(m) for m in json.loads(game["moves"])] if game else []


def start(member_id, partner_id):
    """开新的一局：开局的人执黑。上一局还没下完时不能开（先认输）。"""
    if partner_id is None:
        raise GomokuError("no_partner")
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    game = current_game()
    if game is not None and game["status"] == PLAYING:
        db.rollback()
        raise GomokuError("still_playing")
    db.execute("INSERT INTO gomoku_games (black_id, white_id) VALUES (?, ?)", (member_id, partner_id))
    db.commit()
    return current_game()


def play(member_id, row, col):
    """落子：检查轮到谁、位置是否空，然后判断输赢 / 平局。返回更新后的这一局。"""
    db = get_db()
    db.execute("BEGIN IMMEDIATE")  # 加写锁：两个人同时点也不会下出两步
    try:
        game = current_game()
        if game is None:
            raise GomokuError("no_game")
        if game["status"] != PLAYING:
            raise GomokuError("finished")
        moves = moves_of(game)
        if color_of(game, member_id) != color_to_move(moves):
            raise GomokuError("not_your_turn")
        if not (0 <= row < SIZE and 0 <= col < SIZE):
            raise GomokuError("out_of_range")
        if (row, col) in board_of(moves):
            raise GomokuError("occupied")
        moves.append((row, col))
        line = winning_line(moves)
        status, winner, win_line = PLAYING, None, None
        if line:
            status, winner, win_line = WON, member_id, json.dumps(line)
        elif len(moves) == SIZE * SIZE:
            status = DRAW
        db.execute(
            "UPDATE gomoku_games SET moves = ?, status = ?, winner_id = ?, win_line = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (json.dumps(moves), status, winner, win_line, game["id"]),
        )
        db.commit()
    except GomokuError:
        db.rollback()
        raise
    return current_game()


def resign(member_id):
    """认输：对方获胜。"""
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    game = current_game()
    if game is None or game["status"] != PLAYING or color_of(game, member_id) is None:
        db.rollback()
        raise GomokuError("finished" if game else "no_game")
    winner = game["white_id"] if member_id == game["black_id"] else game["black_id"]
    db.execute("UPDATE gomoku_games SET status = ?, winner_id = ?, updated_at = datetime('now') WHERE id = ?",
               (RESIGNED, winner, game["id"]))
    db.commit()
    return current_game()


def view(game, viewer_id):
    """页面和轮询接口用的数据（都从看的人的角度）：
    {id, size, moves, my_color, turn: "me"/"partner"/None, status, result: "win"/"lose"/"draw"/None,
     win_line, version}"""
    if game is None:
        return {"id": None, "size": SIZE, "moves": [], "my_color": None, "turn": None, "status": None,
                "result": None, "win_line": [], "version": "none"}
    moves = moves_of(game)
    mine = color_of(game, viewer_id)
    turn = None
    if game["status"] == PLAYING:
        turn = "me" if color_to_move(moves) == mine else "partner"
    result = None
    if game["status"] == DRAW:
        result = "draw"
    elif game["status"] in (WON, RESIGNED):
        result = "win" if game["winner_id"] == viewer_id else "lose"
    return {
        "id": game["id"],
        "size": SIZE,
        "moves": [list(m) for m in moves],
        "my_color": mine,
        "turn": turn,
        "status": game["status"],
        "result": result,
        "win_line": json.loads(game["win_line"]) if game["win_line"] else [],
        # 轮询用：局号、步数、状态任何一个变了就说明有新情况
        "version": f"{game['id']}:{len(moves)}:{game['status']}",
    }
