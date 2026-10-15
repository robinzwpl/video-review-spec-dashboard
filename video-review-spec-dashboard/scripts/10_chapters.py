# -*- coding: utf-8 -*-
"""
章节定位：音频线索 + 画面线索交叉验证。

音频线索：转写中的"第N档"、"X元档"、"X元到Y元"等表述
画面线索：OCR 抓到的章节卡标题（"第一档"、"3000元档小结"等）

两者交叉可显著提高定位可靠性—— 单一通道容易漏。
"""
import os
import re
import sys
import json


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


def find_audio_markers(transcript):
    """从转写中找档位标记。"""
    markers = []
    segs = transcript["segments"]

    patterns = [
        # 明确档位
        (r"第\s*([一二三四五六七八九十\d])\s*档", "档位序号"),
        (r"(\d{3,5})\s*(?:块钱|块|元)?\s*(?:档|这一档)", "档位价格"),
        (r"(\d{3,5})\s*到\s*(\d{3,5})", "价格区间"),
        (r"(\d{3,5})\s*档", "档位价格"),
        (r"小结|总结|收尾|总结一下", "段落标记"),
    ]

    for s in segs:
        txt = norm_simplified(s["text"])
        for pat, kind in patterns:
            for m in re.finditer(pat, txt):
                markers.append({
                    "timestamp": s["start"],
                    "kind": kind,
                    "matched": m.group(0),
                    "context": txt[:60],
                })
                break
    return markers


def find_visual_markers(ocr_data):
    """从 OCR 中找章节卡。"""
    markers = []
    for fr in ocr_data:
        for t in fr["texts"]:
            txt = t["text"]
            if re.search(r"第[一二三四五六七八九十]\s*档", txt):
                markers.append({
                    "timestamp": fr["timestamp"],
                    "kind": "档位卡",
                    "matched": txt,
                    "score": t["score"],
                })
            elif re.search(r"\d{3,5}\s*元档", txt):
                markers.append({
                    "timestamp": fr["timestamp"],
                    "kind": "档位卡",
                    "matched": txt,
                    "score": t["score"],
                })
            elif re.search(r"\d{3,5}\s*[-—~至到]\s*\d{3,5}\s*元", txt):
                markers.append({
                    "timestamp": fr["timestamp"],
                    "kind": "价格区间",
                    "matched": txt,
                    "score": t["score"],
                })
    return markers


def build_chapters(audio_markers, visual_markers, total_duration):
    """合并两类线索，构建章节。"""
    # 收集所有档位起点
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
            # 音频线索作为补充（±3s 内已有画面线索则跳过）
            if any(abs(t - ts) < 3 for ts in tier_starts):
                continue
            tier_starts[t] = {"timestamp": t, "source": "音频转写",
                              "text": m["context"], "score": 0.5}

    # 排序并构建章节区间
    points = sorted(tier_starts.values(), key=lambda x: x["timestamp"])

    # 过滤过近的点（20s 内多个标记只保留一个）
    filtered = []
    for p in points:
        if filtered and p["timestamp"] - filtered[-1]["timestamp"] < 20:
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
            "name": p["text"][:30],
            "start": round(start, 1),
            "end": round(end, 1),
            "source": p["source"],
        })

    return chapters


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "output"

    with open(os.path.join(out_dir, "transcript.json"), encoding="utf-8") as f:
        transcript = json.load(f)
    with open(os.path.join(out_dir, "frames_ocr.json"), encoding="utf-8") as f:
        ocr_data = json.load(f)

    print(f"转写 {len(transcript['segments'])} 段，OCR {len(ocr_data)} 帧", flush=True)

    audio_markers = find_audio_markers(transcript)
    visual_markers = find_visual_markers(ocr_data)
    print(f"音频线索 {len(audio_markers)} 条", flush=True)
    print(f"画面线索 {len(visual_markers)} 条", flush=True)

    chapters = build_chapters(audio_markers, visual_markers, transcript["duration"])
    print(f"构建章节 {len(chapters)} 个", flush=True)

    out_path = os.path.join(out_dir, "chapters.json")
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
