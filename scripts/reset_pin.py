"""在服务器上直接重置某位岛民的 PIN（给运行小岛的人用）。

什么时候用：有人忘记了 PIN，但小岛上只有 TA 一个人（没有另一半可以在小信箱里帮 TA 生成重置码）。
有另一半时，请优先用网页上的办法：另一半登录 → 小信箱 →「帮 TA 重置 PIN」→ 在登录页「忘记 PIN？」里使用。

用法（在项目根目录运行）：
    .venv\\Scripts\\python.exe scripts\\reset_pin.py            列出岛民，按提示选择并输入新 PIN
    .venv\\Scripts\\python.exe scripts\\reset_pin.py 小雨       直接重置昵称为"小雨"的岛民

数据库位置和网站一样，由 .env / 环境变量里的 DATA_DIR 决定（默认 data/usland.db）。
输入的 PIN 不会显示在屏幕上，也不会被记录。
"""

import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402  （要先把项目根目录加入 sys.path）
from services import auth  # noqa: E402


def choose_member(members, nickname):
    """按昵称找岛民；没给昵称时列出所有人让用户选。找不到返回 None。"""
    if nickname:
        return next((m for m in members if m["nickname"] == nickname), None)
    for i, m in enumerate(members, 1):
        print(f"  {i}. {m['nickname']}")
    answer = input("要重置谁的 PIN？输入序号：").strip()
    if answer.isdigit() and 1 <= int(answer) <= len(members):
        return members[int(answer) - 1]
    return None


def main():
    app = create_app()
    with app.app_context():
        members = auth.get_members()
        if not members:
            print("还没有小岛或岛民，不需要重置。")
            return 1

        member = choose_member(members, sys.argv[1] if len(sys.argv) > 1 else None)
        if member is None:
            print("没有找到这位岛民。")
            return 1

        pin = getpass.getpass(f"给 {member['nickname']} 设置新的 PIN（4–6 位数字）：")
        if not auth.is_valid_pin(pin):
            print("PIN 需要是 4–6 位数字，没有修改。")
            return 1
        if getpass.getpass("再输入一次：") != pin:
            print("两次输入的 PIN 不一样，没有修改。")
            return 1

        auth.set_pin(member["id"], pin)  # 同时解除锁定、作废重置码
        print(f"{member['nickname']} 的 PIN 已经重置，可以用新的 PIN 登录了。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
