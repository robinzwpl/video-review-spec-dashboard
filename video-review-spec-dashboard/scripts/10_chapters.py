# -*- coding: utf-8 -*-
"""
章节定位：音频线索 + 画面线索交叉验证。（流水线第 10 阶段，可选）

音频线索：转写中的「第N档」「X元档」「X元到Y元」等表述
画面线索：OCR 抓到的章节卡标题（「第一档」「3000元档小结」等）

两者交叉可显著提高定位可靠性——单一通道容易漏。
没有转写时自动降级为「仅画面通道」，仍能出章节。

词表与时间窗取自配置 chapters 段（通用默认在 config/default.yaml，
品类专属话术可在 preset 里覆盖）。

用法：
    python 10_chapters.py --out-dir output [--preset tv75_science]
"""
import os
import re
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config as cfgmod


def norm_simplified(s):
    """繁体转简体（只处理常见字，避免引入依赖）。"""
    table = {
        "檔": "档", "開": "开", "說": "说", "們": "们", "這": "这",
        "個": "个", "來": "来", "時": "时", "會": "会", "對": "对",
        "現": "现", "實": "实", "點": "点", "線": "线", "價": "价",
        "買": "买", "賣": "卖", "顯": "显", "示": "示", "沒": "没",
        "麼": "么", "後": "后", "動": "动", "靜": "静", "選": "选",
        "區": "区", "檔位": "档位", "萬": "万", "與": "与", "為": "为",
        "價位": "价位", "區間": "区间", "萬左右": "万左右",
    }
    for k, v in table.items():
        s = s.replace(k, v)
    return s


def find_audio_markers(transcript, patterns):
    """从转写中找档位标记。每个片段只取第一个命中的词表项。"""
    markers = []
    for s in transcript["segments"]:
        txt = norm_simplified(s["text"])
        for item in patterns:
            pat, kind = item.get("pattern"), item.get("kind")
            if not pat:
                continue
            m = re.search(pat, txt)
            if m:
                markers.append({
                    "timestamp": s["start"],
                    "kind": kind,
                    "matched": m.group(0),
                    "context": txt[:60],
                })
                break
    return markers


def find_visual_markers(ocr_data, patterns):
    """从 OCR 中找章节卡。每段文本只取第一个命中的词表项。"""
    markers = []
    for fr in ocr_data:
        for t in fr["texts"]:
            txt = t["text"]
            for item in patterns:
                pat, kind = item.get("pattern"), item.get("kind")
                if not pat:
                    continue
                if re.search(pat, txt):
                    markers.append({
                        "timestamp": fr["timestamp"],
                        "kind": kind,
                        "matched": txt,
                        "score": t["score"],
                    })
                    break
    return markers


def build_chapters(audio_markers, visual_markers, total_duration,
                   audio_dedupe_sec=3, min_gap_sec=20,
                   fallback_score=0.5, name_max_len=30):
    """合并两类线索，构建章节。"""
    tier_starts = {}

    for m in visual_markers:
        if m["kind"] == "档位卡":
            t = m["timestamp"]
            if t not in tier_starts or m["score"] > tier_starts[t]["score"]:
                tier_starts[t] = {"timestamp": t, "source": "画面OCR",
                                  "text": m["matched"], "score": m["score"]}

    for m in audio_markers:
        if m["kind"] in ("档位序号", "档位价格"):
            t = m["timestamp"]
            # 音频线索作为补充（时间窗内已有画面线索则跳过）
            if any(abs(t - ts) < audio_dedupe_sec for ts in tier_starts):
                continue
            tier_starts[t] = {"timestamp": t, "source": "音频转写",
                              "text": m["context"], "score": fallback_score}

    # 排序并构建章节区间
    points = sorted(tier_starts.values(), key=lambda x: x["timestamp"])

    # 过滤过近的点（min_gap_sec 内多个标记只保留一个）
    filtered = []
    for p in points:
        if filtered and p["timestamp"] - filtered[-1]["timestamp"] < min_gap_sec:
            # 保留画面来源的（更可靠）
            if p["source"] == "画面OCR" and filtered[-1]["source"] != "画面OCR":
                filtered[-1] = p
            continue
        filtered.append(p)

    chapters = []
    for i, p in enumerate(filtered):
        start = p["timestamp"]
        end = filtered[i + 1]["timestamp"] if i + 1 < len(filtered) else total_duration
        chapters.append({
            "index": i + 1,
            "name": p["text"][:name_max_len],
            "start": round(start, 1),
            "end": round(end, 1),
            "source": p["source"],
        })

    return chapters


def main():
    ap = argparse.ArgumentParser(description="章节定位（可选阶段）")
    ap.add_argument("out_dir_pos", nargs="?", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--preset", default=None,
                    help="可选：品类预设名，用于覆盖章节词表")
    ap.add_argument("--transcript", default=None, help="transcript.json 路径")
    ap.add_argument("--ocr", default=None, help="frames_ocr.json 路径")
    args = ap.parse_args()

    out_dir = args.out_dir or args.out_dir_pos or "output"
    cfg = (cfgmod.load_config(args.preset) if args.preset
           else cfgmod.load_base())
    out = cfg.get("output", {})
    ch = cfg.get("chapters", {})

    transcript_path = args.transcript or os.path.join(
        out_dir, out.get("transcript_json", "transcript.json"))
    ocr_path = args.ocr or os.path.join(
        out_dir, out.get("frames_ocr_json", "frames_ocr.json"))

    transcript = None
    if os.path.exists(transcript_path):
        with open(transcript_path, encoding="utf-8") as f:
            transcript = json.load(f)
    else:
        print(f"未找到转写 {transcript_path}，降级为仅画面通道", flush=True)

    if not os.path.exists(ocr_path):
        print(f"错误：找不到 OCR 结果 {ocr_path}", file=sys.stderr)
        sys.exit(1)
    with open(ocr_path, encoding="utf-8") as f:
        ocr_data = json.load(f)

    print(f"转写 {len(transcript['segments']) if transcript else 0} 段，"
          f"OCR {len(ocr_data)} 帧", flush=True)

    audio_markers = (find_audio_markers(transcript, ch.get("audio_patterns", []))
                     if transcript else [])
    visual_markers = find_visual_markers(ocr_data, ch.get("visual_patterns", []))
    print(f"音频线索 {len(audio_markers)} 条", flush=True)
    print(f"画面线索 {len(visual_markers)} 条", flush=True)

    # 总时长优先取转写，没有则用最后一帧 OCR 时间兜底
    total_duration = 0
    if transcript:
        total_duration = transcript.get("duration", 0)
    if not total_duration and ocr_data:
        total_duration = max(fr["timestamp"] for fr in ocr_data) + 60

    chapters = build_chapters(
        audio_markers, visual_markers, total_duration,
        audio_dedupe_sec=ch.get("audio_dedupe_sec", 3),
        min_gap_sec=ch.get("min_gap_sec", 20),
        fallback_score=ch.get("fallback_score", 0.5),
        name_max_len=ch.get("name_max_len", 30),
    )
    print(f"构建章节 {len(chapters)} 个", flush=True)

    out_path = os.path.join(
        out_dir, out.get("chapters_json", "chapters.json"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(chapters, f, ensure_ascii=False, indent=2)
    print(f"输出: {out_path}", flush=True)

    print(flush=True)
    print("=" * 70, flush=True)
    print("章节结构", flush=True)
    print("=" * 70, flush=True)
    for c in chapters:
        dur = c["end"] - c["start"]
        print(f"  [{c['index']}] {c['start']:7.1f}s - {c['end']:7.1f}s "
              f"({dur:5.1f}s) {c['source']:8s} {c['name']}", flush=True)


if __name__ == "__main__":
    main()
