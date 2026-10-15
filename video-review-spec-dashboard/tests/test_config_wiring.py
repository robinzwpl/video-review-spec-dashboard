# -*- coding: utf-8 -*-
"""
配置项接线守卫。

目的：杜绝「配了但没有消费者」的配置项。
这类问题比没有配置更危险——改了配置却毫无效果，排查成本极高。
本仓库早期就有 render.* / output.* 共 9 个键属于这种情况，故加此守卫。

做法：遍历 config/default.yaml 的所有叶子键，检查 scripts/ 下的代码里
是否真的引用了它（按带引号的键名匹配，避免子串误判）。

用法：python tests/test_config_wiring.py
"""
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)

# 临时豁免：已知尚未接线，接线后必须从此列表移除
# 否则守卫形同虚设。当前为空——所有配置项都应有真实消费者。
PENDING_WIRING = set()


def leaf_keys(node, prefix=""):
    """把嵌套 dict 展开成 ['a.b', 'a.c'] 形式的叶子键路径。"""
    out = []
    for k, v in (node or {}).items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.extend(leaf_keys(v, path))
        else:
            out.append(path)
    return out


def load_code():
    """拼接 scripts/ 下所有 Python 源码，供键名匹配。"""
    root = os.path.join(SKILL_ROOT, "scripts")
    chunks = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.endswith(".py"):
                with open(os.path.join(dirpath, fn), encoding="utf-8") as f:
                    chunks.append(f.read())
    return "\n".join(chunks)


def main():
    # 直接读 yaml：本测试刻意不依赖 scripts/lib，避免被测对象与被检对象耦合
    with open(os.path.join(SKILL_ROOT, "config", "default.yaml"),
              encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    code = load_code()
    keys = leaf_keys(cfg)

    unwired = []
    pending = []
    for path in sorted(keys):
        leaf = path.split(".")[-1]
        # 按带引号的键名匹配：cfg.get("missing_label") / cfg["render"]["x"]
        # 避免 "interval" 命中 "interval_pos" 之类的子串误判
        if re.search(r"""["']%s["']""" % re.escape(leaf), code):
            continue
        if leaf in PENDING_WIRING:
            pending.append(path)
        else:
            unwired.append(path)

    print(f"检查配置项 {len(keys)} 个")
    if pending:
        print(f"临时豁免（待接线，接好后必须从 PENDING_WIRING 移除）: "
              f"{len(pending)} 个")
        for p in pending:
            print(f"  - {p}")
    if unwired:
        print(f"\n发现无消费者的配置项 {len(unwired)} 个：", file=sys.stderr)
        for p in unwired:
            print(f"  - {p}", file=sys.stderr)
        print("\n要么让脚本真正读取它，要么把它从 default.yaml 删掉。",
              file=sys.stderr)
        sys.exit(1)

    print("接线守卫通过：所有配置项都有代码消费"
          + (f"（{len(pending)} 个待接线豁免中）" if pending else ""))


if __name__ == "__main__":
    main()
