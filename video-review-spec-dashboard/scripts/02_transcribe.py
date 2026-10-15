# -*- coding: utf-8 -*-
"""
音频转写（绕过 av 版本冲突）。

背景：faster-whisper 1.2.1 调用 av.open(..., metadata_errors="ignore")，
      而 av 19.0.0 已移除该参数，且 av 14.x 在 Python 3.13 无预编译 wheel。
解法：本地已有 16kHz 单声道 WAV（由 PyAV 19 提取），
      自行读成 float32 numpy 数组，绕过 faster_whisper.audio.decode_audio。

用法：python 01c_transcribe_nofast.py <wav> <输出目录> <模型目录>
"""
import os
import sys
import json
import time
import wave

import numpy as np


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
    wav_path = sys.argv[1]
    out_dir = sys.argv[2]
    model_dir = sys.argv[3]

    print("=" * 60, flush=True)
    print("音频转写（绕过 av 冲突版）", flush=True)
    print("=" * 60, flush=True)
    print(f"音频: {wav_path}", flush=True)
    print(f"模型: {model_dir}", flush=True)
    print(flush=True)

    print("读取音频数据...", flush=True)
    t0 = time.time()
    audio = read_wav_as_float32(wav_path)
    print(f"  音频加载完成，耗时 {time.time()-t0:.1f}s", flush=True)
    print(flush=True)

    from faster_whisper import WhisperModel

    t0 = time.time()
    model = WhisperModel(model_dir, device="cpu", compute_type="int8")
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

    result = {
        "language": info.language,
        "duration": info.duration,
        "model": model_dir,
        "segments": [],
    }

    json_path = os.path.join(out_dir, "transcript.json")
    txt_path = os.path.join(out_dir, "transcript.txt")
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
