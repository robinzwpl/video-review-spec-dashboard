# -*- coding: utf-8 -*-
"""
配置加载与校验。

配置分两层：
  config/default.yaml         通用默认（几何阈值、渲染规则等，与品类无关）
  config/presets/<名称>.yaml  品类预设（品牌表、字段表、底部栏区域、人工确认值等）

两层做深度合并，预设覆盖默认。缺失必填项直接报错，不做静默降级。
"""
import os

import yaml


def config_dir():
    """返回 config/ 目录的绝对路径（用 realpath 规避 junction 部署时的路径问题）。"""
    # realpath 规避 junction 部署时 __file__ 返回链接侧路径的问题
    # __file__ = <skill>/scripts/lib/config.py -> 上三级才是 skill 根目录
    here = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "config")


def load_yaml(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base, override):
    """递归合并，override 覆盖 base。"""
    out = dict(base)
    for k, v in (override or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def validate(cfg):
    """校验必填项，缺项直接抛错。"""
    if not cfg.get("fields"):
        raise ValueError("配置缺少 fields 字段表，无法进行参数解析")
    seen = set()
    for fd in cfg["fields"]:
        if not fd.get("name"):
            raise ValueError(f"字段定义缺少 name: {fd}")
        if not fd.get("type"):
            raise ValueError(f"字段 {fd['name']} 缺少 type")
        if fd["name"] in seen:
            raise ValueError(f"字段名重复: {fd['name']}")
        seen.add(fd["name"])
    return cfg


def load_base():
    """
    只加载通用层 config/default.yaml，不做 fields 校验。

    供与品类无关的脚本（抽帧、OCR、版式探查）使用：
    它们只需要通用阈值，此时可能还没有品类预设，不能强制要求 fields。
    """
    return load_yaml(os.path.join(config_dir(), "default.yaml"))


def load_config(preset_name):
    """
    加载配置。

    :param preset_name: 预设文件名（含或不含 .yaml 均可），如 tv75_science
    :return: 合并后的配置 dict
    """
    cdir = config_dir()
    default_path = os.path.join(cdir, "default.yaml")
    if not preset_name.endswith(".yaml"):
        preset_name += ".yaml"
    preset_path = preset_name if os.path.isabs(preset_name) else \
        os.path.join(cdir, "presets", preset_name)
    merged = deep_merge(load_yaml(default_path), load_yaml(preset_path))
    return validate(merged)


def list_presets():
    """列出可用的品类预设名称。"""
    pdir = os.path.join(config_dir(), "presets")
    names = []
    for fn in sorted(os.listdir(pdir)):
        if fn.endswith(".yaml") and not fn.startswith("_"):
            names.append(fn[:-5])
    return names


def field_by_name(cfg, name):
    """按 name 取字段定义。"""
    for fd in cfg["fields"]:
        if fd["name"] == name:
            return fd
    return None


def label_index(cfg):
    """
    构建「标签原文 -> 字段名」索引。

    顺序敏感：按 fields 定义顺序遍历，靠前的字段优先判定。
    """
    idx = []
    for fd in cfg["fields"]:
        for alias in fd.get("aliases", []):
            idx.append((str(alias).lower(), fd["name"]))
    return idx
