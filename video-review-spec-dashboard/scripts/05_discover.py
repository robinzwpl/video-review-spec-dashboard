# -*- coding: utf-8 -*-
"""
版式探查：在还没有 preset 的时候，先摸清这个视频的参数卡长什么样。

它会统计跨帧重复出现的短文本（这些通常就是字段标签），给出它们的平均坐标，
再给出文本框的纵向分布，用来确定标题行阈值与底部栏边界。
照着报告填 config/presets/_template.yaml 即可，不用手动一帧帧量坐标。

--emit-preset 会直接产出一份可编辑的 preset 草稿：字段表、建议阈值、
底部栏区域骨架都先填好，剩下的交给人工确认。

用法：
    python scripts/05_discover.py --input output/frames_ocr.json --output output/layout_report.md
    python scripts/05_discover.py --input output/frames_ocr.json --emit-preset config/presets/my.yaml
"""
import os
import re
import sys
import json
import argparse
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from lib import layout

# 候选标签的最大长度：字段标签通常很短
LABEL_MAX_LEN = 8
# 至少在这么多帧里出现过，才认为是稳定的字段标签
MIN_FRAMES = 3
# 纵向分布直方图的区间高度（像素）
BIN_HEIGHT = 50
# 草稿里最多收录多少个候选字段（按出现帧数排序取前 N）
MAX_DRAFT_FIELDS = 40


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


def y_bins(ocr_data):
    """文本框的纵向分布直方图：{区间起点 y: 框数}。"""
    bins = defaultdict(int)
    for fr in ocr_data:
        for t in fr.get("texts", []):
            y = layout.y_center(t["box"])
            bins[int(y // BIN_HEIGHT) * BIN_HEIGHT] += 1
    return bins


def suggest_title_max_y(bins, height):
    """
    建议标题行纵向上限：取顶部连续密集带的下沿。

    判读逻辑：从上往下扫，只要区间框数不低于全局峰值的 35% 就继续归入
    标题带，遇到第一个稀疏区间即止，阈值取此时带的下沿。
    「连续」二字不能省——只看第一个密集带会把标题下方的副标题行切走
    （实测：只看首个区间得 100，取连续带得 150，后者才是可用值）。
    找不到密集带时给一个 14% 画面高度的保守值。
    """
    if not bins:
        return int(height * 0.14)
    thresh = max(bins.values()) * 0.35
    edge = None
    for lo in sorted(bins):
        if lo > height * 0.5:
            break
        if bins[lo] >= thresh:
            edge = lo + BIN_HEIGHT
        elif edge is not None:
            break
    return int(edge) if edge is not None else int(height * 0.14)


def suggest_footer_top(bins, height):
    """
    建议底部栏起始 y：自底向上找密集带，遇到密度谷即止。

    判读逻辑：以最底部区间的框数为基准，向上只要不低于其 40% 就仍在底栏内，
    第一个明显稀疏的区间就是密度谷，它的起点即底栏上界的保守估计。

    注意不能按「空区间」找边界——画面中部的文字几乎是连续的，
    按空档找会一路走到画面顶部，永远检测不到底栏。
    """
    if not bins:
        return None
    los = sorted(bins)
    thresh = bins[los[-1]] * 0.4
    top = los[-1]
    for lo in reversed(los[:-1]):
        top = lo
        if bins[lo] < thresh:
            break
    if top < height * 0.6:
        return None
    return int(top)


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
    bins = y_bins(ocr_data)

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
    # 建议阈值（同一套判读逻辑也被 --emit-preset 使用，保持两处一致）
    height = max(all_y) / 0.95 if all_y else 1080
    title_y = suggest_title_max_y(bins, height)
    footer_y = suggest_footer_top(bins, height)
    lines.append("建议阈值（已按上表算出，可直接用）：")
    lines.append("")
    lines.append("| 配置项 | 建议值 | 依据 |")
    lines.append("|---|---|---|")
    lines.append(f"| `card.title_max_y` | {title_y} | 顶部连续密集带的下沿 |")
    if footer_y is None:
        lines.append("| 底部栏起始 y | 未检测到 | 画面下半部没有与上方断开的密集带 |")
    else:
        lines.append(f"| 底部栏起始 y | {footer_y} | 自底向上密集带遇密度谷而止（保守值，实际边界在其下方一档内） |")
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
    lines.append("两种走法，选一种：")
    lines.append("")
    lines.append("**A. 让工具起草**（推荐）")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/05_discover.py --input output/frames_ocr.json \\")
    lines.append("        --emit-preset config/presets/<品类名>.yaml --width 1920 --height 1080")
    lines.append("```")
    lines.append("")
    lines.append("产出的草稿里字段表、建议阈值、底部栏骨架都填好了，")
    lines.append("带 `# TODO` 的行是必须人工确认的（主要是每个字段的 `type`）。")
    lines.append("")
    lines.append("**B. 手工填**")
    lines.append("")
    lines.append("1. 复制 `config/presets/_template.yaml` 为你的 preset")
    lines.append("2. 按第一节的表填 `fields`（每个字段的 `aliases` 照抄「文本」列）")
    lines.append("3. 按第二节的分布设 `card.title_max_y`")
    lines.append("4. 若有底部栏，按第三节的 region 填 `footer_regions`")
    lines.append("")
    lines.append("更详细的判读说明见 references/layout-profiling.md")

    return "\n".join(lines)


def _q(s):
    """把字符串转成 YAML 双引号标量（JSON 字符串语法是 YAML 1.2 的子集）。"""
    return json.dumps(s, ensure_ascii=False)


def build_preset_draft(ocr_data, width, height, preset_name, source):
    """
    生成一份 preset 草稿。

    只做三件事：把候选标签铺成字段表、按纵向分布给出建议阈值、检测到的
    底部栏给一个区域骨架。字段的 type 一律先给 text 并标 TODO——类型判定
    依赖对品类规格的理解，自动推断的错配会静默污染数据，不如让人确认。
    """
    stat = collect(ocr_data)
    bins = y_bins(ocr_data)

    candidates = []
    for text, s in stat.items():
        if len(text) > LABEL_MAX_LEN or s["frames"] < MIN_FRAMES:
            continue
        candidates.append({"text": text, "frames": s["frames"], "avg_y": avg(s["y"])})
    candidates.sort(key=lambda c: (-c["frames"], c["avg_y"]))
    candidates = candidates[:MAX_DRAFT_FIELDS]

    title_y = suggest_title_max_y(bins, height)
    footer_y = suggest_footer_top(bins, height)

    L = []
    A = L.append
    A("# ============================================================")
    A(f"# preset 草稿，由 scripts/05_discover.py 于 {date.today().isoformat()} 生成")
    A(f"# 源文件：{source}")
    A(f"# 比例坐标按 {width}x{height} 换算；若实际分辨率不同，改 --width/--height 重跑")
    A("#")
    A("# 这是草稿，不是成品。带 `# TODO` 的行必须人工确认后才能用：")
    A("#   1. 每个字段的 type 目前一律是 text，照 references/field-cookbook.md 改")
    A("#   2. 候选字段里混有字幕与口播文本，不属于参数卡的行请直接删掉")
    A("#   3. 底部栏的 x 边界本工具不推断（等分切是错的），需照拼图逐段量")
    A("# ============================================================")
    A("")
    A("meta:")
    A(f"  name: {_q(preset_name)}")
    A('  title: "TODO 看板标题"')
    A('  author: "TODO 视频作者"')
    A(f'  source_date: "{date.today().isoformat()}"')
    A('  note: "TODO 一句话说明这批数据是什么"')
    A("")
    A("# 开篇总览页多条目同屏会错配，填该页结束秒数；没有就留 0")
    A("exclude_before_sec: 0.0")
    A("")
    A("ocr_fixes:")
    A("  literal: []")
    A("  regex: []")
    A("")
    A("card:")
    A(f"  title_max_y: {title_y}   # TODO 核对：标题行纵向上限，取自顶部密集带下沿")
    A("")
    A("ocr:")
    A("  regions:")
    if footer_y is None:
        A("    # 未检测到独立底部栏；若实际存在，取消下面的注释并照实测坐标填")
        A("    # footer_label:")
        A("    #   box: [0.02, 0.80, 0.98, 0.95]")
        A("    #   role: footer_label")
        A("    #   order: 10")
    else:
        y1 = round(footer_y / height, 4)
        A(f"    # 底部栏骨架：起始 y 由分布推定（{footer_y}px，保守值），x 边界需人工量")
        A("    # 底栏与字幕在纵向上重叠是常态，靠 x 边界避开字幕（字幕通常居中）")
        A("    footer_band:")
        A(f"      box: [0.02, {y1}, 0.98, 0.999]   # TODO 按实测 x 边界拆成多段，勿等分")
        A("      role: footer_label")
        A("      order: 10")
    A("")
    A("identity:")
    A("  # TODO 填品牌表：品牌名 -> 匹配正则。留空则整行标题当型号")
    A("  brand_map: {}")
    A("  title_noise: []")
    A('  model_negative: ""')
    A("  strip_prefix: []")
    A("  strip_year: false")
    A('  cut_at: ""')
    A("")
    A("# TODO 逐个字段确认 type，见 references/field-cookbook.md")
    A("fields:")
    if not candidates:
        A("  []   # 没找到跨帧重复的短文本，检查 OCR 结果是否有内容")
    for c in candidates:
        A(f"  - name: {_q(c['text'])}")
        A(f"    label: {_q(c['text'])}")
        A('    type: text          # TODO 需人工确认')
        A(f"    aliases: [{_q(c['text'])}]")
    A("")
    A("fallback_extract: []")
    A("")
    A("footer_regions: {}   # TODO 底部栏拆段后，在这里声明每段出哪些字段")
    A("")
    A("specials: []")
    A("overrides: {}")
    A("note_rules: []")
    A("")
    A("table:")
    names = [_q(c["text"]) for c in candidates]
    A(f"  field_order: [{', '.join(names)}]")
    A('  extra_columns: ["序号", "品牌", "型号", "数据来源"]')
    A("")
    A("dashboard:")
    A('  price_field: ""   # TODO 填价格字段名，没有价格就留空')
    A("  tiers: []         # 档位从数据实际分布推导，不要预设")
    A("  metrics:")
    for i, c in enumerate(candidates[:6], 1):
        A(f'    - {{field: {_q(c["text"])}, key: "metric{i}", label: {_q(c["text"])} }}')
    A("  color_std_groups: []")
    A("  caveats: []")
    A("")

    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="版式探查：摸清新视频的参数卡版式")
    ap.add_argument("--input", required=True, help="frames_ocr.json 路径")
    ap.add_argument("--output", help="输出 layout_report.md 路径")
    ap.add_argument("--emit-preset", help="额外产出一份 preset 草稿到该路径")
    ap.add_argument("--name", help="草稿里的 preset 名，默认取 --emit-preset 的文件名")
    ap.add_argument("--width", type=int, default=1920, help="画面宽，用于把像素换算成比例")
    ap.add_argument("--height", type=int, default=1080, help="画面高，用于把像素换算成比例")
    args = ap.parse_args()

    if not args.output and not args.emit_preset:
        ap.error("--output 与 --emit-preset 至少给一个")

    with open(args.input, encoding="utf-8") as f:
        ocr_data = json.load(f)

    if args.output:
        report = build_report(ocr_data)
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"版式报告已生成: {args.output}", flush=True)

    if args.emit_preset:
        name = args.name or os.path.splitext(os.path.basename(args.emit_preset))[0]
        draft = build_preset_draft(ocr_data, args.width, args.height, name, args.input)
        os.makedirs(os.path.dirname(os.path.abspath(args.emit_preset)), exist_ok=True)
        with open(args.emit_preset, "w", encoding="utf-8") as f:
            f.write(draft)
        print(f"preset 草稿已生成: {args.emit_preset}", flush=True)
        print("  带 # TODO 的行需人工确认后才能使用（主要是字段 type）", flush=True)

    print(f"共分析 {len(ocr_data)} 帧", flush=True)


if __name__ == "__main__":
    main()
