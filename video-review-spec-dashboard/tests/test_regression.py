# -*- coding: utf-8 -*-
"""
回归测试：验证通用化改造后的 06_parse.py，配置驱动下能否复现冻结基线。

基线文件 tests/expected/tv75_models.json 一旦冻结就不允许更新。
若解析逻辑确有正当变化，应新增 expected v2 并写明理由，而不是改旧基线。

比对范围：
    机型数、品牌、型号、字段集合、每个值的 value / unit / source / 结构化标记
不比对：
    note、raw、label_text、frame_path 等不影响解析正确性的描述性字段
"""
import os
import sys
import json
import subprocess
import tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")

FIXTURE = os.path.join(HERE, "fixtures", "frames_ocr.json")
EXPECTED = os.path.join(HERE, "expected", "tv75_models.json")
PRESET = "tv75_science"

# 参与比对的结构化标记（这些决定了下游如何解读数值）
MARK_KEYS = ("is_range", "value_min", "is_native", "zone_type", "exact",
             "standard", "ocr_error", "hdmi_ver")


def norm_params(params):
    out = {}
    for k, v in params.items():
        item = {
            "value": v.get("value"),
            "unit": v.get("unit"),
            "source": v.get("source"),
        }
        for mk in MARK_KEYS:
            # 值为 None 与键缺失语义等价（都表示未识别出该标记），统一忽略
            if v.get(mk) is not None:
                item[mk] = v[mk]
        out[k] = item
    return out


def load_models(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_parse(out_path):
    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, "06_parse.py"),
           "--preset", PRESET, "--input", FIXTURE, "--output", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print("解析脚本执行失败：")
        print(r.stdout)
        print(r.stderr)
        sys.exit(1)
    return r.stdout


def main():
    if not os.path.exists(FIXTURE):
        print(f"夹具不存在: {FIXTURE}")
        sys.exit(1)

    tmp = tempfile.mktemp(suffix=".json")
    run_parse(tmp)
    actual = load_models(tmp)
    expected = load_models(EXPECTED)

    errors = []

    if len(actual) != len(expected):
        errors.append(f"机型数不一致: 实际 {len(actual)}，基线 {len(expected)}")

    exp_by_key = {(m.get("brand"), m.get("model")): m for m in expected}
    act_by_key = {(m.get("brand"), m.get("model")): m for m in actual}

    for key in exp_by_key:
        if key not in act_by_key:
            errors.append(f"基线机型缺失: {key}")

    for key in act_by_key:
        if key not in exp_by_key:
            errors.append(f"多出机型: {key}")

    for key in exp_by_key:
        if key not in act_by_key:
            continue
        e, a = exp_by_key[key], act_by_key[key]
        ep, ap = norm_params(e.get("params", {})), norm_params(a.get("params", {}))

        miss = sorted(set(ep) - set(ap))
        extra = sorted(set(ap) - set(ep))
        if miss:
            errors.append(f"{key}: 缺少字段 {miss}")
        if extra:
            errors.append(f"{key}: 多出字段 {extra}")

        for f in sorted(set(ep) & set(ap)):
            if ep[f] != ap[f]:
                errors.append(
                    f"{key} / {f}: 基线 {ep[f]} != 实际 {ap[f]}")

        ec = len(e.get("conflicts", []))
        ac = len(a.get("conflicts", []))
        if ec != ac:
            errors.append(f"{key}: 冲突数 基线 {ec} 实际 {ac}")

    if errors:
        print(f"回归失败，共 {len(errors)} 处差异：")
        for e in errors[:40]:
            print("  -", e)
        if len(errors) > 40:
            print(f"  ... 另有 {len(errors) - 40} 处")
        sys.exit(1)

    print(f"回归通过：{len(actual)} 个机型，字段与数值均与基线一致")
    fields = sorted({k for m in actual for k in m.get("params", {})})
    print(f"覆盖字段: {fields}")


if __name__ == "__main__":
    main()
