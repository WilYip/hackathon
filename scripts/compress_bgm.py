"""把 static/audio/bgm/ 里的背景音乐重新压缩到约 96–112 kbps，减小体积（换页时加载更快）。

需要先安装 ffmpeg（不是 Python 包，是一个命令行工具）：
    winget install Gyan.FFmpeg        （Windows，装完重新打开终端）
    brew install ffmpeg               （Mac）

用法（在项目根目录运行）：
    .venv\\Scripts\\python.exe scripts\\compress_bgm.py --dry-run     只看看会压缩哪些、大概能省多少，不改文件
    .venv\\Scripts\\python.exe scripts\\compress_bgm.py               压缩（默认 104 kbps）
    .venv\\Scripts\\python.exe scripts\\compress_bgm.py --bitrate 96  指定码率（96–112）

安全措施：
- 压缩前把原文件复制到 data/audio_originals/bgm/（data/ 不会提交到 git，也不会被网站访问到）；
  已经有备份时不会覆盖备份，所以重复运行总是从**原始文件**压缩，不会越压越差
- 码率已经不高于目标 + 8 kbps 的文件会跳过（除非加 --force）
- 先写到临时文件，检查成功后才替换原文件；失败时原文件保持不变
- 只改音质，不改时长，所以 content/audio_manifest.json 里的时长不需要更新
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BGM_DIR = ROOT / "static" / "audio" / "bgm"
BACKUP_DIR = ROOT / "data" / "audio_originals" / "bgm"
MANIFEST = ROOT / "content" / "audio_manifest.json"


def durations():
    """清单里每个文件的时长（秒）：{"bgm_island.mp3": 329.68, ...}"""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {Path(a["path"]).name: a.get("duration_seconds") for a in data["assets"]}


def kbps(path, seconds):
    """平均码率（kbps）= 文件大小 × 8 ÷ 时长。时长未知时返回 None。"""
    if not seconds:
        return None
    return path.stat().st_size * 8 / seconds / 1000


def encode(ffmpeg, source, target, bitrate):
    """用 ffmpeg（LAME 编码器）把 source 压缩成 target。成功返回 True。"""
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
           "-map", "0:a", "-map_metadata", "0", "-c:a", "libmp3lame", "-b:a", f"{bitrate}k", str(target)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("    ffmpeg 出错：", result.stderr.strip()[:300])
        return False
    return target.exists() and target.stat().st_size > 0


def main():
    parser = argparse.ArgumentParser(description="重新压缩背景音乐到约 96–112 kbps")
    parser.add_argument("--bitrate", type=int, default=104, help="目标码率 kbps（96–112，默认 104）")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不修改文件")
    parser.add_argument("--force", action="store_true", help="码率已经不高的文件也重新压缩")
    args = parser.parse_args()

    if not 96 <= args.bitrate <= 112:
        sys.exit("码率请设在 96 到 112 之间。")

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None and not args.dry_run:
        sys.exit("没有找到 ffmpeg。请先安装（Windows：winget install Gyan.FFmpeg），重新打开终端后再运行。\n"
                 "也可以先加 --dry-run 看看会压缩哪些文件。")

    files = sorted(BGM_DIR.glob("*.mp3"))
    if not files:
        sys.exit(f"{BGM_DIR} 里没有 mp3 文件。")
    seconds = durations()

    total_before = total_after = 0
    print(f"目标码率：{args.bitrate} kbps{'（只预览，不改文件）' if args.dry_run else ''}\n")
    for path in files:
        backup = BACKUP_DIR / path.name
        # 已经压缩过：从备份的原文件重新压缩，避免二次压缩损失音质
        source = backup if backup.exists() else path
        size_before = path.stat().st_size
        rate = kbps(source, seconds.get(path.name))
        rate_text = f"{rate:.0f} kbps" if rate else "码率未知"

        if rate and rate <= args.bitrate + 8 and not args.force:
            print(f"  跳过 {path.name}：{size_before / 1e6:.2f} MB，{rate_text}（已经够小）")
            total_before += size_before
            total_after += size_before
            continue

        if args.dry_run:
            estimate = size_before * args.bitrate / rate if rate else size_before
            print(f"  会压缩 {path.name}：{size_before / 1e6:.2f} MB（{rate_text}）→ 约 {estimate / 1e6:.2f} MB")
            total_before += size_before
            total_after += estimate
            continue

        if not backup.exists():
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        temp = path.with_suffix(".tmp.mp3")
        if encode(ffmpeg, source, temp, args.bitrate):
            temp.replace(path)
            size_after = path.stat().st_size
            print(f"  已压缩 {path.name}：{size_before / 1e6:.2f} MB → {size_after / 1e6:.2f} MB")
        else:
            temp.unlink(missing_ok=True)
            size_after = size_before
            print(f"  失败 {path.name}：原文件没有改动")
        total_before += size_before
        total_after += size_after

    print(f"\n合计：{total_before / 1e6:.2f} MB → {total_after / 1e6:.2f} MB")
    if not args.dry_run:
        print(f"原文件备份在 {BACKUP_DIR.relative_to(ROOT)}（需要还原时复制回 static/audio/bgm/ 即可）")


if __name__ == "__main__":
    main()
