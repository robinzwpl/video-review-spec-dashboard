# -*- coding: utf-8 -*-
"""
音频转写（绕过 av 版本冲突）。（流水线第 2 阶段，可选）

背景：faster-whisper 调用 av.open(..., metadata_errors="ignore")，
      而 av 19.0 起已移除该参数（本机实测为 18.1.0，该参数仍在，
      但为跨版本安全，本脚本始终走绕过路径）。
解法：本地已有 16kHz 单声道 WAV（由 01 提取），
      自行读成 float32 numpy 数组，绕过 faster_whisper.audio.decode_audio。

本阶段是可选的：没有 faster-whisper 或没给本地模型目录时，
打印警告并以退出码 0 结束（不阻塞流水线其余阶段）。

用法：
    python 02_transcribe.py --wav <audio_16k.wav> --out-dir <目录> \
        --model-dir <本地模型目录>
"""
import os
import sys
import json
import time
import wave
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from lib import config as cfgmod


def read_wav_as_float32(path):
    """读取 16bit PCM WAV，返回 float32 归一化数组（whisper 期望 -1.0 ~ 1.0）。"""
    with wave.open(path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        print(f"  WAV: {n_channels}ch {sampwidth*8}bit {framerate}Hz "
              f"{n_frames} 帧 ({n_frames/framerate:.1f}s)", flush=True)

        if sampwidth != 2:
            raise ValueError(f"期望 16bit，实际 {sampwidth*8}bit")
        if n_channels != 1:
            raise ValueError(f"期望单声道，实际 {n_channels} 声道")

        raw = wf.readframes(n_frames)

    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return arr


def main():
    ap = argparse.ArgumentParser(description="音频转写（可选阶段）")
    ap.add_argument("--wav", required=True, help="16kHz 单声道 WAV 路径")
    ap.add_argument("--out-dir", default="output")
    ap.add_argument("--model-dir", required=True,
                    help="faster-whisper 本地模型目录（不给则无法转写）")
    ap.add_argument("--preset", default=None,
                    help="可选：品类预设名，仅用于覆盖输出文件名")
    args = ap.parse_args()

    print("=" * 60, flush=True)
    print("音频转写（绕过 av 冲突版）", flush=True)
    print("=" * 60, flush=True)
    print(f"音频: {args.wav}", flush=True)
    print(f"模型: {args.model_dir}", flush=True)
    print(flush=True)

    if not os.path.exists(args.wav):
        print(f"错误：找不到音频文件 {args.wav}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.model_dir):
        print(f"错误：找不到模型目录 {args.model_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("警告：未安装 faster_whisper，跳过音频转写。", flush=True)
        print("      本阶段是可选的——不影响抽帧 / OCR / 解析 / 看板全套产物。",
              flush=True)
        print("      需要时安装：pip install faster-whisper", flush=True)
        sys.exit(0)  # 退出码 0：让流水线继续跑后面的阶段

    audio = read_wav_as_float32(args.wav)

    t0 = time.time()
    model = WhisperModel(args.model_dir, device="cpu", compute_type="int8")
    print(f"模型加载完成，耗时 {time.time()-t0:.1f}s", flush=True)
    print("开始转写...", flush=True)

    t0 = time.time()
    segments, info = model.transcribe(
        audio,                  # 直接传 numpy 数组，绕过 decode_audio
        language="zh",
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200),
        condition_on_previous_text=False,
    )

    print(f"语言: {info.language}  音频时长: {info.duration:.1f}s", flush=True)

    cfg = (cfgmod.load_config(args.preset) if args.preset
           else cfgmod.load_base())
    out = cfg.get("output", {})
    os.makedirs(args.out_dir, exist_ok=True)
    json_path = os.path.join(
        args.out_dir, out.get("transcript_json", "transcript.json"))
    txt_path = os.path.join(
        args.out_dir, out.get("transcript_txt", "transcript.txt"))

    result = {
        "language": info.language,
        "duration": info.duration,
        "model": args.model_dir,
        "segments": [],
    }
    lines = []
    n = 0

    for seg in segments:
        result["segments"].append({
            "id": seg.id,
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        })
        mm, ss = divmod(int(seg.start), 60)
        lines.append(f"[{mm:02d}:{ss:02d}] {seg.text.strip()}")
        n += 1

        if n % 40 == 0:
            elapsed = time.time() - t0
            pct = seg.end / info.duration * 100
            print(f"  进度 {pct:.0f}% ({seg.end:.0f}s/{info.duration:.0f}s) "
                  f"用时 {elapsed:.0f}s", flush=True)
            # 增量保存，防止意外中断丢数据
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"转写完成: {n} 段，耗时 {time.time()-t0:.0f}s", flush=True)
    print(f"输出: {json_path}", flush=True)
    print(f"输出: {txt_path}", flush=True)


if __name__ == "__main__":
    main()
