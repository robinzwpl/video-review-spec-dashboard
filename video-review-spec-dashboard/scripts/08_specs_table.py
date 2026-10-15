# -*- coding: utf-8 -*-
"""
生成全字段核对表（CSV + HTML），供人工逐项核对。

相比 contact sheet（分批看图），本表把所有字段平铺成表格，便于横向对比与逐项检查。

列顺序、字段中文名、档位划分、口径说明全部取自 preset 配置，
换品类不需要改本文件。

铁律 M8：缺失一律显示「未提取」，不填 0、不推测填充。
"""
import os
import sys
import csv
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from lib import config as cfgmod

# 缺失值文案。main 会从配置的 render.missing_label 读取并覆盖，
# 未配置时保持此默认值（铁律 M8：缺失一律标注，不填 0、不推测填充）
MISSING = "未提取"


def get_field_defs(cfg, field_order):
    """按配置的展示顺序取字段定义。"""
    by_name = {fd["name"]: fd for fd in cfg["fields"]}
    defs = []
    for name in field_order:
        fd = by_name.get(name)
        if fd is None:
            # 兜底字段（如 HDMI2.1数量）不在 fields 里时，用字段名本身做标签
            fd = {"name": name, "label": name, "type": "text_short"}
        defs.append(fd)
    return defs


def tier_of(price, cfg):
    """按配置划分档位；未配置档位时返回 None（不做预设）。"""
    if price is None:
        return None
    for t in cfg.get("dashboard", {}).get("tiers", []):
        if t["lo"] <= price < t["hi"]:
            return t["name"]
    return None


def display_value(p, fd):
    """把字段值转成表格里显示的字符串。"""
    entry = p.get(fd["name"])
    if not entry:
        return MISSING
    val = entry.get("value")
    if val is None:
        return MISSING

    ftype = fd.get("type")
    unit = entry.get("unit", "")

    # 色域一类：识别异常时标「待核对」，不擅自改数值
    if ftype == "percent_std" and entry.get("ocr_error"):
        return f"待核对({val}{unit})"

    if ftype in ("money", "int_unit", "capacity_gb", "size_inch",
                 "zones", "zones_named", "refresh_hz", "count_by_version"):
        return f"{val}{unit}" if unit else str(val)

    if ftype == "range_num":
        if entry.get("is_range"):
            return f"{entry.get('value_min')}-{val}{unit}"
        return f"{val}{unit}" if unit else str(val)

    return str(val)


def build_rows(models, cfg):
    field_order = cfg.get("table", {}).get("field_order", [])
    defs = get_field_defs(cfg, field_order)

    rows = []
    for idx, m in enumerate(sorted(models, key=lambda x: x.get("first_seen", 0)), 1):
        p = m.get("params", {})
        price = p.get(cfg.get("dashboard", {}).get("price_field", "价格"), {}).get("value")

        row = {
            "序号": idx,
            "品牌": m.get("brand") or "?",
            "型号": m.get("model") or "?",
            "档位": tier_of(price, cfg) or "-",
        }
        for fd in defs:
            row[fd["label"]] = display_value(p, fd)

        # 特殊技术特性
        specials = "、".join(sorted({s["name"] for s in m.get("specials", [])}))
        row["特殊技术特性"] = specials or "-"

        # 口径备注（去重）
        note_set = []
        for n in m.get("notes", []):
            t = n.get("note_text", "").strip()
            if t and t not in note_set:
                note_set.append(t)
        # 区间值要显式说明，避免被当成精确值
        for fd in defs:
            entry = p.get(fd["name"], {})
            if entry.get("is_range"):
                note_set.append(f"{fd['label']}为区间，取上限")
            if entry.get("exact") is False:
                note_set.append(f"{fd['label']}为档次区间，非精确值")
        if m.get("verified"):
            note_set.append("部分字段经人工截图确认")
        row["口径备注"] = " | ".join(note_set[:4]) or "-"

        # 数据来源汇总
        src = []
        for v in p.values():
            s = v.get("source", "")
            if "兜底" in s:
                src.append("兜底")
            elif "用户" in s or "人工" in s:
                src.append("人工确认")
        row["数据来源"] = "+".join(sorted(set(src))) if src else "OCR"
        row["来源时间戳"] = f"@{m.get('first_seen', 0):.0f}s"

        rows.append(row)
    return rows, defs


def build_columns(defs, cfg):
    """列顺序：附加列在前 + 字段列 + 附加列在后。"""
    extra = cfg.get("table", {}).get("extra_columns", [])
    head = [c for c in extra if c in ("序号", "品牌", "型号", "档位")]
    tail = [c for c in extra if c not in head]
    field_labels = [fd["label"] for fd in defs]
    seen = set()
    cols = []
    for c in head + field_labels + tail:
        if c not in seen:
            cols.append(c)
            seen.add(c)
    return cols


def coverage(rows, col):
    return sum(1 for r in rows
               if str(r.get(col, MISSING)) not in (MISSING, "未查到", "-", "", "None"))


def write_csv(rows, cols, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_html(rows, cols, defs, cfg, path, stats):
    meta = cfg.get("meta", {})
    title = meta.get("title", "参数核对表")
    caveats = cfg.get("dashboard", {}).get("caveats", [])

    numeric_labels = {fd["label"] for fd in defs
                      if fd.get("type") in ("money", "int_unit", "capacity_gb",
                                            "size_inch", "zones", "zones_named",
                                            "refresh_hz", "count_by_version",
                                            "range_num", "percent_std")}

    def cell_class(col, val):
        s = str(val)
        if s in (MISSING, "未查到", "-", ""):
            return "miss"
        if s.startswith("待核对"):
            return "warn"
        if col in numeric_labels:
            return "num"
        return ""

    notice = "".join(f"<br>{i+1}. {c}" for i, c in enumerate(caveats))

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>{title} - 全字段核对表</title>
<style>
 *{{margin:0;padding:0;box-sizing:border-box}}
 body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#f5f6f8;
      color:#1f2329;padding:20px}}
 h1{{font-size:24px;margin-bottom:6px}}
 .sub{{color:#646a73;font-size:13px;margin-bottom:16px;line-height:1.8}}
 .stats{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px}}
 .stat{{background:#fff;border-radius:6px;padding:12px 18px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
 .stat .n{{font-size:22px;font-weight:600;color:#3370ff}}
 .stat .l{{font-size:12px;color:#8f959e;margin-top:2px}}
 .notice{{background:#fff8e6;border-left:4px solid #ffab00;padding:12px 16px;
         border-radius:4px;font-size:13px;color:#5c4a00;line-height:1.8;margin-bottom:16px}}
 .tw{{background:#fff;border-radius:8px;overflow:auto;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
 table{{border-collapse:collapse;font-size:12.5px;white-space:nowrap}}
 th{{background:#f7f8fa;padding:9px 8px;font-weight:600;text-align:left;
    border-bottom:1px solid #e5e6eb;position:sticky;top:0;z-index:2}}
 td{{padding:8px;border-bottom:1px solid #f0f1f3;vertical-align:top}}
 td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 td.miss{{color:#c9cdd4}}
 td.warn{{color:#fa8c16;font-weight:500}}
 tr:hover td{{background:#fafbfc}}
 .tier{{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11px;
       background:#eef1f4;color:#4a5058}}
 .note{{color:#8f959e;font-size:11px;max-width:280px;white-space:normal;line-height:1.5}}
</style></head><body>
<h1>{title} · 全字段核对表</h1>
<div class="sub">
共 {len(rows)} 条 · 数据源：{meta.get('author', '')}（{meta.get('source_date', '')}）<br>
{meta.get('note', '')}<br>
提取方式：视频关键帧 OCR（参数卡）· 每行标注来源帧时间戳可回溯
</div>
<div class="stats">{''.join(f'<div class="stat"><div class="n">{v}</div><div class="l">{k}</div></div>' for k, v in stats)}</div>
<div class="notice">
<strong>口径说明：</strong>{notice or '（本品类未配置口径说明）'}
<br>{len(caveats) + 1}. 标注「未提取」表示画面未给出该字段，不做推测填充。
</div>
<div class="tw"><table>
<tr>{''.join(f'<th>{c}</th>' for c in cols)}</tr>
"""
    for r in rows:
        tds = []
        for c in cols:
            v = r.get(c, MISSING)
            if c == "档位":
                tds.append(f'<td><span class="tier">{v}</span></td>')
            elif c in ("口径备注", "特殊技术特性"):
                tds.append(f'<td class="note">{v}</td>')
            else:
                tds.append(f'<td class="{cell_class(c, v)}">{v}</td>')
        html += f"<tr>{''.join(tds)}</tr>"

    html += "</table></div></body></html>"

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser(description="生成全字段核对表")
    ap.add_argument("--preset", required=True, help="品类预设名")
    ap.add_argument("--input", required=True, help="models.json 路径")
    ap.add_argument("--csv", required=True, help="输出 CSV 路径")
    ap.add_argument("--html", required=True, help="输出 HTML 路径")
    args = ap.parse_args()

    cfg = cfgmod.load_config(args.preset)

    global MISSING
    MISSING = cfg.get("render", {}).get("missing_label", MISSING)

    with open(args.input, encoding="utf-8") as f:
        models = json.load(f)

    rows, defs = build_rows(models, cfg)
    cols = build_columns(defs, cfg)

    os.makedirs(os.path.dirname(os.path.abspath(args.csv)), exist_ok=True)
    write_csv(rows, cols, args.csv)
    print(f"输出: {args.csv}  ({len(rows)} 行)", flush=True)

    stats = [("条目总数", len(rows))]
    for fd in defs:
        stats.append((fd["label"], coverage(rows, fd["label"])))
    stats.append(("带特殊技术",
                  sum(1 for r in rows if r.get("特殊技术特性") != "-")))

    write_html(rows, cols, defs, cfg, args.html, stats)
    print(f"输出: {args.html}", flush=True)

    print(flush=True)
    print("=" * 76, flush=True)
    print("字段覆盖统计", flush=True)
    print("=" * 76, flush=True)
    for k, v in stats:
        print(f"  {k:<16} {v:>3}/{len(rows)}", flush=True)

    # 列出仍需人工确认的项
    print(flush=True)
    print("=" * 76, flush=True)
    print("需人工确认项", flush=True)
    print("=" * 76, flush=True)
    for r in rows:
        issues = []
        for fd in defs:
            if str(r.get(fd["label"])) == MISSING:
                issues.append(f"缺{fd['label']}")
            elif str(r.get(fd["label"], "")).startswith("待核对"):
                issues.append(f"{fd['label']}异常需核对")
        if issues:
            print(f"  [{r['序号']:2d}] {r['品牌']} {r['型号']}: "
                  f"{'、'.join(issues)}", flush=True)


if __name__ == "__main__":
    main()
