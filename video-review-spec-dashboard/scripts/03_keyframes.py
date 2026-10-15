# -*- coding: utf-8 -*-
"""
关键帧抽取（turbojpeg 加速版）。

与 02_ocr.py 的抽帧逻辑相同，但改用 turbojpeg 编码，显著提速。
"""
import os
import sys
import json
import time

import numpy as np
import av
from turbojpeg import compress, SAMP, CS, PF


def extract_keyframes(video_path, out_dir, interval=1.0, diff_threshold=12.0):
    """
    抽帧并按画面变化去重。
    固定间隔会漏掉只出现 1-2 秒的参数卡，所以按帧间差异自适应保留。
    """
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

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

        # 时间间隔控制：距上次保留帧至少 interval/2 秒
        if (t - last_kept_time) < (interval / 2.0):
            continue

        img = frame.to_ndarray(format="rgb24")

        # 转灰度并降采样，加速差异计算
        gray = (img[:, :, 0].astype(np.float32) * 0.299
                + img[:, :, 1].astype(np.float32) * 0.587
                + img[:, :, 2].astype(np.float32) * 0.114)
        small = gray[::8, ::8]

        if prev_gray is not None:
            diff = float(np.mean(np.abs(small - prev_gray)))
            if diff < diff_threshold:
                # 画面几乎没变，跳过（但不更新 last_kept_time，允许稍后再抓）
                skipped += 1
                prev_gray = small
                continue

        # 画面有变化，用 turbojpeg 编码保存
        frame_name = f"f{t:07.2f}.jpg"
        frame_path = os.path.join(frames_dir, frame_name)
        try:
            # turbojpeg 新版 API：subsamp 必传，颜色空间与像素格式需显式指定
            # 注意：枚举名是 Y420（不是 YUV420），参数名是 pixelformat（不是 pixel_format）
            buf = np.ascontiguousarray(img)
            jpg = compress(
                buf,
                quality=88,
                subsamp=SAMP.Y420,
                colorspace=CS.RGB,
                pixelformat=PF.RGB,
            )
            with open(frame_path, "wb") as fh:
                fh.write(jpg)
        except Exception as e:
            print(f"  保存帧 {t:.2f}s 失败: {e}", flush=True)
            continue

        kept.append({
            "index": len(kept),
            "timestamp": round(t, 2),
            "frame_path": os.path.join("frames", frame_name),
        })
        prev_gray = small
        last_kept_time = t

        if len(kept) % 100 == 0:
            print(f"  已读帧 {total_read}，保留 {len(kept)}，跳过 {skipped}，"
                  f"当前 {t:.0f}s，用时 {time.time()-t0:.0f}s", flush=True)

    container.close()

    print(f"抽帧完成: 读取 {total_read} 帧，保留 {len(kept)} 帧，"
          f"跳过 {skipped} 帧，用时 {time.time()-t0:.0f}s", flush=True)

    meta_path = os.path.join(out_dir, "keyframes.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)
    print(f"关键帧清单: {meta_path}", flush=True)
    return kept


def main():
    video_path = sys.argv[1]
    out_dir = sys.argv[2]
    interval = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    print("=" * 60, flush=True)
    print("关键帧抽取（turbojpeg 加速）", flush=True)
    print("=" * 60, flush=True)
    print(f"视频: {video_path}", flush=True)
    print(f"抽帧间隔: {interval}s", flush=True)
    print(flush=True)

    os.makedirs(out_dir, exist_ok=True)
    extract_keyframes(video_path, out_dir, interval=interval)


if __name__ == "__main__":
    main()
