# -*- coding: utf-8 -*-
"""
生成核对用contact sheet（按品牌分批）。

用途：让用户逐批核对 OCR 提取的参数是否与画面一致。
输出：output/contact_sheet_1_品牌.jpg 等
"""
import os
import re
import sys
import json
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont


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


def brand_of(name):
    if not name:
        return "未知"
    for b in ["TCL", "雷鸟", "海信", "创维", "vidda", "小米", "红米"]:
        if b in name or (b == "vidda" and name.lower().find("vidda") >= 0):
            return b
    return "其他"


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "output"
    models_path = os.path.join(out_dir, "tv_models.json")

    with open(models_path, encoding="utf-8") as f:
        models = json.load(f)
    print(f"载入 {len(models)} 个机型", flush=True)

    # 按品牌分组，保持时间顺序
    by_brand = defaultdict(list)
    for m in models:
        by_brand[brand_of(m.get("brand"))].append(m)

    font_title = load_font(26)
    font_body = load_font(19)
    font_small = load_font(16)

    # 每批最多 6 台
    batches = []
    for brand, items in by_brand.items():
        items.sort(key=lambda x: x["first_seen"])
        for i in range(0, len(items), 6):
            batches.append((brand, items[i:i + 6]))

    print(f"分为 {len(batches)} 批", flush=True)

    for bi, (brand, items) in enumerate(batches, 1):
        # 布局：2 列 x N 行
        cols = 2
        rows = (len(items) + cols - 1) // cols
        cell_w, cell_h = 960, 620
        head_h = 70

        canvas = Image.new("RGB", (cols * cell_w, rows * cell_h + head_h),
                           (250, 250, 252))
        draw = ImageDraw.Draw(canvas)
        draw.text((24, 20), f"核对批次 {bi} —— {brand}（{len(items)} 台）",
                  font=font_title, fill=(20, 20, 30))

        for idx, m in enumerate(items):
            r, c = idx // cols, idx % cols
            x0 = c * cell_w + 8
            y0 = head_h + r * cell_h + 8
            x1 = x0 + cell_w - 16
            y1 = y0 + cell_h - 16
            draw.rectangle([x0, y0, x1, y1], outline=(210, 214, 220), width=2)

            # 左侧：参数卡图片
            # frame_path 保存在 params 各字段里（见 05_parse_cards.py），
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
                    im.thumbnail((620, 340))
                    canvas.paste(im, (x0 + 10, y0 + 42))
                except Exception as e:
                    draw.text((x0 + 10, y0 + 42), f"图片加载失败: {e}",
                              font=font_small, fill=(200, 0, 0))

            # 标题
            name = f"{m.get('brand') or '?'} {m.get('model') or '?'}"
            draw.text((x0 + 10, y0 + 10), name, font=font_body, fill=(10, 10, 20))

            # 右侧：参数列表
            p = m["params"]
            ty = y0 + 400
            draw.text((x0 + 645, y0 + 42), "提取结果：", font=font_body,
                      fill=(30, 90, 180))
            ty = y0 + 74
            order = ["价格", "屏幕", "分区数", "峰值亮度", "刷新率", "色域",
                     "内存", "存储", "处理器", "HDMI2.1数量"]
            for k in order:
                if k in p:
                    v = p[k]
                    val = f"{v['value']}{v.get('unit','')}"
                    draw.text((x0 + 645, ty), f"{k}：{val}", font=font_body,
                              fill=(30, 30, 40))
                    ty += 27
                else:
                    draw.text((x0 + 645, ty), f"{k}：未提取", font=font_small,
                              fill=(190, 195, 205))
                    ty += 24

            # 备注
            ny = y1 - 130
            for nt in m.get("notes", [])[:3]:
                txt = nt.get("note_text", "")[:60]
                draw.text((x0 + 645, ny), "※ " + txt, font=font_small,
                          fill=(190, 120, 0))
                ny += 22

            # 冲突提示
            if m.get("conflicts"):
                draw.text((x0 + 10, y1 - 26),
                          f"⚠ {len(m['conflicts'])} 处数值冲突，需人工确认",
                          font=font_small, fill=(220, 0, 0))

            draw.text((x0 + 10, y1 - 26), "", font=font_small, fill=(0, 0, 0))
            draw.text((x0 + cell_w - 200, y0 + 10), f"@{m['first_seen']:.0f}s",
                      font=font_small, fill=(140, 145, 155))

        out_path = os.path.join(out_dir, f"contact_sheet_{bi}_{brand}.jpg")
        canvas.save(out_path, quality=90)
        print(f"输出: {out_path}", flush=True)


if __name__ == "__main__":
    main()
