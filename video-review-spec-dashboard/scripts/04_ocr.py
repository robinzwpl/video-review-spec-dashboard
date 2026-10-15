# -*- coding: utf-8 -*-
"""
OCR 增强版：针对实际画面的预处理 + 分区域识别。

实测发现的问题与对策：
1. 参数文字压在花哨背景上（金色羽饰等）-> 分区域识别 + 对比度增强
2. 字幕固定在底部、白字黑描边 -> 单独裁切底部区域，识别率大幅提升
3. 左侧常有品牌水印混在参数里 -> 靠坐标过滤掉边缘窄条

区域坐标全部来自配置（config/default.yaml 的 ocr.regions 放通用区，
品类预设放专属区如底部横排栏分段），不在代码里写死。

用法：
    python 04_ocr.py --out-dir output [--preset tv75_science] [--no-enhance]
    python 04_ocr.py output                  # 位置参数，兼容旧调用

不给 --preset 时只识别通用区（card_main + subtitle），用于新视频的第一遍探查；
填好 preset 后需要带 --preset 再跑一遍，才会得到底部栏的 region 标注。
"""
import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image, ImageEnhance

from lib import config as cfgmod


def build_regions(cfg, width, height):
    """
    按配置构建要识别的区域列表，返回 [(名称, x1, y1, x2, y2)]（像素坐标）。

    顺序由配置里的 order 决定，不依赖 YAML 书写顺序——
    两层配置合并后键的排列是「默认在前、预设在后」，靠书写顺序会乱。

    像素换算用 int() 截断（不是 round）：历史上就是这样算的，
    改成 round 会让所有框偏移 1 像素，导致与既有 OCR 产物对不上。
    """
    regions = cfg.get("ocr", {}).get("regions", {})
    items = sorted(regions.items(), key=lambda kv: kv[1].get("order", 50))
    out = []
    for name, r in items:
        rx1, ry1, rx2, ry2 = r["box"]
        out.append((name,
                    int(width * rx1), int(height * ry1),
                    int(width * rx2), int(height * ry2)))
    return out


def preprocess(img, enhance=True):
    """
    图像预处理：增强对比度，让压在花哨背景上的白字更清晰。
    """
    if not enhance:
        return img
    # 轻度锐化 + 对比度增强
    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    return img


def run_ocr(frames, out_dir, cfg=None, do_enhance=True,
            output_name="frames_ocr.json", write_dir=None):
    """
    对每个关键帧跑 OCR，多区域识别。

    :param out_dir: 关键帧所在目录（frame_path 是相对它的相对路径）
    :param write_dir: 结果写入目录，默认与 out_dir 相同
    """
    if cfg is None:
        cfg = cfgmod.load_base()
    from rapidocr_onnxruntime import RapidOCR

    print("正在加载 OCR 模型...", flush=True)
    t0 = time.time()
    engine = RapidOCR()
    print(f"OCR 模型加载完成，耗时 {time.time()-t0:.1f}s", flush=True)

    results = []
    t0 = time.time()
    # 缓存图片，避免重复读取
    img_cache = {}

    for i, fr in enumerate(frames):
        abs_path = os.path.join(out_dir, fr["frame_path"])
        if not os.path.exists(abs_path):
            continue

        try:
            if abs_path in img_cache:
                img = img_cache[abs_path]
            else:
                img = Image.open(abs_path).convert("RGB")
                img_cache.clear()      # 只保留最近一张
                img_cache[abs_path] = img
        except Exception as e:
            print(f"  读取帧失败 {abs_path}: {e}", flush=True)
            continue

        W, H = img.size
        all_texts = []

        for region_name, x1, y1, x2, y2 in build_regions(cfg, W, H):
            crop = img.crop((x1, y1, x2, y2))
            crop = preprocess(crop, do_enhance)

            try:
                # 注意：RapidOCR 只接受 路径/numpy/bytes，不接受 PIL Image 对象。
                # 传 PIL 会抛 LoadImageError，若被 except 吞掉会表现为「识别到 0 个框」。
                ocr_out, _ = engine(np.array(crop), box_thresh=0.35)
            except Exception as e:
                print(f"  帧 {fr['timestamp']}s 区域 {region_name} OCR 异常: {e}",
                      flush=True)
                ocr_out = None

            if not ocr_out:
                continue

            for line in ocr_out:
                box, text, score = line[0], line[1], line[2]
                # score 在本版本中返回字符串，需转 float
                try:
                    score_f = float(score)
                except (TypeError, ValueError):
                    score_f = 0.0
                # 把裁切区域内的坐标换算回全图坐标
                abs_box = [[round(x + x1, 1), round(y + y1, 1)] for x, y in box]
                all_texts.append({
                    "text": text,
                    "score": round(score_f, 3),
                    "box": abs_box,
                    "region": region_name,
                })

        results.append({
            "index": fr["index"],
            "timestamp": fr["timestamp"],
            "frame_path": fr["frame_path"],
            "texts": all_texts,
        })

        if (i + 1) % 50 == 0:
            print(f"  OCR 进度 {i+1}/{len(frames)}，用时 {time.time()-t0:.0f}s", flush=True)

    ocr_path = os.path.join(write_dir or out_dir, output_name)
    with open(ocr_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total_texts = sum(len(r["texts"]) for r in results)
    nonempty = sum(1 for r in results if r["texts"])
    print(f"OCR 完成: {len(results)} 帧，{nonempty} 帧有文字，"
          f"共 {total_texts} 个文本框，耗时 {time.time()-t0:.0f}s", flush=True)
    print(f"输出: {ocr_path}", flush=True)
    return results


def main():
    ap = argparse.ArgumentParser(description="分区域 OCR（坐标来自配置）")
    ap.add_argument("out_dir_pos", nargs="?", default=None,
                    help="输出目录（位置参数，兼容旧调用）")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--preset", default=None,
                    help="品类预设名；不给则只识别通用区（新视频探查用）")
    ap.add_argument("--input", default=None, help="keyframes.json 路径")
    ap.add_argument("--output", default=None, help="输出 frames_ocr.json 路径")
    ap.add_argument("--no-enhance", action="store_true",
                    help="关闭对比度/锐化增强")
    args = ap.parse_args()

    out_dir = args.out_dir or args.out_dir_pos or "output"
    cfg = (cfgmod.load_config(args.preset) if args.preset
           else cfgmod.load_base())
    out = cfg.get("output", {})

    if not args.preset:
        print("提示: 未指定 --preset，只识别通用区（card_main / subtitle）；"
              "填好预设后需带 --preset 再跑一遍，才会得到底部栏的 region 标注",
              flush=True)

    meta_path = args.input or os.path.join(
        out_dir, out.get("keyframes_json", "keyframes.json"))
    with open(meta_path, encoding="utf-8") as f:
        frames = json.load(f)
    print(f"载入关键帧清单: {len(frames)} 帧", flush=True)

    if args.output:
        # 帧始终从 out_dir 读，结果写到 --output 指定的路径
        run_ocr(frames, out_dir, cfg, do_enhance=not args.no_enhance,
                output_name=os.path.basename(args.output),
                write_dir=os.path.dirname(os.path.abspath(args.output)))
    else:
        run_ocr(frames, out_dir, cfg, do_enhance=not args.no_enhance,
                output_name=out.get("frames_ocr_json", "frames_ocr.json"))


if __name__ == "__main__":
    main()
