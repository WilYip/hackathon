"""SQLite 数据库：连接管理与建表。

用法：
- 在请求中：db = get_db()，然后 db.execute(...)
- 手动初始化：python db.py （或 flask --app app init-db）
- 应用启动时也会自动调用 init_db()，所以一般不需要手动运行。

建表语句全部使用 CREATE TABLE IF NOT EXISTS，重复运行是安全的。
后续里程碑需要新表时，直接在 SCHEMA 里追加即可。
"""

import sqlite3
from pathlib import Path

import click
from flask import current_app, g

SCHEMA = """
-- 小岛：一个实例只有一座小岛，所以这张表最多只有一行（id 固定为 1）
CREATE TABLE IF NOT EXISTS island (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    name            TEXT    NOT NULL,
    invite_code     TEXT    NOT NULL,
    deepseek_api_key TEXT,                       -- 用户填写的 key，只在后端使用，永不返回前端
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- 成员：最多两人
CREATE TABLE IF NOT EXISTS members (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname        TEXT    NOT NULL,
    pin_hash        TEXT    NOT NULL,            -- werkzeug.security 生成的哈希
    lang            TEXT    NOT NULL DEFAULT 'zh',
    animal_code     TEXT,                        -- 初见森林的结果，如 ENFP
    failed_attempts INTEGER NOT NULL DEFAULT 0,  -- PIN 连续错误次数
    locked_until    TEXT,                        -- 锁定到期时间（UTC ISO 格式）
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ===== M4 温柔传话 =====

-- 传话消息。final_text 是对方看到的版本；
-- original_text 是软化前的原话（直接发送时为空），只在发送者本人请求时返回
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id       INTEGER NOT NULL REFERENCES members(id),
    final_text      TEXT    NOT NULL,
    original_text   TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))  -- UTC
);

-- 每个人读到了哪条消息（用来算首页传话码头的未读数）
CREATE TABLE IF NOT EXISTS whisper_reads (
    member_id       INTEGER PRIMARY KEY REFERENCES members(id),
    last_read_id    INTEGER NOT NULL DEFAULT 0
);

-- 谁按下了"和好"。双方都按下后清空，并在回忆里加一条记录
CREATE TABLE IF NOT EXISTS reconcile_requests (
    member_id       INTEGER PRIMARY KEY REFERENCES members(id),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- 每天的软化次数（每座小岛每天最多 100 次），day 为 UTC 日期 YYYY-MM-DD
CREATE TABLE IF NOT EXISTS soften_usage (
    day             TEXT    PRIMARY KEY,
    count           INTEGER NOT NULL DEFAULT 0
);

-- 回忆时间线（M7 实现页面）。kind：reconcile 和好 / quest 约会任务 / forest 初见森林 / manual 手动添加
-- 和好记录的标题和文字由页面按 kind 和当前语言显示，所以 title / note 可以为空
CREATE TABLE IF NOT EXISTS memories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT    NOT NULL,
    title           TEXT,
    note            TEXT,
    photo           TEXT,
    created_by      INTEGER REFERENCES members(id),
    ref             TEXT,                        -- 关联的内容 id，例如约会任务的 task_id（M5 新增）
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ===== M5 约会选选选 =====

-- 一轮约会冒险。同一时间只能有一轮进行中（status 为 choosing / deciding / confirmed）
--   choosing  双方各自选择中
--   deciding  双方都选好了，正在共同挑任务（可能有一方已提议）
--   confirmed 已共同确定，等待完成
--   completed 已完成（写入了回忆）
--   cancelled 中途结束
CREATE TABLE IF NOT EXISTS quest_rounds (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    status              TEXT    NOT NULL DEFAULT 'choosing',
    created_by          INTEGER REFERENCES members(id),
    recommendations     TEXT,                    -- 匹配结果 JSON：[{task_id, score, relaxed, reason}]
    proposed_task_id    TEXT,                    -- 当前提议的任务
    proposed_by         INTEGER REFERENCES members(id),
    confirmed_task_id   TEXT,                    -- 双方都同意的任务
    memory_id           INTEGER REFERENCES memories(id),
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at        TEXT
);

-- 每个人在这一轮里的选择（双方都提交前，对方看不到）
CREATE TABLE IF NOT EXISTS quest_choices (
    round_id        INTEGER NOT NULL REFERENCES quest_rounds(id),
    member_id       INTEGER NOT NULL REFERENCES members(id),
    time_option     TEXT    NOT NULL,
    budget          TEXT    NOT NULL,
    mood            TEXT    NOT NULL,
    want            TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (round_id, member_id)
);

-- ===== M6 初见森林 =====

-- 每次做完森林动物性格测试的结果（可以重测，最新一次同时写进 members.animal_code）
CREATE TABLE IF NOT EXISTS forest_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id       INTEGER NOT NULL REFERENCES members(id),
    code            TEXT    NOT NULL,            -- 动物代码，如 ENFP
    answers         TEXT    NOT NULL,            -- 12 题的答案 JSON，如 ["a","b",...]
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- 猜猜 TA 是哪只小动物：先测完的人猜还没测的另一半；对方测完时揭晓并写一条回忆
-- 揭晓前可以改猜（每人最多一条未揭晓的猜测）
CREATE TABLE IF NOT EXISTS forest_guesses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guesser_id      INTEGER NOT NULL REFERENCES members(id),
    target_id       INTEGER NOT NULL REFERENCES members(id),
    code            TEXT    NOT NULL,            -- 猜的动物代码
    actual_code     TEXT,                        -- 对方测出的动物（揭晓前为空）
    memory_id       INTEGER REFERENCES memories(id),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    revealed_at     TEXT
);

-- ===== 长凳五子棋 =====
-- 一局棋。谁开的新局谁执黑先下；moves 是落子顺序 [[行, 列], ...]，第 0、2、4… 手是黑棋。
-- status：playing 进行中 / won 五子连珠 / resigned 有人认输 / draw 下满了平局
CREATE TABLE IF NOT EXISTS gomoku_games (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    black_id        INTEGER NOT NULL REFERENCES members(id),
    white_id        INTEGER NOT NULL REFERENCES members(id),
    moves           TEXT    NOT NULL DEFAULT '[]',
    status          TEXT    NOT NULL DEFAULT 'playing',
    winner_id       INTEGER REFERENCES members(id),
    win_line        TEXT,                        -- 连成五子的那几颗 [[行, 列], ...]，用来高亮
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- 下棋时的道具互动（像斗地主那样）：倒卡布奇诺 coffee / 扔番茄 tomato / 扔鸡蛋 egg。
-- 只用来让对方的页面播一次动画，轮询时按 id 取新的；不进回忆
CREATE TABLE IF NOT EXISTS gomoku_props (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id       INTEGER NOT NULL REFERENCES members(id),
    kind            TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

# 给已经存在的旧数据库补上新增的列（CREATE TABLE IF NOT EXISTS 不会修改已有的表）
# 格式：(表名, 列名, 列定义)
NEW_COLUMNS = [
    ("memories", "ref", "TEXT"),
    # 情绪状态（VISUAL_DESIGN 13.4）：happy 开心 / wronged 委屈 / need_space 需要空间 / calm 平静
    ("members", "mood", "TEXT"),
    ("members", "mood_set_at", "TEXT"),  # 选择的时间（UTC），24 小时后自动恢复平静
    # 忘记 PIN：另一半在小信箱生成的一次性重置码（只存哈希）和过期时间（UTC ISO 格式）
    ("members", "reset_code_hash", "TEXT"),
    ("members", "reset_code_expires", "TEXT"),
]


def _add_missing_columns(conn):
    for table, column, decl in NEW_COLUMNS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def connect(db_path):
    """打开一个 SQLite 连接。查询结果可以像字典一样用列名取值。"""
    conn = sqlite3.connect(Path(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """获取当前请求的数据库连接（同一请求内复用同一个连接）。"""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(exc=None):
    """请求结束时关闭连接。"""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(db_path):
    """创建所有数据表（已存在的表不会被改动），并给旧数据库补上新增的列。"""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _add_missing_columns(conn)
        conn.commit()
    finally:
        conn.close()


@click.command("init-db")
def init_db_command():
    """命令行：flask --app app init-db"""
    init_db(current_app.config["DATABASE_PATH"])
    click.echo("数据库已初始化。")


def init_app(app):
    """在应用工厂中注册：请求结束自动关闭连接、命令行命令、启动时建表。"""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    init_db(app.config["DATABASE_PATH"])


if __name__ == "__main__":
    # 直接运行 python db.py 时，按 config.py 的配置初始化数据库
    from config import Config

    cfg = Config()
    init_db(cfg.DATABASE_PATH)
    print(f"数据库已初始化：{cfg.DATABASE_PATH}")
