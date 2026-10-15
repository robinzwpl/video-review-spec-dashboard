# -*- coding: utf-8 -*-
"""
从视频中提取音频并转写为带时间戳的文本。
使用 PyAV 解码 mp4（无需 ffmpeg），faster-whisper 做语音识别。
"""
import os
import sys
import json
import time

# 输入视频路径通过命令行参数传入
VIDEO_PATH = sys.argv[1]
OUTPUT_DIR = sys.argv[2]
MODEL_SIZE = sys.argv[3] if len(sys.argv) > 3 else "small"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==================== 第一步：提取音频 ====================
def extract_audio(video_path, wav_path):
    """用 PyAV 解码 mp4 音频轨，重采样为 16kHz 单声道 WAV。"""
    import av

    print("[1/3] 正在打开视频并提取音频...", flush=True)
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


# ==================== 第二步：语音识别 ====================
def transcribe(wav_path, model_size, output_dir):
    """用 faster-whisper 转写，保留时间戳。"""
    from faster_whisper import WhisperModel

    print(f"[2/3] 正在加载模型: {model_size} ...", flush=True)
    t0 = time.time()
    # device="cpu", compute_type="int8" —— CPU 上最稳的组合
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    print(f"  模型加载完成，耗时 {time.time()-t0:.1f} 秒", flush=True)

    print("[3/3] 正在转写（首次会下载模型，请耐心等待）...", flush=True)
    t0 = time.time()
    segments, info = model.transcribe(
        wav_path,
        language="zh",           # 强制中文，避免误判
        task="transcribe",       # 不是翻译
        beam_size=5,             # beam search，提高准确率
        vad_filter=True,         # 语音活动检测，跳过静音段
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        ),
        condition_on_previous_text=False,  # 减少重复幻觉
    )

    print(f"  语言: {info.language} 概率 {info.language_probability:.2f}", flush=True)
    print(f"  音频时长: {info.duration:.1f} 秒", flush=True)

    result = {
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "model_size": model_size,
        "segments": [],
    }

    # 实时写出，便于中途查看进度
    json_path = os.path.join(output_dir, "transcript.json")
    txt_path = os.path.join(output_dir, "transcript.txt")
    txt_lines = []
    seg_count = 0

    for seg in segments:
        seg_data = {
            "id": seg.id,
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "no_speech_prob": round(seg.no_speech_prob, 3) if seg.no_speech_prob else None,
            "avg_logprob": round(seg.avg_logprob, 3) if seg.avg_logprob else None,
        }
        result["segments"].append(seg_data)

        # 时间戳格式：[mm:ss] 文本
        m, s = divmod(int(seg.start), 60)
        line = f"[{m:02d}:{s:02d}] {seg.text.strip()}"
        txt_lines.append(line)

        seg_count += 1
        if seg_count % 30 == 0:
            elapsed = time.time() - t0
            progress = seg.end / info.duration * 100
            print(f"  已转写 {progress:.0f}% ({seg.end:.0f}s/{info.duration:.0f}s) "
                  f"用时 {elapsed:.0f}s", flush=True)
            # 增量保存，防止意外中断丢数据
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(txt_lines))

    # 最终保存
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(txt_lines))

    print(f"  转写完成: {seg_count} 个片段，耗时 {time.time()-t0:.0f} 秒", flush=True)
    print(f"  输出: {json_path}", flush=True)
    print(f"  输出: {txt_path}", flush=True)
    return result


def main():
    print("=" * 60, flush=True)
    print("视频音频转写工具", flush=True)
    print("=" * 60, flush=True)
    print(f"视频: {VIDEO_PATH}", flush=True)
    print(f"模型: {MODEL_SIZE}", flush=True)
    print(flush=True)

    wav_path = os.path.join(OUTPUT_DIR, "audio_16k.wav")

    if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
        print("检测到已有音频文件，跳过提取步骤", flush=True)
    else:
        extract_audio(VIDEO_PATH, wav_path)

    print(flush=True)
    transcribe(wav_path, MODEL_SIZE, OUTPUT_DIR)

    print(flush=True)
    print("=" * 60, flush=True)
    print("全部完成", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
