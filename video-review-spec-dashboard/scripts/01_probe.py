# -*- coding: utf-8 -*-
"""
视频探测 + 音频提取（流水线第 1 阶段）。

只做两件事：
  1. 探测视频元信息 -> video_info.json（分辨率 / 时长 / 帧率 / 编码 / 音频轨）
  2. 提取 16kHz 单声道 WAV -> audio_16k.wav（供 02 转写消费）

不做语音识别 —— 那是 02 的职责。早期版本把转写也塞在本脚本里，
导致与 02 功能重复，且用的是会触发 av 版本冲突的调用路径，已删除。
用 PyAV 解码，不需要额外的 ffmpeg。

用法：
    python 01_probe.py --video <视频> --out-dir <目录>
    python 01_probe.py --video <视频> --out-dir <目录> --skip-audio
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config as cfgmod


def probe_video(video_path):
    """用 PyAV 读取视频元信息。"""
    import av

    info = {"path": os.path.abspath(video_path)}
    with av.open(video_path) as container:
        if container.duration is not None:
            info["duration_sec"] = round(container.duration / 1_000_000, 2)
        else:
            info["duration_sec"] = None

        for stream in container.streams:
            if stream.type == "video":
                cc = stream.codec_context
                info["width"] = cc.width
                info["height"] = cc.height
                info["video_codec"] = cc.name
                rate = stream.average_rate
                info["fps"] = round(float(rate), 3) if rate else None
                # 帧数是估算值：精确值只能靠全量解码得到，代价太高
                if info.get("duration_sec") and info.get("fps"):
                    info["estimated_frames"] = int(
                        info["duration_sec"] * info["fps"])
            elif stream.type == "audio":
                cc = stream.codec_context
                info["has_audio"] = True
                info["audio_codec"] = cc.name
                info["audio_sample_rate"] = cc.sample_rate
                info["audio_channels"] = cc.channels

        info.setdefault("has_audio", False)
    return info


def extract_audio(video_path, wav_path):
    """用 PyAV 解码 mp4 音频轨，重采样为 16kHz 单声道 WAV。"""
    import av

    print("正在打开视频并提取音频...", flush=True)
    container = av.open(video_path)

    # 找到音频流
    audio_stream = None
    for stream in container.streams:
        if stream.type == "audio":
            audio_stream = stream
            break

    if audio_stream is None:
        print("错误：视频中没有音频轨", file=sys.stderr)
        sys.exit(1)

    print(f"  音频流编码: {audio_stream.codec_context.name}", flush=True)
    print(f"  原始采样率: {audio_stream.codec_context.sample_rate} Hz", flush=True)
    print(f"  声道数: {audio_stream.codec_context.channels}", flush=True)

    # 重采样为单声道 16kHz（whisper 要求）
    resampler = av.audio.resampler.AudioResampler(
        format="s16",        # 16位有符号整数
        layout="mono",       # 单声道
        rate=16000,          # whisper 要求的采样率
    )

    total_samples = 0
    chunk_count = 0
    with open(wav_path, "wb") as wav_file:
        # 写 WAV 文件头（占位，稍后回填正确长度）
        wav_file.write(b"RIFF")
        wav_file.write((0).to_bytes(4, "little"))  # 文件大小，稍后修正
        wav_file.write(b"WAVE")
        wav_file.write(b"fmt ")
        wav_file.write((16).to_bytes(4, "little"))
        wav_file.write((1).to_bytes(2, "little"))   # PCM 格式
        wav_file.write((1).to_bytes(2, "little"))   # 单声道
        wav_file.write((16000).to_bytes(4, "little"))
        wav_file.write((16000 * 2).to_bytes(4, "little"))  # 字节率
        wav_file.write((2).to_bytes(2, "little"))   # 块对齐
        wav_file.write((16).to_bytes(2, "little"))  # 位深
        wav_file.write(b"data")
        wav_file.write((0).to_bytes(4, "little"))  # 数据长度，稍后修正

        for packet in container.demux(audio_stream):
            for frame in packet.decode():
                for resampled_frame in resampler.resample(frame):
                    arr = resampled_frame.to_ndarray().reshape(-1)
                    wav_file.write(arr.tobytes())
                    total_samples += len(arr)
                    chunk_count += 1
                    if chunk_count % 100 == 0:
                        print(f"  已处理 {total_samples/16000:.1f} 秒", flush=True)

    container.close()

    # 回填 WAV 头部的长度字段
    data_size = total_samples * 2  # 16位 = 2字节
    with open(wav_path, "r+b") as wav_file:
        wav_file.seek(4)
        wav_file.write((36 + data_size).to_bytes(4, "little"))
        wav_file.seek(40)
        wav_file.write(data_size.to_bytes(4, "little"))

    duration = total_samples / 16000
    print(f"  音频提取完成: {duration:.1f} 秒 ({duration/60:.1f} 分钟)", flush=True)
    print(f"  输出文件: {wav_path}", flush=True)
    return duration


def main():
    ap = argparse.ArgumentParser(description="视频探测 + 16kHz 音频提取")
    ap.add_argument("--video", required=True, help="视频文件路径")
    ap.add_argument("--out-dir", default="output")
    ap.add_argument("--skip-audio", action="store_true",
                    help="只探测，不提取音频")
    ap.add_argument("--preset", default=None,
                    help="可选：品类预设名，仅用于覆盖输出文件名")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        print(f"错误：视频不存在: {args.video}", file=sys.stderr)
        sys.exit(1)

    cfg = (cfgmod.load_config(args.preset) if args.preset
           else cfgmod.load_base())
    out = cfg.get("output", {})

    print("=" * 60, flush=True)
    print("视频探测", flush=True)
    print("=" * 60, flush=True)
    print(f"视频: {args.video}", flush=True)

    os.makedirs(args.out_dir, exist_ok=True)

    info = probe_video(args.video)
    print(f"  分辨率: {info.get('width')}x{info.get('height')}", flush=True)
    print(f"  时长: {info.get('duration_sec')}s  帧率: {info.get('fps')} fps",
          flush=True)
    print(f"  视频编码: {info.get('video_codec')}", flush=True)
    print(f"  音频轨: {'有' if info.get('has_audio') else '无'} "
          f"{info.get('audio_codec') or ''}", flush=True)

    info_path = os.path.join(
        args.out_dir, out.get("video_info_json", "video_info.json"))
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"  视频信息: {info_path}", flush=True)

    if args.skip_audio:
        print("已跳过音频提取（--skip-audio）", flush=True)
        return

    if not info.get("has_audio"):
        print("视频没有音频轨，跳过音频提取", flush=True)
        return

    wav_path = os.path.join(args.out_dir, out.get("audio_wav", "audio_16k.wav"))
    print(flush=True)
    if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
        print("检测到已有音频文件，跳过提取步骤", flush=True)
    else:
        extract_audio(args.video, wav_path)


if __name__ == "__main__":
    main()
