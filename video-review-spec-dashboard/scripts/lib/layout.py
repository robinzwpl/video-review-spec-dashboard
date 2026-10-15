# -*- coding: utf-8 -*-
"""
画面几何：文本框坐标处理与「标签-值」配对。

铁律 M4：先按 |Δy| 取最近行，同行内再按 x 拼接。
反例教训：早期实现按 x 排序取最近，误取到下一行的补充说明，
          曾导致 5 台机型的刷新率全部解析错误（144Hz 被记成 60Hz 等）。
"""
import re


def y_center(box):
    """文本框纵向中心。"""
    ys = [p[1] for p in box]
    return sum(ys) / len(ys)


def x_left(box):
    """文本框左边界。"""
    return min(p[0] for p in box)


def apply_ocr_fixes(text, ocr_fixes):
    """按配置里的字面替换表与正则替换表修正 OCR 误识。"""
    t = text
    for item in (ocr_fixes or {}).get("literal", []):
        t = t.replace(item["from"], item["to"])
    for item in (ocr_fixes or {}).get("regex", []):
        flags = re.I if item.get("ignore_case", True) else 0
        t = re.sub(item["pattern"], item["repl"], t, flags=flags)
    return t


def build_items(frame_texts, ocr_fixes):
    """
    把一帧的 OCR 文本框整理成统一结构。

    :param frame_texts: frames_ocr.json 中单帧的 texts 列表
    :return: [{"text", "score", "yc", "xl", "region"}, ...]
    """
    items = []
    for t in frame_texts:
        items.append({
            "text": apply_ocr_fixes(t["text"], ocr_fixes),
            "score": t.get("score", 0),
            "yc": y_center(t["box"]),
            "xl": x_left(t["box"]),
            # region 标注来源区域，底部横排栏靠它区分字段归属
            "region": t.get("region", ""),
        })
    return items


def classify_label(text, label_idx):
    """
    判断文本框是否为字段标签，返回字段名或 None。

    匹配规则（与原实现一致）：
      1. 去掉尾部冒号/空白/逗号后，完全等于别名
      2. 以前缀匹配别名，且文本不比别名长 4 个字以上（兼容「运行内存/存储」这类复合标签）
    """
    t = re.sub(r"[:：\s,，/、]+$", "", text.strip())
    t_l = t.lower()
    for alias, field in label_idx:
        if t_l == alias:
            return field
        if t_l.startswith(alias) and len(t) <= len(alias) + 4:
            return field
    return None


def pair_values(items, labels, geometry, label_idx):
    """
    为每个标签找它对应的值文本。

    :param items: build_items 的输出
    :param labels: 标签项列表（每项含 xl/yc/field）
    :param geometry: 配置中的 geometry 段（dx_min / dy_max / row_tol）
    :return: [(label_item, value_text), ...]
    """
    dx_min = geometry.get("dx_min", 40)
    dy_max = geometry.get("dy_max", 42)
    row_tol = geometry.get("row_tol", 8)

    pairs = []
    for lb in labels:
        cands = [
            it for it in items
            if it["xl"] > lb["xl"] + dx_min
            and abs(it["yc"] - lb["yc"]) <= dy_max
            and not classify_label(it["text"], label_idx)
        ]
        if not cands:
            continue
        # 按 y 距离优先（关键：避免取到下一行的补充说明）
        cands.sort(key=lambda x: (abs(x["yc"] - lb["yc"]), x["xl"]))
        nearest = abs(cands[0]["yc"] - lb["yc"])
        same_row = [c for c in cands if abs(c["yc"] - lb["yc"]) <= nearest + row_tol]
        same_row.sort(key=lambda x: x["xl"])
        pairs.append((lb, " ".join(c["text"] for c in same_row)))
    return pairs
