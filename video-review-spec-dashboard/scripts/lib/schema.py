# -*- coding: utf-8 -*-
"""
字段值解析：按 preset 中声明的 type 分派到对应 handler。

每种 type 对应一类数值形态（金额、区间、百分比、枚举……）。
换品类时只需在 preset 里为字段挑选合适的 type，不必改代码。

铁律 M8：解析不出就返回 None，绝不填 0、绝不推测填充。
"""
import re


def _clean(d):
    """去掉值为 None 的键，避免输出里出现 null 噪音。"""
    return {k: v for k, v in d.items() if v is not None}


def _money(v, fd):
    """价格：支持 ¥ 前缀与千分位。"""
    m = re.search(r"[¥￥]?\s*([\d,]+(?:\.\d+)?)", v)
    if not m:
        return None
    return {"value": float(m.group(1).replace(",", "")),
            "unit": fd.get("unit", "元"), "note": fd.get("note")}


def _enum_map(v, fd):
    """枚举型：按 preset 里的 pattern -> name 词典匹配（如屏幕类型）。"""
    for p in fd.get("patterns", []):
        if re.search(p["pattern"], v, re.I):
            return {"value": p["name"], "unit": fd.get("unit", "")}
    return None


def _zones(v, fd):
    """
    背光分区数。

    三种形态：
      无分区声明 -> 记 0；精确值 -> 整数；区间 -> 取上限并标记非精确
    """
    unit = fd.get("unit", "区")
    notes = fd.get("notes", {})
    if re.search(fd.get("no_zone_pattern", "无独立背光分区|无光分区|无分区"), v):
        return {"value": 0, "unit": unit, "exact": True, "zone_type": "无分区",
                "note": notes.get("none")}
    ztype = None
    for zt in fd.get("zone_types", []):
        if re.search(zt, v):
            ztype = zt
            break
    m = re.search(r"(\d{3,5})\s*个?", v)
    if m:
        return {"value": int(m.group(1)), "unit": unit, "exact": True,
                "zone_type": ztype,
                "note": (notes.get("exact") or "").format(zone_type=ztype)}
    m = re.search(r"(\d{2,5})\s*[-—~至]\s*(\d{2,5})\s*级", v)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return {"value": hi, "value_min": lo, "unit": unit, "exact": False,
                "zone_type": ztype,
                "note": (notes.get("range") or "").format(lo=lo, hi=hi)}
    return None


def _zones_named(v, fd):
    """品牌专属控光口径（如海信玲珑控色区），与背光分区不可混算。"""
    m = re.search(r"(\d{2,5})\s*个", v)
    if m:
        return {"value": int(m.group(1)), "unit": fd.get("unit", "个控色区"),
                "note": fd.get("note")}
    if re.search(r"控色区", v):
        return {"value": v, "unit": ""}
    return None


def _range_num(v, fd):
    """亮度一类：可能是区间（取上限）也可能是单值。"""
    unit = fd.get("unit", "nit")
    notes = fd.get("notes", {})
    m = re.search(r"(\d{3,5})\s*[-—~至]\s*(\d{3,5})", v)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return {"value": hi, "value_min": lo, "unit": unit, "is_range": True,
                "note": (notes.get("range") or "").format(lo=lo, hi=hi)}
    m = re.search(r"(\d{3,5})", v)
    if m:
        return {"value": int(m.group(1)), "unit": unit, "is_range": False,
                "note": notes.get("single")}
    return None


def _refresh_hz(v, fd):
    """刷新率：区分原生 4K 与降分辨率模式下的高刷。"""
    notes = fd.get("notes", {})
    m = re.search(r"4K\s*(\d{2,3})\s*Hz", v, re.I)
    if m:
        return {"value": int(m.group(1)), "unit": "Hz", "is_native": True,
                "note": notes.get("native")}
    m = re.search(r"(\d{2,3})\s*Hz", v, re.I)
    if m:
        return {"value": int(m.group(1)), "unit": "Hz", "is_native": False,
                "note": notes.get("non_native")}
    return None


def _percent_std(v, fd):
    """
    色域：不同色域标准分列，不可混算。

    覆盖率超过 100% 时不擅自改写成 100 —— 保留原值并标记需人工核对，
    因为既可能是 OCR 误识，也可能是画面本身就那么标。
    """
    notes = fd.get("notes", {})
    for std in fd.get("standards", []):
        m = re.search(std["pattern"], v, re.I)
        if not m:
            continue
        val = float(m.group(1))
        name = std["name"]
        if val > 100:
            return {"value": val, "unit": name, "ocr_error": True,
                    "note": (notes.get("over100") or "").format(val=val)}
        note = (notes.get("srgb") if name == "% sRGB"
                else (notes.get("default") or "").format(std=name))
        return {"value": val, "unit": name, "standard": name, "note": note}
    return None


def _capacity_gb(v, fd):
    """内存 / 存储。"""
    m = re.search(r"(\d+)\s*GB", v, re.I)
    if not m:
        return None
    return {"value": int(m.group(1)), "unit": fd.get("unit", "GB")}


def _cpu_text(v, fd):
    """处理器型号（如 四核A73、双核A55+A73）。"""
    m = re.search(r"((?:双核|单核|四核|五核|八核|四核A|双核A)?\s*[A-Z]?\d{2,3}"
                  r"\s*(?:\+\s*(?:双核|单核|四核|五核|八核)?\s*[A-Z]?\d{0,3})*)", v)
    if m and m.group(1).strip():
        return {"value": m.group(1).strip(), "unit": fd.get("unit", "")}
    return None


def _size_inch(v, fd):
    """屏幕尺寸。"""
    m = re.search(r"(\d{2})\s*(?:英寸|寸)", v)
    if not m:
        return None
    return {"value": int(m.group(1)), "unit": fd.get("unit", "英寸")}


def _count_by_version(v, fd):
    """按版本号分别计数的接口数量（如 HDMI 2.1 / 2.0 各几个）。"""
    for ver in fd.get("versions", []):
        pat = r"HDMI\s*" + re.escape(ver) + r"\D{0,8}?(\d+)\s*个?"
        m = re.search(pat, v, re.I)
        if m:
            return {"value": int(m.group(1)), "unit": fd.get("unit", "个"),
                    "hdmi_ver": ver}
    return None


def _int_unit(v, fd):
    """「N 个」形态的计数。"""
    m = re.search(r"(\d+)\s*个", v)
    if not m:
        return None
    return {"value": int(m.group(1)), "unit": fd.get("unit", "个")}


def _text_short(v, fd):
    """纯文本字段：不做结构化，交给下层的短文本兜底处理。"""
    return None


HANDLERS = {
    "money": _money,
    "enum_map": _enum_map,
    "zones": _zones,
    "zones_named": _zones_named,
    "range_num": _range_num,
    "refresh_hz": _refresh_hz,
    "percent_std": _percent_std,
    "capacity_gb": _capacity_gb,
    "cpu_text": _cpu_text,
    "size_inch": _size_inch,
    "count_by_version": _count_by_version,
    "int_unit": _int_unit,
    "text_short": _text_short,
}

# 只有纯文本字段走「短文本原样收录」兜底。
# 有专门 handler 的类型解析不出就是解析不出（铁律 M8），
# 不能用原文兜底，否则会混入非结构化文本污染数值字段。
FALLBACK_TYPES = {"text_short"}


def parse_value(v, fd, cfg, source="OCR参数卡"):
    """
    解析单个字段值。

    :param v: 待解析的文本（已做 OCR 修正）
    :param fd: 字段定义（来自 preset 的 fields）
    :param cfg: 合并后的完整配置
    :param source: 来源标记，写进结果的 source 字段以便溯源
    :return: dict 或 None（None 表示解析不出，不填充）
    """
    v = (v or "").strip()
    if not v:
        return None

    ftype = fd.get("type")
    handler = HANDLERS.get(ftype)
    if handler is None:
        raise ValueError(f"未知的字段解析类型: {ftype}（字段 {fd.get('name')}）")

    res = handler(v, fd)

    # 仅纯文本字段做短文本兜底，数值类字段解析不出即放弃
    if res is None:
        if ftype not in FALLBACK_TYPES:
            return None
        max_len = cfg.get("parse", {}).get("fallback_text_max_len", 24)
        if len(v) > max_len:
            return None
        res = {"value": v, "unit": ""}

    res["raw"] = v
    res["source"] = source
    return _clean(res)
