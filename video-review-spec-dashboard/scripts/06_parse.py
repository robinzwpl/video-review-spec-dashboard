# -*- coding: utf-8 -*-
"""
参数卡解析（通用版）：从 OCR 结果里提取出结构化参数。

领域知识（品牌表、字段表、底部栏区域、人工确认值、OCR 修正表）全部来自
config/presets/<名称>.yaml，换品类只需换 preset，不改本文件。

保留的核心处理逻辑（与电视专用版 v3 一致）：
1. 干扰帧排除：开篇总览页多机型同屏，文本框混杂必然错配，整体丢弃
2. 参数卡判定：一帧的字段标签数达到阈值才参与解析
3. 标题行提取品牌 + 型号（含负向词表，避免把 "P3" 当型号）
4. 标签-值几何配对：先按 |Δy| 取最近行，同行内再按 x 拼接
5. 刷新率择优（原生 4K 优先），倍频值单独成字段
6. 无标签字段的全帧兜底提取
7. 底部横排栏按 region 归位（必须按实测 x 边界切分，等分无效）
8. 口径备注留痕（宣称值、国补价等）
9. 机型聚类 + 冲突检测（不静默覆盖，交人工处理）
10. 人工确认值回填并标记来源
"""
import os
import re
import sys
import json
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from lib import config as cfgmod
from lib import layout
from lib import schema

# 来源标记：写进每个字段值，便于溯源核对
SRC_CARD = "OCR参数卡"
SRC_FALLBACK = "OCR参数卡(兜底)"
SRC_FOOTER = "OCR参数卡底部栏"
SRC_USER = "用户截图确认"


def build_context(cfg):
    """把配置整理成便于解析时取用的结构。"""
    return {
        "cfg": cfg,
        "label_idx": cfgmod.label_index(cfg),
        "fields": {fd["name"]: fd for fd in cfg["fields"]},
        "geometry": cfg.get("geometry", {}),
        "ocr_fixes": cfg.get("ocr_fixes", {}),
        "identity": cfg.get("identity", {}),
        "card": cfg.get("card", {}),
    }


def extract_brand_model(text, identity):
    """
    提取品牌与型号。

    实测标题行形态（电视）：
        雷鸟鹏6 SE 2026   创维黑骑士 A5F+   海信小墨E5S
        Vidda小钢炮SMini  华为Vision智慧屏6  小米 S Mini LED 2026
        REDMIA75          TCL V8M          创维 A6F Ultra

    brand_map 留空时不做品牌识别，整行标题作为型号。
    """
    t = text.strip()
    if not t:
        return None, None

    for noise in identity.get("title_noise", []):
        if t.startswith(noise):
            return None, None

    brand_map = identity.get("brand_map") or {}
    if not brand_map:
        # 无品牌表：整行标题作为型号
        return None, t

    brand = None
    for name, pat in brand_map.items():
        if re.search(pat, t, re.I):
            brand = name
            break
    if not brand:
        return None, None

    # 去掉品牌前缀
    rest = t
    for name, pat in brand_map.items():
        m = re.search(pat, t, re.I)
        if m:
            rest = t[m.end():]
            break

    # 去掉栏目字样残留
    for prefix in identity.get("strip_prefix", []):
        rest = re.sub("^" + re.escape(prefix), "", rest)

    # 截断价格等无关后缀
    cut_at = identity.get("cut_at")
    if cut_at:
        rest = re.split(cut_at, rest)[0]
    rest = rest.strip(" ·-—:：")

    if identity.get("strip_year", False):
        rest = re.sub(r"\b(20\d{2})\b", "", rest)
    rest = re.sub(r"\s+", " ", rest).strip()

    # 负向规则：命中色域标准等词表的候选不是型号
    neg = identity.get("model_negative")
    if rest and neg and re.search(neg, rest, re.I):
        return brand, None
    if not rest:
        return brand, None

    return brand, rest


def is_card_frame(frame, ctx):
    """一帧的字段标签数达到阈值，才认为是参数卡。"""
    items = layout.build_items(frame["texts"], ctx["ocr_fixes"])
    labels = sum(1 for it in items
                 if layout.classify_label(it["text"], ctx["label_idx"]))
    return labels >= ctx["card"].get("min_labels", 4)


def convert_raw(raw, ftype):
    """把正则捕获到的字符串按类型转成目标类型。"""
    if ftype in ("money",):
        return float(str(raw).replace(",", ""))
    if ftype in ("capacity_gb", "int_unit", "size_inch", "zones",
                 "zones_named", "count_by_version", "refresh_hz",
                 "range_num", "percent_std"):
        return int(raw)
    return str(raw).strip()


def apply_fallback(items, params, ctx):
    """
    无标签字段的全帧兜底提取。

    实测底部横排版式中，「运行内存/存储」一栏的标签可能没被 OCR 出来，
    只剩值（形如 "2GB / 64GB"），导致该字段整体缺失，故做一次全帧匹配。
    """
    full_text = " ".join(it["text"] for it in items)
    for rule in ctx["cfg"].get("fallback_extract", []):
        field = rule["field"]
        if field in params:
            continue
        flags = re.I if rule.get("ignore_case", True) else 0
        m = re.search(rule["pattern"], full_text, flags)
        if not m:
            continue
        group = rule.get("group", 1)
        val = convert_raw(m.group(group), rule.get("type", "text_short"))
        entry = {"value": val, "unit": rule.get("unit", ""),
                 "raw": m.group(0), "source": SRC_FALLBACK}
        if rule.get("note"):
            entry["note"] = rule["note"]
        if rule.get("hdmi_ver"):
            entry["hdmi_ver"] = rule["hdmi_ver"]
        params[field] = entry


def collect_notes(items, ctx):
    """按配置提取口径备注（宣称值、国补价、高刷说明等），铁律 M9。"""
    notes = []
    for it in items:
        for rule in ctx["cfg"].get("note_rules", []):
            text = it["text"]
            if rule.get("require") and rule["require"] not in text:
                continue
            if rule.get("mode") == "match":
                hit = re.match(rule["pattern"], text)
            else:
                hit = re.search(rule["pattern"], text)
            if not hit:
                continue
            note_text = rule.get("fixed_text") or text
            notes.append({"field": rule["field"], "note_text": note_text})
    return notes


def apply_footer(items, params, ctx):
    """
    底部横排栏：按 OCR 阶段标注的 region 归位。

    必须按实测 x 边界切分，等分切分无效 —— 实测内存覆盖率因此从 2/32 提升到 31/32。
    ordinal 用于「2GB / 64GB」这类同形态复合值：0 取第一个匹配，1 取第二个。
    """
    regions = ctx["cfg"].get("footer_regions", {})
    if not regions:
        return
    buf = defaultdict(list)
    for it in items:
        rg = it.get("region", "")
        if rg in regions:
            buf[rg].append(it["text"])

    for rg, region_def in regions.items():
        texts = buf.get(rg, [])
        if not texts:
            continue
        blob = " ".join(texts)
        for ex in region_def.get("extractors", []):
            field = ex["field"]
            if field in params:
                continue
            flags = re.I if ex.get("ignore_case", True) else 0
            matches = re.findall(ex["pattern"], blob, flags)
            if not matches:
                continue
            ordinal = ex.get("ordinal", 0)
            if ordinal >= len(matches):
                continue
            val = convert_raw(matches[ordinal], ex.get("type", "text_short"))
            entry = {"value": val, "unit": ex.get("unit", ""),
                     "raw": blob, "source": SRC_FOOTER}
            if ex.get("note"):
                entry["note"] = ex["note"]
            params[field] = entry


def parse_card_geometry(frame, ctx):
    """解析单帧参数卡，返回 (brand, model, {params, notes, specials})。"""
    cfg = ctx["cfg"]
    items = layout.build_items(frame["texts"], ctx["ocr_fixes"])

    labels = []
    for it in items:
        f = layout.classify_label(it["text"], ctx["label_idx"])
        if f:
            labels.append({**it, "field": f})
    if len(labels) < ctx["card"].get("min_labels", 4):
        return None, None, None

    # 标题行：品牌 + 型号所在
    title_max_y = ctx["card"].get("title_max_y", 150)
    title_band = [it for it in items if it["yc"] < title_max_y]
    brand, model = None, None
    for it in sorted(title_band, key=lambda x: x["xl"]):
        if re.search(r"参考价|[¥￥]", it["text"]):
            continue
        b, m_ = extract_brand_model(it["text"], ctx["identity"])
        if b:
            brand = b
            if m_:
                model = m_
                break
    if not brand:
        for it in sorted(title_band, key=lambda x: x["xl"]):
            b, m_ = extract_brand_model(it["text"], ctx["identity"])
            if b:
                brand = b
                if m_:
                    model = m_
                    break

    params = {}
    bad_values = {}
    for lb, val_text in layout.pair_values(items, labels, ctx["geometry"],
                                           ctx["label_idx"]):
        fd = ctx["fields"].get(lb["field"])
        if fd is None:
            continue
        parsed = schema.parse_value(val_text, fd, cfg, source=SRC_CARD)
        if not parsed:
            continue
        # 解析不出有效值时不写入 params，仅在 notes 中留痕
        if parsed.get("value") is None:
            bad_values.setdefault(lb["field"], []).append({
                "raw": parsed.get("raw", ""),
                "note": parsed.get("note", ""),
            })
            continue
        parsed["label_text"] = lb["text"]

        if lb["field"] in params:
            prev = params[lb["field"]]
            if prev.get("value") != parsed.get("value"):
                prev.setdefault("alt_values", []).append({
                    "value": parsed["value"], "raw": parsed["raw"],
                    "is_native": parsed.get("is_native"),
                })
        else:
            params[lb["field"]] = parsed

    # 刷新率择优：原生 4K 优先
    for fd in cfg["fields"]:
        if fd.get("type") != "refresh_hz":
            continue
        fname = fd["name"]
        if fname not in params:
            continue
        r = params[fname]
        alts = r.get("alt_values", [])
        if not r.get("is_native"):
            native = [a for a in alts if a.get("is_native")]
            if native:
                params[fname] = {
                    "value": native[0]["value"], "unit": "Hz",
                    "raw": native[0]["raw"], "source": SRC_CARD,
                    "is_native": True, "note": fd.get("notes", {}).get("native"),
                }
            else:
                r["note"] = fd.get("notes", {}).get("non_native")

        # 倍频单独成字段，不与原生刷新率混算
        boost_field = fd.get("boost_field")
        boost_pattern = fd.get("boost_pattern")
        if boost_field and boost_pattern:
            for it in items:
                m = re.search(boost_pattern, it["text"])
                if m:
                    params[boost_field] = {
                        "value": int(m.group(1)), "unit": "Hz",
                        "raw": it["text"], "source": SRC_CARD,
                        "note": fd.get("boost_note"),
                    }

    # 无标签字段兜底
    apply_fallback(items, params, ctx)

    # 口径备注
    notes = collect_notes(items, ctx)

    # 底部横排栏
    apply_footer(items, params, ctx)

    # 特殊技术特性
    full = " ".join(it["text"] for it in items)
    specials = []
    for sp in cfg.get("specials", []):
        if re.search(sp["pattern"], full, re.I):
            specials.append({"name": sp["name"], "type": sp.get("type"),
                             "owner": sp.get("owner")})

    # 解析异常值转 notes，不写入 params
    for field, entries in bad_values.items():
        for e in entries:
            notes.append({"field": f"_OCR异常:{field}",
                          "note_text": f"{e['raw']} —— {e['note']}"})

    return brand, model, {"params": params, "notes": notes, "specials": specials}


def apply_overrides(models, overrides):
    """套用人工核对确认值，并标记来源。"""
    fixed = 0
    for m in models:
        name = f"{m.get('brand') or ''}{m.get('model') or ''}"
        for key, patch in (overrides or {}).items():
            if key in name or name in key:
                for field, val in patch.items():
                    m["params"][field] = {
                        **val, "raw": "(用户截图确认)",
                        "source": SRC_USER, "verified_by": "user_screenshot",
                    }
                    fixed += 1
                m["verified"] = True
    return fixed


def merge_cards(cards, cfg):
    """把同一机型的多个帧合并成一条记录，冲突不静默覆盖。"""
    groups = defaultdict(list)
    for c in cards:
        groups[(c["brand"], c["model"])].append(c)

    models_out = []
    for (brand, model), items in groups.items():
        if not brand and not model:
            continue

        merged = {}
        conflicts = []
        all_notes = []
        all_specials = []
        for it in items:
            all_notes.extend(it["notes"])
            for s in it["specials"]:
                if s["name"] not in [x["name"] for x in all_specials]:
                    all_specials.append(s)
            for field, val in it["params"].items():
                if field not in merged:
                    merged[field] = {**val,
                                     "source_timestamp": it["timestamp"],
                                     "frame_path": it["frame_path"],
                                     "frame_count": 1}
                else:
                    if merged[field]["value"] != val["value"]:
                        conflicts.append({
                            "field": field,
                            "old": merged[field]["value"],
                            "new": val["value"],
                            "old_ts": merged[field]["source_timestamp"],
                            "new_ts": it["timestamp"]})
                    else:
                        merged[field]["frame_count"] += 1

        models_out.append({
            "brand": brand, "model": model, "params": merged,
            "frame_count": len(items),
            "first_seen": min(i["timestamp"] for i in items),
            "last_seen": max(i["timestamp"] for i in items),
            "notes": all_notes[:8],
            "specials": all_specials,
            "conflicts": conflicts,
        })
    return models_out


def print_report(models, cfg):
    """打印解析结果概要，字段取自配置的 metrics 与 price_field。"""
    dash = cfg.get("dashboard", {})
    price_field = dash.get("price_field", "价格")
    metrics = dash.get("metrics", [])

    print(flush=True)
    print("=" * 110, flush=True)
    print(f"共 {len(models)} 个机型", flush=True)
    print("=" * 110, flush=True)

    cols = [("时间", 6), ("品牌", 6), ("型号", 16)] + \
           [(m.get("label", m["field"]), 12) for m in metrics]
    header = " ".join(f"{n:>{w}s}" for n, w in cols)
    print(header, flush=True)

    for m in models:
        p = m["params"]
        price = p.get(price_field, {}).get("value", "-")
        cells = [f"{m['first_seen']:6.0f}",
                 f"{str(m['brand'] or '?'):6s}",
                 f"{str(m['model'] or '?'):16s}"]
        for mt in metrics:
            v = p.get(mt["field"], {}).get("value", "-")
            unit = p.get(mt["field"], {}).get("unit", "")
            cells.append(f"{str(v)}{unit}".rstrip())
        # 价格单独附在型号后，便于核对档位
        cells[2] = f"{str(m['model'] or '?')}({price})"
        print(" ".join(cells), flush=True)

        sp = [s["name"] for s in m["specials"]]
        if sp:
            print(f"{'':>6} └ 特殊: {'、'.join(sp)}", flush=True)
        for c in m["conflicts"][:2]:
            print(f"{'':>6} ⚠ 冲突 {c['field']}: {c['old']}@{c['old_ts']}s vs "
                  f"{c['new']}@{c['new_ts']}s", flush=True)


def main():
    ap = argparse.ArgumentParser(description="参数卡解析（通用版，配置驱动）")
    ap.add_argument("--preset", required=True,
                    help="品类预设名，如 tv75_science")
    ap.add_argument("--input", required=True, help="frames_ocr.json 路径")
    ap.add_argument("--output", required=True, help="输出 models.json 路径")
    args = ap.parse_args()

    cfg = cfgmod.load_config(args.preset)
    ctx = build_context(cfg)

    with open(args.input, encoding="utf-8") as f:
        ocr_data = json.load(f)
    print(f"载入 OCR 数据: {len(ocr_data)} 帧", flush=True)

    # 排除开篇多机型同屏干扰帧
    exclude_before = cfg.get("exclude_before_sec", 0.0)
    usable = [f for f in ocr_data if f["timestamp"] >= exclude_before]
    skipped = len(ocr_data) - len(usable)
    print(f"排除开篇干扰帧: {skipped} 帧（< {exclude_before}s，多机型同屏易错配）",
          flush=True)
    print(f"可用帧: {len(usable)}", flush=True)

    cards = []
    for fr in usable:
        if not is_card_frame(fr, ctx):
            continue
        brand, model, parsed = parse_card_geometry(fr, ctx)
        if parsed and parsed["params"]:
            cards.append({
                "timestamp": fr["timestamp"],
                "frame_path": fr["frame_path"],
                "brand": brand, "model": model,
                "params": parsed["params"],
                "notes": parsed["notes"],
                "specials": parsed["specials"],
            })

    print(f"识别到参数卡: {len(cards)} 帧", flush=True)

    models_out = merge_cards(cards, cfg)

    nfix = apply_overrides(models_out, cfg.get("overrides"))
    print(f"套用人工确认值: {nfix} 个字段", flush=True)

    models_out.sort(key=lambda x: x["first_seen"])

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(models_out, f, ensure_ascii=False, indent=2)
    print(f"输出: {args.output}", flush=True)

    all_fields = set()
    for m in models_out:
        all_fields.update(m["params"].keys())
    print(f"覆盖字段: {sorted(all_fields)}", flush=True)
    print(f"冲突总数: {sum(len(m['conflicts']) for m in models_out)}", flush=True)
    print(f"带特殊参数机型: {sum(1 for m in models_out if m['specials'])}", flush=True)

    print_report(models_out, cfg)


if __name__ == "__main__":
    main()
