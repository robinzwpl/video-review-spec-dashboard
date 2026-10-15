# -*- coding: utf-8 -*-
"""
关键帧抽取（turbojpeg 加速；未安装时自动回落 PIL 保存）。

与品类无关：抽帧阈值取自 config/default.yaml 的 keyframes 段，
命令行显式给出时优先于配置。

用法（两种都支持）：
    python 03_keyframes.py <视频> <输出目录> [间隔]      # 位置参数，兼容旧调用
    python 03_keyframes.py --video <视频> --out-dir <目录>
"""
import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import av
from PIL import Image

from lib import config as cfgmod

# turbojpeg 是可选加速依赖：装了提速约 3 倍，没装则回落 PIL，
# 编码结果有像素级差异（不同编码器），但 OCR 结果不受实质影响
try:
    from turbojpeg import compress, SAMP, CS, PF
    TURBOJPEG_OK = True
except ImportError:
    TURBOJPEG_OK = False


def save_jpeg(img, path, quality=88):
    """保存 JPEG：优先 turbojpeg，失败或未安装则回落 PIL。"""
    if TURBOJPEG_OK:
        try:
            # turbojpeg 新版 API：subsamp 必传，颜色空间与像素格式需显式指定
            # 注意：枚举名是 Y420（不是 YUV420），参数名是 pixelformat（不是 pixel_format）
            buf = np.ascontiguousarray(img)
            jpg = compress(
                buf,
                quality=quality,
                subsamp=SAMP.Y420,
                colorspace=CS.RGB,
                pixelformat=PF.RGB,
            )
            with open(path, "wb") as fh:
                fh.write(jpg)
            return
        except Exception as e:
            print(f"  turbojpeg 编码失败，回落 PIL: {e}", flush=True)
    Image.fromarray(img).save(path, quality=quality)


def extract_keyframes(video_path, out_dir, interval=1.0, diff_threshold=12.0,
                      downsample=8, jpeg_quality=88, frames_dir="frames",
                      meta_name="keyframes.json", max_duration=None):
    """
    抽帧并按画面变化去重。

    固定间隔会漏掉只出现 1-2 秒的参数卡，所以按帧间差异自适应保留。

    :param max_duration: 只解码前 N 秒（调试/烟雾测试用），None 表示全片
    """
    frames_abs = os.path.join(out_dir, frames_dir)
    os.makedirs(frames_abs, exist_ok=True)

    container = av.open(video_path)
    video_stream = None
    for stream in container.streams:
        if stream.type == "video":
            video_stream = stream
            break
    if video_stream is None:
        print("错误：没有视频轨", file=sys.stderr)
        sys.exit(1)

    fps = float(video_stream.average_rate)
    W = video_stream.codec_context.width
    H = video_stream.codec_context.height
    print(f"视频流: {W}x{H} @ {fps:.2f} fps", flush=True)

    prev_gray = None
    kept = []
    total_read = 0
    skipped = 0
    last_kept_time = -999.0
    t0 = time.time()

    for frame in container.decode(video_stream):
        total_read += 1
        t = float(frame.pts * frame.time_base) if frame.pts is not None else 0.0

        if max_duration is not None and t > max_duration:
            break

        # 时间间隔控制：距上次保留帧至少 interval/2 秒
        if (t - last_kept_time) < (interval / 2.0):
            continue

        img = frame.to_ndarray(format="rgb24")

        # 转灰度并降采样，加速差异计算
        gray = (img[:, :, 0].astype(np.float32) * 0.299
                + img[:, :, 1].astype(np.float32) * 0.587
                + img[:, :, 2].astype(np.float32) * 0.114)
        small = gray[::downsample, ::downsample]

        if prev_gray is not None:
            diff = float(np.mean(np.abs(small - prev_gray)))
            if diff < diff_threshold:
                # 画面几乎没变，跳过（但不更新 last_kept_time，允许稍后再抓）
                skipped += 1
                prev_gray = small
                continue

        # 画面有变化，编码保存
        frame_name = f"f{t:07.2f}.jpg"
        frame_path = os.path.join(frames_abs, frame_name)
        try:
            save_jpeg(img, frame_path, quality=jpeg_quality)
        except Exception as e:
            print(f"  保存帧 {t:.2f}s 失败: {e}", flush=True)
            continue

        kept.append({
            "index": len(kept),
            "timestamp": round(t, 2),
            "frame_path": os.path.join(frames_dir, frame_name),
        })
        prev_gray = small
        last_kept_time = t

        if len(kept) % 100 == 0:
            print(f"  已读帧 {total_read}，保留 {len(kept)}，跳过 {skipped}，"
                  f"当前 {t:.0f}s，用时 {time.time()-t0:.0f}s", flush=True)

    container.close()

    print(f"抽帧完成: 读取 {total_read} 帧，保留 {len(kept)} 帧，"
          f"跳过 {skipped} 帧，用时 {time.time()-t0:.0f}s", flush=True)

    meta_path = os.path.join(out_dir, meta_name)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)
    print(f"关键帧清单: {meta_path}", flush=True)
    return kept


def main():
    ap = argparse.ArgumentParser(
        description="关键帧抽取（turbojpeg 加速，缺失时回落 PIL）")
    # 位置参数：兼容旧的 `python 03_keyframes.py <视频> <输出目录> [间隔]` 调用
    ap.add_argument("video_pos", nargs="?", default=None)
    ap.add_argument("out_dir_pos", nargs="?", default=None)
    ap.add_argument("interval_pos", nargs="?", default=None)
    # 显式参数：pipeline 与手工调用统一用这一套
    ap.add_argument("--video", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--interval", type=float, default=None)
    ap.add_argument("--diff-threshold", type=float, default=None)
    ap.add_argument("--jpeg-quality", type=int, default=None)
    ap.add_argument("--max-duration", type=float, default=None,
                    help="只解码前 N 秒（调试/烟雾测试用）")
    ap.add_argument("--preset", default=None,
                    help="可选：品类预设名，仅用于覆盖通用阈值")
    args = ap.parse_args()

    video = args.video or args.video_pos
    out_dir = args.out_dir or args.out_dir_pos or "output"
    if not video:
        ap.error("缺少视频路径：用 --video 或第一个位置参数给出")

    # 阈值来源优先级：命令行 > 预设 > 通用默认 > 代码内置
    cfg = (cfgmod.load_config(args.preset) if args.preset
           else cfgmod.load_base())
    kf = cfg.get("keyframes", {})
    out = cfg.get("output", {})
    interval = args.interval or float(args.interval_pos or 0) or \
        kf.get("interval", 1.0)
    diff_threshold = args.diff_threshold or kf.get("diff_threshold", 12.0)
    jpeg_quality = args.jpeg_quality or kf.get("jpeg_quality", 88)

    print("=" * 60, flush=True)
    print("关键帧抽取", flush=True)
    print("=" * 60, flush=True)
    print(f"视频: {video}", flush=True)
    print(f"抽帧间隔: {interval}s", flush=True)
    if not TURBOJPEG_OK:
        print("提示: 未安装 PyTurboJPEG，回落 PIL 保存（速度略慢，结果可用）",
              flush=True)

    os.makedirs(out_dir, exist_ok=True)
    extract_keyframes(
        video, out_dir,
        interval=interval,
        diff_threshold=diff_threshold,
        downsample=kf.get("downsample", 8),
        jpeg_quality=jpeg_quality,
        frames_dir=out.get("frames_dir", "frames"),
        meta_name=out.get("keyframes_json", "keyframes.json"),
        max_duration=args.max_duration,
    )


if __name__ == "__main__":
    main()
