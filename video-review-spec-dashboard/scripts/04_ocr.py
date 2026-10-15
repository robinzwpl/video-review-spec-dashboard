# -*- coding: utf-8 -*-
"""
OCR 增强版：针对实际画面的预处理 + 分区域识别。

实测发现的问题与对策：
1. 参数文字压在花哨背景上（金色羽饰等）-> 分区域识别 + 对比度增强
2. 字幕固定在底部、白字黑描边 -> 单独裁切底部区域，识别率大幅提升
3. 左侧常有品牌水印混在参数里 -> 靠坐标过滤掉边缘窄条

策略：
- 整帧识别一遍（抓画面中央的参数表/贴纸）
- 底部字幕条单独裁切再识别一遍（抓口播字幕，拿章节结构）
"""
import os
import sys
import json
import time

import numpy as np
from PIL import Image, ImageEnhance


# 画面分区（基于 1920x1080 观察，可按实际分辨率等比缩放）
def get_regions(width, height):
    """
    返回要识别的区域列表。坐标格式: (名称, x1比例, y1比例, x2比例, y2比例)

    实测画面有两种参数卡版式（基于 1920x1080 逐帧扫描确定）：
      A) 主区竖排：标签/值在 y 240-860，x 480-1400
         （屏幕 / 背光分区 / 亮度范围 / 原生刷新 / 色域）
      B) 底部横排栏：y 920-1005，四组字段
         标签行 y≈920-945，数值行 y≈960-1005

    **底部横排栏与口播字幕位置重叠**（字幕居中约 x 600-1340），
    整行识别会被字幕污染（实测得到
    "2GB/64GB第三台合 Vidda>钢SM8ni四核A55"）。
    因此底部改为**按实测 x 范围分段识别，跳过字幕所在的中间段**：
      组1 x 150-560  运行内存/存储 -> 实测干净输出['2GB','64GB']
      组2 x 620-900HDMI 2.1/2.0   -> 常被字幕压住
      组3 x 960-1180  发声单元      -> 常被字幕压住
      组4 x 1340-1800 处理器        -> 实测干净输出['四核A55']
    被字幕遮挡的组若识别不到，保留「未提取」，不推测填充。
    """
    return [
        # 参数卡主区：屏幕/分区/亮度/刷新/色域
        ("card_main", 0.02, 0.05, 0.98, 0.86),
        # 底部横排栏 · 标签行
        ("footer_label", 0.02, 0.845, 0.98, 0.88),
        # 底部横排栏 · 数值行四段（避开字幕居中区）
        ("footer_v1", 0.078, 0.883, 0.292, 0.935),   # x150-560  内存/存储
        ("footer_v2", 0.323, 0.883, 0.469, 0.935),   # x620-900  HDMI
        ("footer_v3", 0.500, 0.883, 0.615, 0.935),   # x960-1180 发声单元
        ("footer_v4", 0.698, 0.883, 0.938, 0.935),   # x1340-1800 处理器
        # 口播字幕（单独识别用于章节定位）
        ("subtitle", 0.02, 0.86, 0.98, 0.999),
    ]


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


def split_footer(crop, n=4):
    """
    底部横排数值行按x 四等分切开。

    实测该行为「运行内存/存储 | HDMI2.1 | 发声单元 | 处理器」四组等距排列，
    但 RapidOCR 会把整行识别成一个文本框并相互粘连
    （实测得到 "2GB64GBEA00aHSnoA55"，其中 EA00aH 是 "HDMI2.0 4个" 的误识）。
    按 x 切分后逐段识别，可显著降低粘连导致的误识。
    """
    w, h = crop.size
    # 左右各留 1% 边距，避免切到相邻字段边缘
    m = int(w * 0.01)
    seg_w = (w - 2 * m) // n
    out = []
    for i in range(n):
        x0 = m + i * seg_w
        x1 = m + (i + 1) * seg_w if i < n - 1 else w - m
        out.append(crop.crop((x0, 0, x1, h)))
    return out


def run_ocr(frames, out_dir, do_enhance=True):
    """对每个关键帧跑 OCR，多区域识别。"""
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

        for region_name, rx1, ry1, rx2, ry2 in get_regions(W, H):
            x1, y1 = int(W * rx1), int(H * ry1)
            x2, y2 = int(W * rx2), int(H * ry2)
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

    ocr_path = os.path.join(out_dir, "frames_ocr.json")
    with open(ocr_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total_texts = sum(len(r["texts"]) for r in results)
    nonempty = sum(1 for r in results if r["texts"])
    print(f"OCR 完成: {len(results)} 帧，{nonempty} 帧有文字，"
          f"共 {total_texts} 个文本框，耗时 {time.time()-t0:.0f}s", flush=True)
    print(f"输出: {ocr_path}", flush=True)
    return results


def main():
    out_dir = sys.argv[1]
    meta_path = os.path.join(out_dir, "keyframes.json")

    with open(meta_path, encoding="utf-8") as f:
        frames = json.load(f)
    print(f"载入关键帧清单: {len(frames)} 帧", flush=True)

    run_ocr(frames, out_dir, do_enhance=True)


if __name__ == "__main__":
    main()
