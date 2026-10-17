"""用真实的 DeepSeek 试一试"温柔传话"的改写效果（给开发者手动检查提示词用，会花一点点余额）。

用法（在项目根目录运行，key 和 test_ai.py 一样从 .env 的 DEEPSEEK_API_KEY 读取）：
    .venv\\Scripts\\python.exe scripts\\try_soften.py              跑下面的默认例句，每句 3 遍
    .venv\\Scripts\\python.exe scripts\\try_soften.py 你是头猪      只跑这一句
    .venv\\Scripts\\python.exe scripts\\try_soften.py --times 5     每句跑 5 遍，看稳不稳定

走的是网站里同一个 services.ai.soften()（同样的提示词、示例、语言检查和重试），
所以这里看到的结果就是网页上会看到的。
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from app import create_app  # noqa: E402
from services import ai  # noqa: E402

# 容易出问题的原话：骂人、问句、很短、本来就温和、英文、夸张说法、需要安全卡片的
SAMPLES = [
    "你是头猪",
    "你脑子是不是有病",
    "你在干嘛",
    "随便",
    "我分手了！",
    "气死我了，你怎么又迟到",
    "今天辛苦啦，早点睡",
    "You never listen to me.",
    "Whatever, do what you want.",
    "你再这样我就去你公司闹",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="*", help="要试的原话（不写就用默认例句）")
    parser.add_argument("--times", type=int, default=3, help="每句跑几遍")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("没有找到 DEEPSEEK_API_KEY：请在 .env 里填写（只给开发者测试用）。")
        return 1

    samples = [" ".join(args.text)] if args.text else SAMPLES
    app = create_app()
    with app.app_context():
        for original in samples:
            print(f"\n原话：{original}")
            for i in range(args.times):
                result = ai.soften(key, original)
                shown = result.text if result.status == ai.OK else f"[{result.status}]"
                print(f"  {i + 1}. {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
