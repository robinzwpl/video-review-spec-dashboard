# -*- coding: utf-8 -*-
"""
OCR 区域等价性断言。

04_ocr.py 的区域坐标从硬编码改成配置驱动后，回归测试测不出差异——
因为回归比对的是 06 的输出，而 06 吃的是历史 fixture（已标注 region 的产物）。
改错坐标，回归照样绿，真实视频重跑时覆盖率却会塌。

本测试用三条断言守住这个盲区：
  A. 像素坐标等价：配置算出的区域与历史上硬编码的逐位一致
  B. 包含性契约  ：fixture 里每个文本框都必须落在它被标注的那个区域内
  C. 命名契约    ：区域名与 preset 的 footer_regions 抽取器一一对应，无孤儿

最强的证据是「用现有 226 帧重跑一次 04，与 fixture 逐项比对」，
那条耗时要几分钟，不放在本测试里，改完 04 手工跑一次即可。

用法：python tests/test_ocr_regions_equiv.py
"""
import os
import sys
import json
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS)


def load_module(name, path):
    """按文件路径加载模块（脚本名以数字开头，不是合法标识符）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cfgmod = load_module("cfgmod", os.path.join(SCRIPTS, "lib", "config.py"))
ocr = load_module("ocr04", os.path.join(SCRIPTS, "04_ocr.py"))

# 1920x1080 下按 int() 截断换算得到的期望值（历史硬编码的等价像素坐标）
# 注意：0.078*1920=149.76 -> 149，不是四舍五入的 150
EXPECTED_1080P = [
    ("card_main",    38,   54, 1881,  928),
    ("footer_label", 38,  912, 1881,  950),
    ("footer_v1",   149,  953,  560, 1009),
    ("footer_v2",   620,  953,  900, 1009),
    ("footer_v3",   960,  953, 1180, 1009),
    ("footer_v4",  1340,  953, 1800, 1009),
    ("subtitle",     38,  928, 1881, 1078),
]

TOL = 1  # 像素容差


def test_a_pixel_equivalence(cfg):
    """断言 A：顺序与像素坐标与历史硬编码逐位一致。"""
    got = ocr.build_regions(cfg, 1920, 1080)
    if got == EXPECTED_1080P:
        print(f"  A 通过：{len(got)} 个区域的顺序与像素坐标与历史一致")
        return True
    print("  A 失败：", file=sys.stderr)
    print(f"    期望: {EXPECTED_1080P}", file=sys.stderr)
    print(f"    实际: {got}", file=sys.stderr)
    for i, (exp, act) in enumerate(zip(EXPECTED_1080P, got)):
        if exp != act:
            print(f"    第 {i} 个不同: 期望 {exp} 实际 {act}", file=sys.stderr)
    if len(got) != len(EXPECTED_1080P):
        print(f"    区域数量不同: 期望 {len(EXPECTED_1080P)} 实际 {len(got)}",
              file=sys.stderr)
    return False


def test_b_containment(cfg, fixture):
    """断言 B：每个文本框都落在它被标注的区域之内。"""
    boxes = {name: (x1, y1, x2, y2)
             for name, x1, y1, x2, y2 in ocr.build_regions(cfg, 1920, 1080)}
    total = 0
    outside = 0
    unknown = set()
    samples = []
    for fr in fixture:
        for t in fr["texts"]:
            total += 1
            rg = t.get("region")
            if rg not in boxes:
                unknown.add(rg)
                continue
            gx1, gy1, gx2, gy2 = boxes[rg]
            for x, y in t["box"]:
                if not (gx1 - TOL <= x <= gx2 + TOL
                        and gy1 - TOL <= y <= gy2 + TOL):
                    outside += 1
                    if len(samples) < 3:
                        samples.append((fr["timestamp"], rg, t["text"],
                                        t["box"], (gx1, gy1, gx2, gy2)))
                    break
    if unknown:
        print(f"  B 失败：存在未知 region {sorted(unknown)}", file=sys.stderr)
        return False
    if outside:
        print(f"  B 失败：{outside}/{total} 个文本框越出所属区域，样例：",
              file=sys.stderr)
        for s in samples:
            print(f"    t={s[0]} region={s[1]} text={s[2]!r} "
                  f"box={s[3]} 区域={s[4]}", file=sys.stderr)
        return False
    print(f"  B 通过：{total} 个文本框全部落在所属区域内（越界 0）")
    return True


def test_c_name_contract(cfg):
    """断言 C：区域名与 footer_regions 抽取器一一对应，无孤儿。"""
    regions = cfg.get("ocr", {}).get("regions", {})
    footers = cfg.get("footer_regions", {})
    problems = []
    for key in footers:
        if key not in regions:
            problems.append(f"footer_regions.{key} 在 ocr.regions 里没有同名区域")
    for name, r in regions.items():
        if r.get("role") == "footer_value" and name not in footers:
            problems.append(f"区域 {name} 识别了但没有 footer_regions 抽取器")
    if problems:
        print("  C 失败：", file=sys.stderr)
        for p in problems:
            print(f"    {p}", file=sys.stderr)
        return False
    print(f"  C 通过：{len(regions)} 个区域与 {len(footers)} 个抽取器"
          f"命名一致，无孤儿")
    return True


def main():
    cfg = cfgmod.load_config("tv75_science")
    with open(os.path.join(HERE, "fixtures", "frames_ocr.json"),
              encoding="utf-8") as f:
        fixture = json.load(f)

    print(f"OCR 区域等价性断言（fixture {len(fixture)} 帧）")
    ok = True
    ok = test_a_pixel_equivalence(cfg) and ok
    ok = test_b_containment(cfg, fixture) and ok
    ok = test_c_name_contract(cfg) and ok

    if not ok:
        print("\n断言失败：配置驱动的 region 与历史不等价", file=sys.stderr)
        sys.exit(1)
    print("三段断言全部通过")


if __name__ == "__main__":
    main()
