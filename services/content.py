"""读取 content/ 目录下的 JSON 内容数据（地图区域、任务库、动物、题目……）。"""

import json
from functools import lru_cache
from pathlib import Path

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"


@lru_cache(maxsize=None)
def load(name):
    """读取 content/<name>.json。结果会缓存，修改 JSON 后需要重启应用。"""
    path = CONTENT_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def regions():
    """小岛地图的五个功能区域（列表）。"""
    return load("regions")["regions"]

