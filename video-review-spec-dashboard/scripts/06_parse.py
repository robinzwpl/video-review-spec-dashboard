# -*- coding: utf-8 -*-
"""
参数卡解析 v3：全字段提取 + 特殊参数 + 干扰帧排除。

相比 v2 的改动：
1. 色域支持四种标准（sRGB / DCI-P3 / BT.2020 / BT.709），分列不混算
2. 型号负向规则：命中色域标准词表（DCI/P3/BT/2020/709/sRGB/HDR）的候选丢弃
3. 品牌表新增华为；支持「纯英文词+数字」型号（Vision智慧屏6）
4. 全字段提取：价格/屏幕/分区(含类型)/亮度区间/原生刷新+倍频/色域/内存/存储/
   处理器/HDMI2.1/HDMI2.0/发声单元/尺寸
5. 特殊参数独立字段（玲珑控色区、万象分区、画质芯片等）
6. 排除开篇「32款一起拆开看」多机型同屏干扰帧（first_seen < 120s 不参与解析）
7. 兼容两种参数卡版式：主区竖排 + 底部横排
"""
import os
import re
import sys
import json
from collections import defaultdict


# ==================== 干扰帧阈值 ====================
# 开篇 15.8-18.3s 为「32款电视一起拆开看」总览页，多机型卡片叠同屏，
# 文本框混杂会导致机型-参数错配。120s 之前的帧不参与参数解析。
INTERFERENCE_START = 120.0


# ==================== 品牌 ====================
BRAND_PATTERNS = {
    "雷鸟": r"雷鸟|Falcon",
    "创维": r"创维|Skyworth",
    "海信": r"海信|Hisense",
    "华为": r"华为|HUAWEI",
    "小米": r"小米|Xiaomi",
    "红米": r"红米|Redmi|REDMI",
    "TCL": r"TCL",
    "vidda": r"vidda|VIDDA|Vidda",
}

# 标题行剔除词（栏目字样/总数说明，不是型号）
TITLE_NOISE = re.compile(
    r"^(绝对值|32款|32台|一起拆开看|参考价|售价|热卖|推荐|参数|"
    r"全屏|画质|高刷|新品|汇总|对比|横评|乾貝)")

# 型号负向词表：命中则该候选不是型号（如把 "P3" 当成型号）
MODEL_NEGATIVE = re.compile(
    r"(DCI|P3|BT|2020|709|sRGB|SRGB|HDR|Dolby|ATMOS|绝对值|参考价)", re.I)


# ==================== 字段标签 ====================
LABEL_MAP = {
    "屏幕": "屏幕", "面板": "屏幕", "屏体": "屏幕", "软屏": "屏幕", "硬屏": "屏幕",
    "背光分区": "分区数", "分区": "分区数",
    "玲珑控色区": "控色区", "控色区": "控色区", "品牌控色区": "控色区",
    "控色": "控色区",
    "亮度范围": "峰值亮度", "亮度": "峰值亮度", "峰值亮度": "峰值亮度",
    "典型亮度": "典型亮度",
    "原生刷新": "刷新率", "刷新率": "刷新率", "刷新": "刷新率",
    "色域": "色域", "色彩覆盖": "色域",
    "运行内存": "内存", "内存": "内存",
    "存储": "存储", "硬盘": "存储", "ROM": "存储",
    "处理器": "处理器", "芯片": "处理器", "cpu": "处理器", "CPU": "处理器",
    "尺寸": "屏幕尺寸", "英寸": "屏幕尺寸", "屏幕尺寸": "屏幕尺寸",
    "参考价": "价格", "价格": "价格", "售价": "价格", "到手价": "价格",
    "hdm": "HDMI", "接口": "HDMI",
    "发声单元": "发声单元", "声道": "声道", "音响": "音频", "扬声器": "发声单元",
    "游戏": "游戏特性", "gam": "游戏特性",
    "hdr": "HDR", "认证": "认证",
    "控色区": "控色区", "画质": "画质技术", "技术": "画质技术",
}

# 特殊参数词典：(正则, 名称, 类型, 归属)
SPECIAL_PATTERNS = [
    (r"玲珑控色区", "玲珑控色区", "画质技术", "海信"),
    (r"万象分区", "万象分区", "分区类型", "TCL/雷鸟"),
    (r"超级分区", "超级分区", "分区类型", "创维"),
    (r"变色龙AI画质芯片", "变色龙AI画质芯片", "画质芯片", "创维"),
    (r"QD-?Mini\s*LED", "QD-Mini LED", "屏幕技术", "通用"),
    (r"SQD-?Mini\s*LED", "SQD-Mini LED", "屏幕技术", "TCL"),
    (r"Mini\s*LED", "Mini LED", "背光技术", "通用"),
    (r"墨晶屏", "墨晶屏", "屏幕技术", "海信"),
    (r"极黑广角类纸屏|类纸屏", "极黑类纸屏", "屏幕技术", "创维"),
    (r"黑曜屏", "黑曜屏", "屏幕技术", "vidda"),
    (r"晶粹高色阻屏|高色阻屏", "高色阻屏", "屏幕技术", "TCL"),
    (r"直下式\s*/?\s*DLED|直下式|DLED", "直下式DLED", "背光技术", "通用"),
    (r"VA\s*软屏", "VA软屏", "屏幕类型", "通用"),
    (r"ADS|硬屏", "硬屏", "屏幕类型", "通用"),
    (r"量子点|超级量子点", "量子点", "屏幕技术", "通用"),
]


def y_center(box):
    ys = [p[1] for p in box]
    return sum(ys) / len(ys)


def x_left(box):
    return min(p[0] for p in box)


def fix_ocr_text(t):
    """修正 OCR 常见误识。"""
    t = t.replace("HDM12.1", "HDMI2.1").replace("HDM12.0", "HDMI2.0")
    t = t.replace("HDM1 2.1", "HDMI2.1").replace("HDMI 2.1", "HDMI2.1")
    t = t.replace("HDMI 2.0", "HDMI2.0")
    t = re.sub(r"4K\s*(\d+)\s*Hz", r"4K\1Hz", t, flags=re.I)
    t = re.sub(r"(\d+)\s*赫兹", r"\1Hz", t)
    t = t.replace("，", ",").replace("：", ":")
    t = re.sub(r"\bnits?\b", "nits", t, flags=re.I)
    t = re.sub(r"\bSRGB\b", "sRGB", t)
    return t


def classify_label(text):
    """判断文本框是否为字段标签。"""
    t = re.sub(r"[:：\s,，/、]+$", "", text.strip())
    t_l = t.lower()
    for kw, field in LABEL_MAP.items():
        k = kw.lower()
        if t_l == k:
            return field
        # 允许"运行内存/存储"这类复合标签
        if t_l.startswith(k) and len(t) <= len(k) + 4:
            return field
    return None


def extract_brand_model(text):
    """
    提取品牌与型号。

    实测标题行形态：
        雷鸟鹏6 SE 2026   创维黑骑士 A5F+   海信小墨E5S
        Vidda小钢炮SMini  华为Vision智慧屏6  小米 S Mini LED 2026
        REDMIA75          TCL V8M          创维 A6F Ultra
    """
    t = text.strip()
    if TITLE_NOISE.match(t):
        return None, None

    brand = None
    for name, pat in BRAND_PATTERNS.items():
        if re.search(pat, t, re.I):
            brand = name
            break
    if not brand:
        return None, None

    # 去掉品牌前缀与栏目字样
    for name, pat in BRAND_PATTERNS.items():
        m = re.search(pat, t, re.I)
        if m:
            rest = t[m.end():]
            break
    rest = re.sub(r"^绝对值", "", rest)
    rest = re.split(r"参考价|￥|¥", rest)[0]
    rest = rest.strip(" ·-—:：")
    rest = re.sub(r"\b(20\d{2})\b", "", rest)      # 去年份
    rest = re.sub(r"\s+", " ", rest).strip()

    # 负向规则：命中色域标准等词表的候选不是型号
    if rest and MODEL_NEGATIVE.search(rest):
        return brand, None
    if not rest:
        return brand, None

    return brand, rest


# ==================== 字段值解析 ====================
def parse_value(field, v):
    """按字段解析值。返回 dict 或 None。"""
    v = (v or "").strip()
    if not v:
        return None

    if field == "价格":
        m = re.search(r"[¥￥]?\s*([\d,]+(?:\.\d+)?)", v)
        if m:
            return {"value": float(m.group(1).replace(",", "")), "unit": "元",
                    "raw": v, "source": "OCR参数卡",
                    "note": "参考价为国补后价格，需符合地区补贴条件"}
        return None

    if field == "屏幕":
        for pat, name in [(r"QD-?Mini\s*LED", "QD-Mini LED"),
                          (r"SQD-?Mini\s*LED", "SQD-Mini LED"),
                          (r"Mini\s*LED", "Mini LED"),
                          (r"Micro\s*LED", "Micro LED"),
                          (r"QD-?OLED", "QD-OLED"), (r"OLED", "OLED"),
                          (r"ULED", "ULED"), (r"QLED", "QLED"),
                          (r"VA\s*软屏", "VA软屏"),
                          (r"极黑广角类纸屏", "极黑类纸屏"),
                          (r"墨晶屏[\d.]*", "墨晶屏"),
                          (r"黑曜屏[\w\s]*", "黑曜屏"),
                          (r"直下式\s*/?\s*DLED", "直下式DLED"),
                          (r"直下式", "直下式"), (r"DLED", "DLED"),
                          (r"IPS", "IPS"), (r"\bVA\b", "VA"),
                          (r"ADS", "ADS"), (r"硬屏", "硬屏")]:
            if re.search(pat, v, re.I):
                return {"value": name, "unit": "", "raw": v, "source": "OCR参数卡"}
        return None

    if field == "控色区":
        # 海信专属：玲珑控色区，画面同时标注「品牌控色区口径」
        # 实测值形如 "2640个"（海信小墨E5S Pro）、"4200个"（海信E8S）
        m = re.search(r"(\d{2,5})\s*个", v)
        if m:
            return {"value": int(m.group(1)), "unit": "个控色区", "raw": v,
                    "source": "OCR参数卡",
                    "note": "玲珑控色区（海信专属口径），与背光分区算法不同，"
                            "不可与背光分区直接比较"}
        if re.search(r"控色区", v):
            return {"value": v, "unit": "", "raw": v, "source": "OCR参数卡"}
        return None

    if field == "分区数":
        if re.search(r"无独立背光分区|无光分区|无分区", v):
            return {"value": 0, "unit": "区", "raw": v, "source": "OCR参数卡",
                    "exact": True, "zone_type": "无分区",
                    "note": "无独立背光分区（侧光/直下式无控光分区），记为0"}
        # 命名类型
        ztype = None
        if re.search(r"万象分区", v):
            ztype = "万象分区"
        elif re.search(r"超级分区", v):
            ztype = "超级分区"
        elif re.search(r"独立背光分区", v):
            ztype = "独立背光分区"
        elif re.search(r"背光分区", v):
            ztype = "背光分区"
        m = re.search(r"(\d{3,5})\s*个?", v)
        if m:
            return {"value": int(m.group(1)), "unit": "区", "raw": v,
                    "source": "OCR参数卡", "exact": True, "zone_type": ztype,
                    "note": f"分区类型：{ztype}；需确认单/双/多重分区，算法不同不可直接比较"}
        m = re.search(r"(\d{2,5})\s*[-—~至]\s*(\d{2,5})\s*级", v)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            return {"value": hi, "value_min": lo, "unit": "区", "raw": v,
                    "source": "OCR参数卡", "exact": False, "zone_type": ztype,
                    "note": f"卡片标注 {lo}-{hi} 级分区区间，取上限；非精确分区数"}
        return None

    if field == "峰值亮度":
        if re.search(r"宣称", v):
            pass
        m = re.search(r"(\d{3,5})\s*[-—~至]\s*(\d{3,5})", v)
        if m:
            return {"value": int(m.group(2)), "value_min": int(m.group(1)),
                    "unit": "nit", "raw": v, "source": "OCR参数卡",
                    "is_range": True,
                    "note": f"标称区间 {m.group(1)}-{m.group(2)} nit，取上限；注意测试窗口口径"}
        m = re.search(r"(\d{3,5})", v)
        if m:
            return {"value": int(m.group(1)), "unit": "nit", "raw": v,
                    "source": "OCR参数卡", "is_range": False,
                    "note": "需注意测试窗口口径（3%/10%窗口 vs 全屏）"}
        return None

    if field == "刷新率":
        m = re.search(r"4K\s*(\d{2,3})\s*Hz", v, re.I)
        if m:
            return {"value": int(m.group(1)), "unit": "Hz", "raw": v,
                    "source": "OCR参数卡", "is_native": True,
                    "note": "原生 4K 刷新率"}
        m = re.search(r"(\d{2,3})\s*Hz", v, re.I)
        if m:
            return {"value": int(m.group(1)), "unit": "Hz", "raw": v,
                    "source": "OCR参数卡", "is_native": False,
                    "note": "卡片未标4K，可能为 2K/降分辨率模式下的高刷"}
        return None

    if field == "色域":
        # 四种标准，分列不混算
        for pat, std in [(r"(\d{2,3}(?:\.\d)?)\s*%\s*DCI-?P3", "% DCI-P3"),
                         (r"(\d{2,3}(?:\.\d)?)\s*%\s*BT\.?2020", "% BT.2020"),
                         (r"(\d{2,3}(?:\.\d)?)\s*%\s*BT\.?709", "% BT.709"),
                         (r"(\d{2,3}(?:\.\d)?)\s*%\s*sRGB", "% sRGB")]:
            m = re.search(pat, v, re.I)
            if m:
                val = float(m.group(1))
                # 覆盖率不可能超过 100%。实测两种情况都出现过：
                #  (a) OCR 误识："100% BT.709"->"130% BT.709"、"100% DCI-P3"->"110% DCI-P3"
                #      （0→3、0→1 形近误识）
                #  (b) 视频画面本身就这么写（如 TCL V8M 标 130% BT.709，技术上不成立）
                # 因此不能一律改写成 100 —— 一律标记为需人工确认，保留原值备查。
                if val > 100:
                    return {"value": val, "unit": std, "raw": v,
                            "source": "OCR参数卡", "ocr_error": True,
                            "note": f"画面标注为 {val}%，超过 100% 覆盖率上限，"
                                    f"技术上不成立（原图如此，非识别误差），需人工核对"}
                note = ("色域标准为 sRGB，与 DCI-P3/BT.2020 非同一量纲，不可直接比较"
                        if std == "% sRGB" else
                        f"色域标准 {std}，与其他标准不可直接比较")
                return {"value": val, "unit": std, "raw": v,
                        "source": "OCR参数卡", "standard": std, "note": note}
        return None

    if field in ("内存", "存储"):
        m = re.search(r"(\d+)\s*GB", v, re.I)
        if m:
            return {"value": int(m.group(1)), "unit": "GB", "raw": v,
                    "source": "OCR参数卡"}
        return None

    if field == "处理器":
        m = re.search(r"((?:双核|单核|四核|五核|八核|四核A|双核A)?\s*[A-Z]?\d{2,3}"
                      r"\s*(?:\+\s*(?:双核|单核|四核|五核|八核)?\s*[A-Z]?\d{0,3})*)", v)
        if m and m.group(1).strip():
            return {"value": m.group(1).strip(), "unit": "", "raw": v,
                    "source": "OCR参数卡"}
        return None

    if field == "屏幕尺寸":
        m = re.search(r"(\d{2})\s*(?:英寸|寸)", v)
        if m:
            return {"value": int(m.group(1)), "unit": "英寸", "raw": v,
                    "source": "OCR参数卡"}
        return None

    if field == "HDMI":
        m = re.search(r"HDMI\s*2\.1\D{0,8}?(\d+)\s*个?", v, re.I)
        if m:
            return {"value": int(m.group(1)), "unit": "个", "raw": v,
                    "source": "OCR参数卡", "hdmi_ver": "2.1"}
        m = re.search(r"HDMI\s*2\.0\D{0,8}?(\d+)\s*个?", v, re.I)
        if m:
            return {"value": int(m.group(1)), "unit": "个", "raw": v,
                    "source": "OCR参数卡", "hdmi_ver": "2.0"}
        return None

    if field == "发声单元":
        m = re.search(r"(\d+)\s*个", v)
        if m:
            return {"value": int(m.group(1)), "unit": "个", "raw": v,
                    "source": "OCR参数卡"}
        return None

    if field == "控色区":
        m = re.search(r"(\d+)\s*(?:个)?\s*([一-龥A-Za-z0-9]+控色区)", v)
        if m:
            return {"value": m.group(2), "unit": "", "raw": v, "source": "OCR参数卡"}
        if re.search(r"控色区", v):
            return {"value": v, "unit": "", "raw": v, "source": "OCR参数卡"}
        return None

    if len(v) <= 24:
        return {"value": v, "unit": "", "raw": v, "source": "OCR参数卡"}
    return None


# ==================== 参数卡解析 ====================
def is_card_frame(frame):
    labels = sum(1 for t in frame["texts"] if classify_label(t["text"]))
    return labels >= 4


def parse_card_geometry(frame):
    """坐标配对解析。"""
    items = []
    for t in frame["texts"]:
        items.append({
            "text": fix_ocr_text(t["text"]),
            "score": t["score"],
            "yc": y_center(t["box"]),
            "xl": x_left(t["box"]),
            # region 标注来源区域，底部横排栏靠它区分字段归属
            "region": t.get("region", ""),
        })

    labels = []
    for it in items:
        f = classify_label(it["text"])
        if f:
            labels.append({**it, "field": f})
    if len(labels) < 4:
        return None, None, None

    # 标题行（y< 150）
    title_band = [it for it in items if it["yc"] < 150]
    brand, model = None, None
    for it in sorted(title_band, key=lambda x: x["xl"]):
        if re.search(r"参考价|[¥￥]", it["text"]):
            continue
        b, m_ = extract_brand_model(it["text"])
        if b:
            brand = b
            if m_:
                model = m_
                break
    if not brand:
        for it in sorted(title_band, key=lambda x: x["xl"]):
            b, m_ = extract_brand_model(it["text"])
            if b:
                brand = b
                if m_:
                    model = m_
                    break

    params = {}
    notes = []
    # 记录 OCR 异常值（value 为 None 的解析结果）
    bad_values = {}

    for lb in labels:
        cands = [it for it in items
                 if it["xl"] > lb["xl"] + 40
                 and abs(it["yc"] - lb["yc"]) <= 42
                 and not classify_label(it["text"])]
        if not cands:
            continue
        # 按 y 距离优先（关键：避免取到下一行的补充说明）
        cands.sort(key=lambda x: (abs(x["yc"] - lb["yc"]), x["xl"]))
        nearest = abs(cands[0]["yc"] - lb["yc"])
        same_row = [c for c in cands if abs(c["yc"] - lb["yc"]) <= nearest + 8]
        same_row.sort(key=lambda x: x["xl"])
        val_text = " ".join(c["text"] for c in same_row)

        parsed = parse_value(lb["field"], val_text)
        if not parsed:
            continue
        # OCR 异常标记（如色域识别为 130% BT.709 超过 100% 上限）时，
        # parse_value 会返回 value=None 的记录。这类记录不能当作有效参数，
        # 否则会在字段统计里产生大量"待确认(空)"噪声。
        #改为不写入 params，仅在 notes 中留痕。
        if parsed.get("value") is None:
            bad_values.setdefault(lb["field"], []).append({
                "raw": parsed.get("raw", ""),
                "note": parsed.get("note", ""),
                "timestamp": None,
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
    if "刷新率" in params:
        r = params["刷新率"]
        alts = r.get("alt_values", [])
        if not r.get("is_native"):
            native = [a for a in alts if a.get("is_native")]
            if native:
                params["刷新率"] = {
                    "value": native[0]["value"], "unit": "Hz",
                    "raw": native[0]["raw"], "source": "OCR参数卡",
                    "is_native": True, "note": "原生 4K 刷新率"}
            else:
                r["note"] = "卡片未标明 4K，该值可能为 2K/降分辨率模式下的高刷"

    # 倍频/第二刷新率（如 288Hz 倍频）
    for it in items:
        m = re.search(r"(\d{2,3})\s*Hz\s*[（(]?\s*倍频", it["text"])
        if m:
            params["刷新率_倍频"] = {
                "value": int(m.group(1)), "unit": "Hz", "raw": it["text"],
                "source": "OCR参数卡",
                "note": "倍频值，非原生刷新率，不可与原生值直接比较"}

    # ---- 无标签字段兜底提取 ----
    # 先构造全帧文本供兜底匹配使用
    full_text = " ".join(i["text"] for i in items)
    # 实测底部横排版式中，"运行内存/存储" 一栏的标签可能未OCR出来，
    # 只有值（形如 "2GB / 64GB"，x≈485 y≈790），导致该字段整体缺失。
    # 因此对内存/存储/HDMI/发声单元做一次全帧兜底匹配。
    if "内存" not in params or "存储" not in params:
        m = re.search(r"(\d+)\s*GB\s*[/／]\s*(\d+)\s*GB", full_text, re.I)
        if m:
            if "内存" not in params:
                params["内存"] = {"value": int(m.group(1)), "unit": "GB",
                                  "raw": m.group(0), "source": "OCR参数卡(兜底)",
                                  "note": "由 'NGB/MGB' 复合值拆分"}
            if "存储" not in params:
                params["存储"] = {"value": int(m.group(2)), "unit": "GB",
                                  "raw": m.group(0), "source": "OCR参数卡(兜底)",
                                  "note": "由 'NGB/MGB' 复合值拆分"}

    if "HDMI2.1数量" not in params:
        m = re.search(r"HDMI\s*2\.1\D{0,8}?(\d+)\s*个?", full_text, re.I)
        if m:
            params["HDMI2.1数量"] = {"value": int(m.group(1)), "unit": "个",
                                     "raw": m.group(0),
                                     "source": "OCR参数卡(兜底)", "hdmi_ver": "2.1"}
    if "HDMI2.0数量" not in params:
        m = re.search(r"HDMI\s*2\.0\D{0,8}?(\d+)\s*个?", full_text, re.I)
        if m:
            params["HDMI2.0数量"] = {"value": int(m.group(1)), "unit": "个",
                                     "raw": m.group(0),
                                     "source": "OCR参数卡(兜底)", "hdmi_ver": "2.0"}
    if "发声单元" not in params:
        m = re.search(r"发声单元\D{0,20}?(\d+)\s*个", full_text)
        if m:
            params["发声单元"] = {"value": int(m.group(1)), "unit": "个",
                                 "raw": m.group(0), "source": "OCR参数卡(兜底)"}
    if "处理器" not in params:
        m = re.search(r"处理器\D{0,20}?((?:双核|单核|四核|五核|八核)\s*[A-Z]?\d{0,3}"
                      r"(?:\s*\+\s*(?:双核|单核|四核|五核|八核)?\s*[A-Z]?\d{0,3})*)",
                      full_text)
        if m:
            params["处理器"] = {"value": m.group(1).strip(), "unit": "",
                                "raw": m.group(0), "source": "OCR参数卡(兜底)"}
    if "屏幕尺寸" not in params:
        m = re.search(r"(\d{2})\s*(?:英寸|寸)", full_text)
        if m:
            params["屏幕尺寸"] = {"value": int(m.group(1)), "unit": "英寸",
                                  "raw": m.group(0), "source": "OCR参数卡(兜底)"}

    # 备注
    for it in items:
        if re.match(r"^客服[:：]", it["text"]):
            notes.append({"field": "_口径说明", "note_text": it["text"]})
        elif "高刷" in it["text"] and re.search(r"\d{2,3}Hz", it["text"]):
            notes.append({"field": "_刷新说明", "note_text": it["text"]})
        elif re.search(r"[（(]\s*宣称\s*[)）]", it["text"]):
            notes.append({"field": "_宣称标记",
                          "note_text": "该数值为厂商宣称值而非实测值"})
        elif re.search(r"国补|补贴|地区", it["text"]):
            notes.append({"field": "_价格口径", "note_text": it["text"]})

    # 特殊参数
    # ---- 底部横排栏：按 x 位置映射字段 ----
    # OCR 时已把底部数值行按实测 x 范围切成四段并标注 region，
    # 这里直接按 region 与x 位置归位，避免与字幕混淆。
    #   footer_v1 x150-560  -> 运行内存/存储
    #   footer_v2 x620-900  -> HDMI 2.1 / 2.0
    #   footer_v3 x960-1180 -> 发声单元
    #   footer_v4 x1340-1800-> 处理器
    footer_map = {
        "footer_v1": ["内存", "存储"],
        "footer_v2": ["HDMI2.1数量", "HDMI2.0数量"],
        "footer_v3": ["发声单元"],
        "footer_v4": ["处理器"],
    }
    footer_buf = defaultdict(list)
    for it in items:
        rg = it.get("region", "")
        if rg in footer_map:
            footer_buf[rg].append(it["text"])

    for rg, fields in footer_map.items():
        texts = footer_buf.get(rg, [])
        if not texts:
            continue
        blob = " ".join(texts)
        # 内存/存储
        if "内存" in fields:
            m = re.search(r"(\d+)\s*GB", blob, re.I)
            if m and "内存" not in params:
                params["内存"] = {"value": int(m.group(1)), "unit": "GB",
                                  "raw": blob, "source": "OCR参数卡底部栏",
                                  "note": "由底部横排栏 'NGB/MGB' 复合值拆分"}
            m2 = re.search(r"(\d+)\s*GB\s*[/／]\s*(\d+)\s*GB", blob, re.I)
            if m2:
                if "内存" not in params:
                    params["内存"] = {"value": int(m2.group(1)), "unit": "GB",
                                      "raw": blob, "source": "OCR参数卡底部栏"}
                if "存储" not in params:
                    params["存储"] = {"value": int(m2.group(2)), "unit": "GB",
                                      "raw": blob, "source": "OCR参数卡底部栏"}
            elif m and "存储" not in params:
                # 只有单个 GB 值时按位置判定：靠前者为内存
                nums = re.findall(r"(\d+)\s*GB", blob, re.I)
                if len(nums) == 2:
                    params["存储"] = {"value": int(nums[1]), "unit": "GB",
                                      "raw": blob, "source": "OCR参数卡底部栏"}
        # HDMI
        if "HDMI2.1数量" in fields and "HDMI2.1数量" not in params:
            m = re.search(r"2\.?1\D{0,6}?(\d+)\s*个?", blob)
            if m:
                params["HDMI2.1数量"] = {"value": int(m.group(1)), "unit": "个",
                                         "raw": blob,
                                         "source": "OCR参数卡底部栏"}
        if "HDMI2.0数量" in fields and "HDMI2.0数量" not in params:
            m = re.search(r"2\.?0\D{0,6}?(\d+)\s*个?", blob)
            if m:
                params["HDMI2.0数量"] = {"value": int(m.group(1)), "unit": "个",
                                         "raw": blob,
                                         "source": "OCR参数卡底部栏"}
        # 发声单元
        if "发声单元" in fields and "发声单元" not in params:
            m = re.search(r"(\d+)\s*个", blob)
            if m:
                params["发声单元"] = {"value": int(m.group(1)), "unit": "个",
                                     "raw": blob, "source": "OCR参数卡底部栏"}
        # 处理器
        if "处理器" in fields and "处理器" not in params:
            m = re.search(r"((?:双核|单核|四核|五核|八核)\s*[A-Z]?\d{0,3}"
                          r"(?:\s*\+\s*(?:双核|单核|四核|五核|八核)?\s*[A-Z]?\d{0,3})*)",
                          blob)
            if m:
                params["处理器"] = {"value": m.group(1).strip(), "unit": "",
                                    "raw": blob, "source": "OCR参数卡底部栏"}

    full = " ".join(i["text"] for i in items)
    specials = []
    for pat, name, typ, owner in SPECIAL_PATTERNS:
        if re.search(pat, full, re.I):
            specials.append({"name": name, "type": typ, "owner": owner})

    # OCR 异常值 -> 转为 notes，不写入 params
    for field, items in bad_values.items():
        for it in items:
            notes.append({
                "field": f"_OCR异常:{field}",
                "note_text": f"{it['raw']} —— {it['note']}",
            })

    return brand, model, {"params": params, "notes": notes, "specials": specials}


# ==================== 人工确认值（用户截图） ====================
USER_VERIFIED = {
    "创维A4F Pro": {
        "色域": {"value": 100.0, "unit": "% sRGB", "standard": "% sRGB",
                "note": "色域标准为 sRGB，与 DCI-P3/BT.2020 非同一量纲，不可直接比较"},
        "内存": {"value": 2, "unit": "GB"},
        "存储": {"value": 64, "unit": "GB"},
        "处理器": {"value": "四核A55", "unit": ""},
        "HDMI2.1数量": {"value": 2, "unit": "个"},
        "发声单元": {"value": 2, "unit": "个"},
    },
    "华为Vision智慧屏6": {
        "屏幕": {"value": "VA软屏", "unit": ""},
        "内存": {"value": 8, "unit": "GB"},
        "存储": {"value": 64, "unit": "GB"},
        "处理器": {"value": "四核A73", "unit": ""},
        "刷新率_倍频": {"value": 288, "unit": "Hz",
                     "note": "倍频值，非原生刷新率，不可与原生值直接比较"},
    },
}


def apply_user_verified(models):
    """套用用户截图确认值，并标记来源。"""
    fixed = 0
    for m in models:
        name = f"{m.get('brand') or ''}{m.get('model') or ''}"
        for key, patch in USER_VERIFIED.items():
            if key in name or name in key:
                for field, val in patch.items():
                    m["params"][field] = {
                        **val, "raw": "(用户截图确认)",
                        "source": "用户截图确认",
                        "verified_by": "user_screenshot",
                    }
                    fixed += 1
                m["verified"] = True
    return fixed


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "output"
    ocr_path = os.path.join(out_dir, "frames_ocr.json")

    with open(ocr_path, encoding="utf-8") as f:
        ocr_data = json.load(f)
    print(f"载入 OCR 数据: {len(ocr_data)} 帧", flush=True)

    # 排除开篇多机型同屏干扰帧
    usable = [f for f in ocr_data if f["timestamp"] >= INTERFERENCE_START]
    skipped = len(ocr_data) - len(usable)
    print(f"排除开篇干扰帧: {skipped} 帧（< {INTERFERENCE_START}s，多机型同屏易错配）",
          flush=True)
    print(f"可用帧: {len(usable)}", flush=True)

    cards = []
    for fr in usable:
        if not is_card_frame(fr):
            continue
        brand, model, parsed = parse_card_geometry(fr)
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

    # 聚类
    groups = defaultdict(list)
    for c in cards:
        groups[(c["brand"], c["model"])].append(c)

    models_out = []
    for key, items in groups.items():
        brand, model = key
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
                    merged[field] = {**val, "source_timestamp": it["timestamp"],
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

    # 套用用户确认值
    nfix = apply_user_verified(models_out)
    print(f"套用用户截图确认值: {nfix} 个字段", flush=True)

    models_out.sort(key=lambda x: x["first_seen"])

    out_json = os.path.join(out_dir, "tv_models.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(models_out, f, ensure_ascii=False, indent=2)
    print(f"输出: {out_json}", flush=True)

    # 统计
    all_fields = set()
    for m in models_out:
        all_fields.update(m["params"].keys())
    print(f"覆盖字段: {sorted(all_fields)}", flush=True)
    print(f"冲突总数: {sum(len(m['conflicts']) for m in models_out)}", flush=True)
    print(f"带特殊参数机型: {sum(1 for m in models_out if m['specials'])}", flush=True)

    # 报告
    print(flush=True)
    print("=" * 110, flush=True)
    print(f"共 {len(models_out)} 个机型", flush=True)
    print("=" * 110, flush=True)
    hdr = (f"{'时间':>6} {'品牌':6s} {'型号':16s} {'价格':>8s} {'亮度':>6s} "
           f"{'分区':>5s} {'刷新':>5s} {'色域':>12s} {'内存':>5s} {'存储':>5s}")
    print(hdr, flush=True)
    for m in models_out:
        p = m["params"]
        def g(k):
            return str(p.get(k, {}).get("value", "-"))
        mem = g("内存") + ("/" + g("存储") if "存储" in p else "")
        cg = p.get("色域", {})
        cgv = (str(cg.get("value", "-")) + cg.get("unit", "")) if cg else "-"
        print(f"{m['first_seen']:6.0f} {str(m['brand'] or '?'):6s} "
              f"{str(m['model'] or '?'):16s} {g('价格'):>8s} {g('峰值亮度'):>6s} "
              f"{g('分区数'):>5s} {g('刷新率'):>5s} {cgv:>12s} {mem:>7s}", flush=True)
        sp = [s["name"] for s in m["specials"]]
        if sp:
            print(f"{'':>6} └ 特殊: {'、'.join(sp)}", flush=True)
        for c in m["conflicts"][:2]:
            print(f"{'':>6} ⚠ 冲突 {c['field']}: {c['old']}@{c['old_ts']}s vs "
                  f"{c['new']}@{c['new_ts']}s", flush=True)


if __name__ == "__main__":
    main()
