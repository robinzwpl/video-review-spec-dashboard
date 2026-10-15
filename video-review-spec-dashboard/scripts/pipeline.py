# -*- coding: utf-8 -*-
"""
抽帧 + OCR 一体化入口（不经过 shell 传参，避免中文路径与 ! 号被吃掉）。

用法：python run_pipeline.py <输出目录> [抽帧间隔]
"""
import os
import sys
import glob
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import importlib


def find_video():
    """
    递归查找视频文件。

    查找顺序：项目目录内优先，找不到再回退到 C 盘 Downloads。
    项目根由脚本自身位置推算（scripts/ 的上级目录），
    因此整个项目目录移动到任何位置后本脚本仍可正常工作。
    """
    project_root = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))

    # 1) 项目目录内（跳过 output，避免误取中间产物）
    for ext in ("mp4", "mkv", "mov"):
        hits = glob.glob(os.path.join(project_root, "**", f"*.{ext}"),
                         recursive=True)
        hits = [h for h in hits if os.sep + "output" + os.sep not in h]
        if hits:
            return hits[0]

    # 2) 回退：原工作路径下的 Downloads
    for pat in (r"C:/Users/DELL/Downloads/**/*.mp4",
                r"C:/Users/DELL/Downloads/**/*.mkv",
                r"C:/Users/DELL/Downloads/**/*.mov"):
        hits = glob.glob(pat, recursive=True)
        if hits:
            return hits[0]

    return None


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "output"
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0

    video = find_video()
    if not video:
        print("错误：未找到视频文件", file=sys.stderr)
        sys.exit(1)

    print("=" * 60, flush=True)
    print("抽帧 + OCR 流水线", flush=True)
    print("=" * 60, flush=True)
    print(f"视频: {video}", flush=True)
    print(f"输出: {out_dir}", flush=True)
    print(f"抽帧间隔: {interval}s", flush=True)
    print(flush=True)

    os.makedirs(out_dir, exist_ok=True)

    # 导入抽帧模块
    mod = importlib.import_module("02a_extract_fast")
    frames = mod.extract_keyframes(video, out_dir, interval=interval)
    print(flush=True)

    # 导入 OCR 模块
    ocr_mod = importlib.import_module("02b_ocr_enhanced")
    results = ocr_mod.run_ocr(frames, out_dir, do_enhance=True)

    print(flush=True)
    print("=" * 60, flush=True)
    print("流水线完成", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
