# -*- coding: utf-8 -*-
"""
生成全字段核对表（CSV + HTML），供用户一次性核对 32 台机型。

相比 contact sheet（分批看图），本表把所有字段平铺成表格，
便于横向对比与逐项检查。
"""
import os
import re
import sys
import json
import csv


# 字段展示顺序与中文名
FIELD_ORDER = [
    ("价格", "参考价(元)"),
    ("屏幕", "屏幕类型"),
    ("屏幕尺寸", "尺寸(英寸)"),
    ("分区数", "背光分区"),
    ("控色区", "玲珑控色区"),
    ("峰值亮度", "峰值亮度(nit)"),
    ("刷新率", "原生刷新(Hz)"),
    ("刷新率_倍频", "倍频(Hz)"),
    ("色域", "色域"),
    ("内存", "内存(GB)"),
    ("存储", "存储(GB)"),
    ("处理器", "处理器"),
    ("HDMI2.1数量", "HDMI2.1(个)"),
    ("HDMI2.0数量", "HDMI2.0(个)"),
    ("发声单元", "发声单元(个)"),
]

COLUMNS = [
    "序号", "品牌", "型号", "档位", "参考价(元)", "屏幕类型", "尺寸(英寸)",
    "背光分区", "玲珑控色区", "分区类型", "峰值亮度(nit)", "亮度为区间", "原生刷新(Hz)",
    "倍频(Hz)", "色域", "内存(GB)", "存储(GB)", "处理器",
    "HDMI2.1(个)", "HDMI2.0(个)", "发声单元(个)",
    "特殊技术特性", "口径备注", "来源时间戳", "数据来源",
]


def classify_tier(price):
    """
    按视频实际章节卡与实际价格分布分档。
    实测 32 台价格区间 2821.9 - 10649.1 元。
    """
    if price is None:
        return "未查到"
    if price < 3500:
        return "3000元档"
    if price < 4500:
        return "3500-4500元"
    if price < 6000:
        return "4500-6000元"
    if price < 8000:
        return "6000-8000元"
    if price < 11000:
        return "8000-11000元"
    return "11000元以上"


def build_rows(models):
    rows = []
    for idx, m in enumerate(sorted(models, key=lambda x: x.get("first_seen", 0)), 1):
        p = m.get("params", {})

        def gv(field):
            return p.get(field, {}).get("value")

        price = gv("价格")
        zones = gv("分区数")
        bright = gv("峰值亮度")
        cg = p.get("色域", {})
        cg_val = cg.get("value")
        cg_std = cg.get("unit", "")
        if cg.get("ocr_error"):
            # 画面原文如此，技术上不成立但据实记录，标注待人工核对
            cg_disp = f"待核对({cg_val}{cg_std})"
        else:
            cg_disp = f"{cg_val}{cg_std}" if cg_val is not None else "未提取"

        specials = "、".join(sorted({s["name"] for s in m.get("specials", [])}))

        # 口径备注（去重）
        note_set = []
        for n in m.get("notes", []):
            t = n.get("note_text", "").strip()
            if t and t not in note_set:
                note_set.append(t)
        # 分区非精确也要说明
        if zones is not None and p.get("分区数", {}).get("exact") is False:
            note_set.append("分区为档次区间，非精确值")
        if m.get("verified"):
            note_set.append("部分字段经用户截图确认")
        notes = " | ".join(note_set[:4])

        # 数据来源
        src = []
        for field, v in p.items():
            s = v.get("source", "")
            if "兜底" in s:
                src.append("兜底")
            elif "用户" in s:
                src.append("用户确认")
        src_disp = "+".join(sorted(set(src))) if src else "OCR"

        rows.append({
            "序号": idx,
            "品牌": m.get("brand") or "?",
            "型号": m.get("model") or "?",
            "档位": classify_tier(price),
            "参考价(元)": price if price is not None else "未提取",
            "屏幕类型": gv("屏幕") or "未提取",
            "尺寸(英寸)": gv("屏幕尺寸") or "未提取",
            "背光分区": zones if zones is not None else "未提取",
            "玲珑控色区": gv("控色区") if gv("控色区") is not None else "未提取",
            "分区类型": p.get("分区数", {}).get("zone_type") or "-",
            "峰值亮度(nit)": bright if bright is not None else "未提取",
            "亮度为区间": "是" if p.get("峰值亮度", {}).get("is_range") else "",
            "原生刷新(Hz)": gv("刷新率") if gv("刷新率") is not None else "未提取",
            "倍频(Hz)": gv("刷新率_倍频") or "",
            "色域": cg_disp,
            "内存(GB)": gv("内存") if gv("内存") is not None else "未提取",
            "存储(GB)": gv("存储") if gv("存储") is not None else "未提取",
            "处理器": gv("处理器") or "未提取",
            "HDMI2.1(个)": gv("HDMI2.1数量") or "未提取",
            "HDMI2.0(个)": gv("HDMI2.0数量") or "未提取",
            "发声单元(个)": gv("发声单元") or "未提取",
            "特殊技术特性": specials or "-",
            "口径备注": notes or "-",
            "来源时间戳": f"@{m.get('first_seen', 0):.0f}s",
            "数据来源": src_disp,
        })
    return rows


def write_csv(rows, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def write_html(rows, path, stats):
    """生成便于横向扫视的 HTML 表格。"""
    # 分组着色
    tier_colors = {
        "3000元以下": "#f0f9eb", "3000-4500": "#e6f4ff",
        "4500-6000": "#fff7e6", "6000-8000": "#fff1f0",
        "8000-12000": "#f9f0ff", "12000以上": "#fff0f6",
        "未查到": "#f5f5f5",
    }

    def cell_class(col, val):
        s = str(val)
        if s in ("未提取", "未查到", "-", ""):
            return "miss"
        if s.startswith("待确认"):
            return "warn"
        if col in ("序号",):
            return "num"
        if col in ("参考价(元)", "峰值亮度(nit)", "原生刷新(Hz)", "内存(GB)",
                   "存储(GB)", "背光分区", "HDMI2.1(个)", "发声单元(个)"):
            return "num"
        return ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>75寸电视横评 - 全字段核对表</title>
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
<h1>75 寸电视横评 · 全字段核对表</h1>
<div class="sub">
共 {len(rows)} 台机型 · 数据源：科技绝对值《七大品牌 32 台 75 寸电视横评》（2026-09-23）<br>
提取方式：视频关键帧 OCR（参数卡）+ 音频转写交叉验证 · 每行标注来源帧时间戳可回溯
</div>
<div class="stats">{''.join(f'<div class="stat"><div class="n">{v}</div><div class="l">{k}</div></div>' for k, v in stats)}</div>
<div class="notice">
<strong>口径说明：</strong>① 色域按标准分列（sRGB / DCI-P3 / BT.2020 / BT.709），不同标准数值不可直接比较；
② 刷新率以原生 4K 口径为主，倍频/2K 模式单独记录；
③ 亮度常为区间（如 4000-5000 nits），表中取上限并标注「亮度为区间」；
④ 分区若为档次（如 100-200级）非精确值，已在「分区类型」列标明；
⑤ 标注「未提取」表示视频参数卡上未给出该字段，不做推测填充。
</div>
<div class="tw"><table>
<tr>{''.join(f'<th>{c}</th>' for c in COLUMNS)}</tr>
"""

    for r in rows:
        tcls = tier_colors.get(r["档位"], "#f5f5f5")
        tds = []
        for c in COLUMNS:
            v = r[c]
            if c == "档位":
                tds.append(f'<td><span class="tier" style="background:{tcls}">{v}</span></td>')
            elif c in ("口径备注", "特殊技术特性"):
                tds.append(f'<td class="note">{v}</td>')
            else:
                tds.append(f'<td class="{cell_class(c, v)}">{v}</td>')
        html += f"<tr>{''.join(tds)}</tr>"

    html += "</table></div></body></html>"

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "output"
    with open(os.path.join(out_dir, "tv_models.json"), encoding="utf-8") as f:
        models = json.load(f)

    rows = build_rows(models)

    csv_path = os.path.join(out_dir, "tv_specs.csv")
    write_csv(rows, csv_path)
    print(f"输出: {csv_path}  ({len(rows)} 行)", flush=True)

    # 统计
    def cov(col):
        return sum(1 for r in rows if str(r[col]) not in
                   ("未提取", "未查到", "-", "", "None"))

    stats = [
        ("机型总数", len(rows)),
        ("价格完整", cov("参考价(元)")),
        ("亮度完整", cov("峰值亮度(nit)")),
        ("分区完整", cov("背光分区")),
        ("刷新率完整", cov("原生刷新(Hz)")),
        ("色域完整", cov("色域")),
        ("内存完整", cov("内存(GB)")),
        ("处理器完整", cov("处理器")),
        ("带特殊技术", sum(1 for r in rows if r["特殊技术特性"] != "-")),
    ]

    html_path = os.path.join(out_dir, "tv_specs_table.html")
    write_html(rows, html_path, stats)
    print(f"输出: {html_path}", flush=True)

    print(flush=True)
    print("=" * 76, flush=True)
    print("字段覆盖统计", flush=True)
    print("=" * 76, flush=True)
    for k, v in stats:
        print(f"  {k:<12} {v:>3}/{len(rows)}", flush=True)

    # 列出仍需人工确认的项
    print(flush=True)
    print("=" * 76, flush=True)
    print("需人工确认项", flush=True)
    print("=" * 76, flush=True)
    for r in rows:
        issues = []
        if "待核对" in str(r["色域"]) or "超过 100%" in r["口径备注"]:
            issues.append("色域超100%需核对")
        # 缺分区：若该机改用玲珑控色区（海信口径），不算缺失
        if r["背光分区"] == "未提取" and r["玲珑控色区"] == "未提取":
            issues.append("画面未给分区")
        if r["峰值亮度(nit)"] == "未提取":
            issues.append("画面未给亮度")
        if r["内存(GB)"] == "未提取":
            issues.append("缺内存(字幕遮挡)")
        if r["处理器"] == "未提取":
            issues.append("缺处理器(字幕遮挡)")
        if issues:
            print(f"  [{r['序号']:2d}] {r['品牌']} {r['型号']}: "
                  f"{'、'.join(issues)}", flush=True)


if __name__ == "__main__":
    main()
