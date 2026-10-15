# -*- coding: utf-8 -*-
"""
版式探查：在还没有 preset 的时候，先摸清这个视频的参数卡长什么样。

它会统计跨帧重复出现的短文本（这些通常就是字段标签），给出它们的平均坐标，
再给出文本框的纵向分布，用来确定标题行阈值与底部栏边界。
照着报告填 config/presets/_template.yaml 即可，不用手动一帧帧量坐标。

用法：
    python scripts/05_discover.py --input output/frames_ocr.json --output output/layout_report.md
"""
import os
import re
import sys
import json
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from lib import layout

# 候选标签的最大长度：字段标签通常很短
LABEL_MAX_LEN = 8
# 至少在这么多帧里出现过，才认为是稳定的字段标签
MIN_FRAMES = 3
# 纵向分布直方图的区间高度（像素）
BIN_HEIGHT = 50


def collect(ocr_data):
    """统计每个文本的出现次数与坐标。"""
    stat = defaultdict(lambda: {"count": 0, "y": [], "x": [], "frames": 0})
    frame_seen = defaultdict(set)

    for fr in ocr_data:
        for t in fr.get("texts", []):
            text = t.get("text", "").strip()
            if not text:
                continue
            norm = re.sub(r"[:：\s,，/、]+$", "", text)
            if not norm:
                continue
            s = stat[norm]
            s["count"] += 1
            s["y"].append(layout.y_center(t["box"]))
            s["x"].append(layout.x_left(t["box"]))
            frame_seen[norm].add(fr.get("timestamp"))

    for k, v in frame_seen.items():
        stat[k]["frames"] = len(v)
    return stat


def region_stats(ocr_data):
    """统计各 region 的文本框数量与平均坐标。"""
    stat = defaultdict(lambda: {"count": 0, "y": [], "x": []})
    for fr in ocr_data:
        for t in fr.get("texts", []):
            rg = t.get("region", "") or "(未标注)"
            s = stat[rg]
            s["count"] += 1
            s["y"].append(layout.y_center(t["box"]))
            s["x"].append(layout.x_left(t["box"]))
    return stat


def avg(nums):
    return sum(nums) / len(nums) if nums else 0


def build_report(ocr_data):
    stat = collect(ocr_data)
    total_frames = len(ocr_data)

    # 候选标签：短文本 + 多帧重复
    candidates = []
    for text, s in stat.items():
        if len(text) > LABEL_MAX_LEN:
            continue
        if s["frames"] < MIN_FRAMES:
            continue
        candidates.append({
            "text": text,
            "frames": s["frames"],
            "avg_y": avg(s["y"]),
            "avg_x": avg(s["x"]),
        })
    candidates.sort(key=lambda c: (-c["frames"], c["avg_y"]))

    # 纵向分布直方图
    bins = defaultdict(int)
    for fr in ocr_data:
        for t in fr.get("texts", []):
            y = layout.y_center(t["box"])
            bins[int(y // BIN_HEIGHT) * BIN_HEIGHT] += 1

    # 坐标范围
    all_y = [layout.y_center(t["box"]) for fr in ocr_data for t in fr.get("texts", [])]
    all_x = [layout.x_left(t["box"]) for fr in ocr_data for t in fr.get("texts", [])]

    lines = []
    lines.append("# 版式探查报告")
    lines.append("")
    lines.append(f"总帧数：{total_frames}")
    if all_y:
        lines.append(f"文本框纵向范围：y {min(all_y):.0f} - {max(all_y):.0f}")
    if all_x:
        lines.append(f"文本框横向范围：x {min(all_x):.0f} - {max(all_x):.0f}")
    lines.append("")

    lines.append("## 一、候选字段标签（跨帧重复的短文本）")
    lines.append("")
    lines.append("这些很可能是画面上的字段标签，照着填进 preset 的 `fields.aliases`。")
    lines.append("")
    lines.append("| 文本 | 出现帧数 | 平均 y | 平均 x |")
    lines.append("|---|---|---|---|")
    for c in candidates[:60]:
        lines.append(f"| {c['text']} | {c['frames']} | {c['avg_y']:.0f} | {c['avg_x']:.0f} |")
    if not candidates:
        lines.append("| （未找到稳定重复的短文本，检查 OCR 结果是否有内容） | | | |")
    lines.append("")

    lines.append("## 二、文本框纵向分布")
    lines.append("")
    lines.append("用来判断标题行在哪、参数区在哪、底部栏从哪开始。")
    lines.append("")
    lines.append("| y 区间 | 文本框数 |")
    lines.append("|---|---|")
    for lo in sorted(bins):
        lines.append(f"| {lo}-{lo + BIN_HEIGHT} | {bins[lo]} |")
    lines.append("")
    lines.append("判读要点：")
    lines.append("- 顶部第一个密集带通常是标题行（品牌 + 型号），据此设 `card.title_max_y`")
    lines.append("- 中部密集带是参数卡主体")
    lines.append("- 画面靠下若有独立密集带，多半是底部横排栏，据此设 `footer_regions`")
    lines.append("")

    lines.append("## 三、region 分布")
    lines.append("")
    lines.append("| region | 文本框数 | 平均 y | 平均 x |")
    lines.append("|---|---|---|---|")
    for rg, s in sorted(region_stats(ocr_data).items()):
        lines.append(f"| {rg} | {s['count']} | {avg(s['y']):.0f} | {avg(s['x']):.0f} |")
    lines.append("")

    lines.append("## 四、下一步")
    lines.append("")
    lines.append("1. 复制 `config/presets/_template.yaml` 为你的 preset")
    lines.append("2. 按第一节的表填 `fields`（每个字段的 `aliases` 照抄「文本」列）")
    lines.append("3. 按第二节的分布设 `card.title_max_y`")
    lines.append("4. 若有底部栏，按第三节的 region 填 `footer_regions`")
    lines.append("")
    lines.append("更详细的判读说明见 references/layout-profiling.md")

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="版式探查：摸清新视频的参数卡版式")
    ap.add_argument("--input", required=True, help="frames_ocr.json 路径")
    ap.add_argument("--output", required=True, help="输出 layout_report.md 路径")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        ocr_data = json.load(f)

    report = build_report(ocr_data)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"版式报告已生成: {args.output}", flush=True)
    print(f"共分析 {len(ocr_data)} 帧", flush=True)


if __name__ == "__main__":
    main()
