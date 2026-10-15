# -*- coding: utf-8 -*-
"""
生成核对用 contact sheet（按品牌分批）。

用途：让用户逐批核对 OCR 提取的参数是否与画面一致。
输出：<out-dir>/contact_sheet_<序号>_<品牌>.jpg

品牌分组与字段顺序均取自品类预设（identity.brand_map / table.field_order），
不再写死在代码里。

用法：
    python 07_contact_sheet.py --preset tv75_science --out-dir output
    python 07_contact_sheet.py output                  # 位置参数，兼容旧调用
"""
import os
import re
import sys
import json
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw, ImageFont

from lib import config as cfgmod

# 每批最多几台（2 列 x 3 行）
BATCH_SIZE = 6
# 单元格尺寸：改动会影响已有批次图的画布大小，非必要不要动
CELL_W, CELL_H = 960, 620
HEAD_H = 70
# 左侧参数卡缩略图的最大尺寸
THUMB = (620, 340)


def load_font(size=20):
    """加载中文字体。"""
    for p in [r"C:\Windows\Fonts\msyh.ttc",
              r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\simhei.ttf",
              r"C:\Windows\Fonts\simsun.ttc"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def brand_of(name, brand_map):
    """按预设的品牌表识别品牌；表为空则不做识别。"""
    if not name:
        return "未知"
    for brand, pat in (brand_map or {}).items():
        try:
            if re.search(str(pat), name, re.I):
                return brand
        except re.error:
            continue
    return "其他"


def main():
    ap = argparse.ArgumentParser(description="生成核对用 contact sheet")
    ap.add_argument("--preset", required=True,
                    help="品类预设名，如 tv75_science")
    ap.add_argument("--input", default=None,
                    help="models.json 路径（默认取 <out-dir>/<output.models_json>）")
    ap.add_argument("out_dir_pos", nargs="?", default=None,
                    help="输出目录（位置参数，兼容旧调用）")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    cfg = cfgmod.load_config(args.preset)
    out = cfg.get("output", {})
    out_dir = args.out_dir or args.out_dir_pos or "output"
    models_path = args.input or os.path.join(
        out_dir, out.get("models_json", "models.json"))
    missing_label = cfg.get("render", {}).get("missing_label", "未提取")
    brands = cfg.get("identity", {}).get("brand_map", {})
    field_order = cfg.get("table", {}).get("field_order", [])

    if not os.path.exists(models_path):
        print(f"错误：找不到 {models_path}（请先跑 06 生成参数）", file=sys.stderr)
        sys.exit(1)

    with open(models_path, encoding="utf-8") as f:
        models = json.load(f)
    print(f"载入 {len(models)} 个机型", flush=True)

    # 按品牌分组，保持时间顺序
    by_brand = defaultdict(list)
    for m in models:
        by_brand[brand_of(m.get("brand"), brands)].append(m)

    font_title = load_font(26)
    font_body = load_font(19)
    font_small = load_font(16)

    batches = []
    for brand, items in by_brand.items():
        items.sort(key=lambda x: x["first_seen"])
        for i in range(0, len(items), BATCH_SIZE):
            batches.append((brand, items[i:i + BATCH_SIZE]))

    print(f"分为 {len(batches)} 批", flush=True)

    for bi, (brand, items) in enumerate(batches, 1):
        # 布局：2 列 x N 行
        cols = 2
        rows = (len(items) + cols - 1) // cols

        canvas = Image.new("RGB", (cols * CELL_W, rows * CELL_H + HEAD_H),
                           (250, 250, 252))
        draw = ImageDraw.Draw(canvas)
        draw.text((24, 20), f"核对批次 {bi} —— {brand}（{len(items)} 台）",
                  font=font_title, fill=(20, 20, 30))

        for idx, m in enumerate(items):
            r, c = idx // cols, idx % cols
            x0 = c * CELL_W + 8
            y0 = HEAD_H + r * CELL_H + 8
            x1 = x0 + CELL_W - 16
            y1 = y0 + CELL_H - 16
            draw.rectangle([x0, y0, x1, y1], outline=(210, 214, 220), width=2)

            # 左侧：参数卡图片
            # frame_path 保存在 params 各字段里（见 06_parse.py），
            # 取第一个带路径的字段作为该机型的代表帧
            rel = ""
            for pv in m.get("params", {}).values():
                if pv.get("frame_path"):
                    rel = pv["frame_path"]
                    break
            if rel:
                # 归一化分隔符：JSON 里存的是 Windows 反斜杠
                rel_norm = rel.replace("\\", "/")
                fp = os.path.join(out_dir, *rel_norm.split("/"))
            else:
                fp = ""
            if fp and os.path.exists(fp):
                try:
                    im = Image.open(fp).convert("RGB")
                    im.thumbnail(THUMB)
                    canvas.paste(im, (x0 + 10, y0 + 42))
                except Exception as e:
                    draw.text((x0 + 10, y0 + 42), f"图片加载失败: {e}",
                              font=font_small, fill=(200, 0, 0))

            # 标题
            name = f"{m.get('brand') or '?'} {m.get('model') or '?'}"
            draw.text((x0 + 10, y0 + 10), name, font=font_body, fill=(10, 10, 20))

            # 右侧：参数列表（顺序取自 table.field_order）
            p = m["params"]
            draw.text((x0 + 645, y0 + 42), "提取结果：", font=font_body,
                      fill=(30, 90, 180))
            ty = y0 + 74
            for k in field_order:
                if k in p:
                    v = p[k]
                    val = f"{v['value']}{v.get('unit','')}"
                    draw.text((x0 + 645, ty), f"{k}：{val}", font=font_body,
                              fill=(30, 30, 40))
                    ty += 27
                else:
                    draw.text((x0 + 645, ty), f"{k}：{missing_label}",
                              font=font_small, fill=(190, 195, 205))
                    ty += 24

            # 备注：放在左图下方
            # 原实现放在右列底部（y1-130），字段列表增至 15 项后会压住最后一行
            ny = y0 + 390
            for nt in m.get("notes", [])[:3]:
                txt = nt.get("note_text", "")[:36]
                if not txt:
                    continue
                draw.text((x0 + 12, ny), "※ " + txt, font=font_small,
                          fill=(190, 120, 0))
                ny += 20

            # 冲突提示
            if m.get("conflicts"):
                draw.text((x0 + 10, y1 - 26),
                          f"⚠ {len(m['conflicts'])} 处数值冲突，需人工确认",
                          font=font_small, fill=(220, 0, 0))

            draw.text((x0 + CELL_W - 200, y0 + 10), f"@{m['first_seen']:.0f}s",
                      font=font_small, fill=(140, 145, 155))

        out_path = os.path.join(
            out_dir,
            f"{out.get('contact_sheet_prefix', 'contact_sheet')}_{bi}_{brand}.jpg")
        canvas.save(out_path, quality=90)
        print(f"输出: {out_path}", flush=True)


if __name__ == "__main__":
    main()
