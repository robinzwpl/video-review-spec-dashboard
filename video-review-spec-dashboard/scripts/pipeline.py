# -*- coding: utf-8 -*-
"""
流水线编排：把 01-10 十个阶段串起来。

用 subprocess 调用各阶段脚本，而不是 import：
  - 脚本名以数字开头，不是合法标识符，import 需要绕路
  - 各脚本 CLI 独立，import 方案要为每个脚本重复一遍参数解析（bug 温床）
  - 进程隔离：OCR 加载 onnxruntime、av 解码崩溃都局限在子进程里
  - --dry-run 能打印出可直接复制粘贴的单阶段命令

产物路径由本脚本统一从 config/default.yaml 的 output 段拼出，
再显式传给各阶段，避免各脚本各自猜文件名。

用法：
    python pipeline.py --preset tv75_science --video <视频> --stages all
    python pipeline.py --video <视频> --stages 3,4,5     # 新视频：先探版式
    python pipeline.py --preset tv75_science --out-dir output --stages 6,8,9
    python pipeline.py --list-presets
"""
import os
import sys
import glob
import json
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import config as cfgmod

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)

# 阶段定义
#   no     阶段编号
#   name   阶段名（--stages 用）
#   script 脚本文件名
#   kind   core = 失败即中止；optional = 失败只警告并继续
#   needs_preset  True 表示该阶段必须有品类预设才能跑
STAGES = [
    (1, "probe", "01_probe.py", "core", False, "视频探测 + 16kHz 音频提取"),
    (2, "transcribe", "02_transcribe.py", "optional", False, "音频转写（需本地模型）"),
    (3, "keyframes", "03_keyframes.py", "core", False, "差异自适应抽帧"),
    (4, "ocr", "04_ocr.py", "core", False, "分区域 OCR"),
    (5, "discover", "05_discover.py", "optional", False, "版式探查报告"),
    (6, "parse", "06_parse.py", "core", True, "参数卡解析"),
    (7, "contact", "07_contact_sheet.py", "optional", True, "核对拼图"),
    (8, "table", "08_specs_table.py", "core", True, "核对表 CSV + HTML"),
    (9, "dashboard", "09_dashboard.py", "core", True, "单文件对比看板"),
    (10, "chapters", "10_chapters.py", "optional", False, "章节定位"),
]

BY_NAME = {s[1]: s for s in STAGES}
BY_NO = {s[0]: s for s in STAGES}
CORE_DEFAULT = [1, 3, 4, 5, 6, 7, 8, 9]


def parse_stages(spec):
    """解析 --stages：支持 all / 编号 / 名称 / 1-4 区间，逗号分隔。"""
    if spec.strip().lower() == "all":
        return list(CORE_DEFAULT)
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and part[0].isdigit():
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        elif part.isdigit():
            out.append(int(part))
        elif part in BY_NAME:
            out.append(BY_NAME[part][0])
        else:
            raise ValueError(f"无法识别的阶段: {part}")
    # 去重并保持编号顺序
    return sorted(set(n for n in out if n in BY_NO))


def find_video(cfg, out_dir):
    """
    查找视频，优先级：
      1) --video 显式给出（调用方先判断）
      2) 环境变量 VRSD_VIDEO
      3) config: search.video_dirs（默认空，不猜用户专属目录）
      4) skill 目录与其上级目录内递归（跳过 output / .git / node_modules）
    """
    env = os.environ.get("VRSD_VIDEO")
    if env and os.path.exists(env):
        return env

    exts = cfg.get("search", {}).get("video_exts", ["mp4", "mkv", "mov"])
    searched = []

    for d in cfg.get("search", {}).get("video_dirs", []) or []:
        searched.append(d)
        hits = _glob_video(d, exts)
        if hits:
            return hits[0]

    for root in (SKILL_ROOT, os.path.dirname(SKILL_ROOT)):
        searched.append(root)
        hits = _glob_video(root, exts)
        if hits:
            return hits[0]

    print("错误：未找到视频文件。已搜索：", file=sys.stderr)
    for d in searched:
        print(f"  - {d}", file=sys.stderr)
    print("请用 --video 显式给出，或设置环境变量 VRSD_VIDEO", file=sys.stderr)
    return None


def _glob_video(root, exts):
    hits = []
    for ext in exts:
        for p in glob.glob(os.path.join(root, "**", f"*.{ext}"), recursive=True):
            low = p.replace(os.sep, "/").lower()
            if any(f"/{x}/" in low for x in ("output", ".git", "node_modules")):
                continue
            hits.append(p)
    return sorted(hits)


def build_cmd(no, ctx):
    """构造某个阶段的命令行（list 形式，不经 shell，中文/含 ! 路径都安全）。"""
    s = os.path.join(SCRIPT_DIR, BY_NO[no][2])
    py = sys.executable
    out_dir, cfg = ctx["out_dir"], ctx["cfg"]
    out = cfg.get("output", {})
    paths = ctx["paths"]

    if no == 1:
        return [py, s, "--video", ctx["video"], "--out-dir", out_dir]
    if no == 2:
        return [py, s, "--wav", paths["wav"], "--out-dir", out_dir,
                "--model-dir", ctx["model_dir"]]
    if no == 3:
        cmd = [py, s, "--video", ctx["video"], "--out-dir", out_dir,
               "--interval", str(ctx["interval"])]
        if ctx.get("max_duration"):
            cmd += ["--max-duration", str(ctx["max_duration"])]
        return cmd
    if no == 4:
        # 未给 preset 时 04 只识别通用区，这是新视频第一遍探查的正常用法
        cmd = [py, s, "--out-dir", out_dir]
        if ctx["preset"]:
            cmd += ["--preset", ctx["preset"]]
        return cmd
    if no == 5:
        cmd = [py, s, "--input", paths["frames_ocr"], "--output", paths["layout"]]
        if ctx.get("emit_preset"):
            cmd += ["--emit-preset", ctx["emit_preset"]]
            # 草稿里的区域是比例坐标，必须知道真实分辨率才能换算；
            # 01 阶段探测过就直接用，否则 05 会退回 1920x1080 的假设
            info_path = paths["video_info"]
            if os.path.exists(info_path):
                try:
                    with open(info_path, encoding="utf-8") as f:
                        info = json.load(f)
                    if info.get("width") and info.get("height"):
                        cmd += ["--width", str(info["width"]),
                                "--height", str(info["height"])]
                except (OSError, ValueError):
                    pass
        return cmd
    if no == 6:
        return [py, s, "--preset", ctx["preset"],
                "--input", paths["frames_ocr"], "--output", paths["models"]]
    if no == 7:
        return [py, s, "--preset", ctx["preset"], "--out-dir", out_dir]
    if no == 8:
        return [py, s, "--preset", ctx["preset"], "--input", paths["models"],
                "--csv", paths["specs_csv"], "--html", paths["specs_html"]]
    if no == 9:
        return [py, s, "--preset", ctx["preset"], "--input", paths["models"],
                "--output", paths["dashboard"]]
    if no == 10:
        cmd = [py, s, "--out-dir", out_dir]
        if ctx["preset"]:
            cmd += ["--preset", ctx["preset"]]
        return cmd
    raise ValueError(f"未知阶段 {no}")


def prereq_missing(no, ctx):
    """返回该阶段缺什么前置条件（None 表示可以跑）。"""
    paths = ctx["paths"]
    if no == 1:
        return None if ctx["video"] else "视频路径"
    if no == 2:
        if not ctx.get("model_dir"):
            return "未给 --model-dir（本阶段可选，跳过不影响其余阶段）"
        return None if os.path.exists(paths["wav"]) else paths["wav"]
    if no == 3:
        return None if ctx["video"] else "视频路径"
    if no == 4:
        if not os.path.exists(paths["keyframes"]):
            return paths["keyframes"]
        return None if os.path.isdir(paths["frames_dir"]) else paths["frames_dir"]
    if no in (5, 6):
        return None if os.path.exists(paths["frames_ocr"]) else paths["frames_ocr"]
    if no in (7, 8, 9):
        return None if os.path.exists(paths["models"]) else paths["models"]
    if no == 10:
        return None if os.path.exists(paths["frames_ocr"]) else paths["frames_ocr"]
    return "未知阶段"


def run_stage(no, ctx):
    """执行一个阶段，返回 (ok, skipped_reason)。"""
    name, kind = BY_NO[no][1], BY_NO[no][3]
    cmd = build_cmd(no, ctx)

    print(flush=True)
    print("-" * 60, flush=True)
    print(f"阶段 {no} · {name} · {BY_NO[no][5]}", flush=True)
    print("-" * 60, flush=True)

    if ctx["dry_run"]:
        print("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
        return True, None

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    tail = []
    for line in proc.stdout:
        line = line.rstrip("\n")
        tail.append(line)
        if len(tail) > 20:
            tail.pop(0)
        if not ctx["quiet"]:
            print(line, flush=True)
    rc = proc.wait()

    if rc == 0:
        return True, None

    joined = "\n".join(tail)
    dep_missing = ("ModuleNotFoundError" in joined or "ImportError" in joined)
    if kind == "optional":
        why = "依赖缺失" if dep_missing else f"退出码 {rc}"
        print(f"警告：阶段 {no}（{name}）失败 —— {why}，继续执行后续阶段",
              flush=True)
        if ctx["quiet"]:
            print("\n".join(tail[-10:]), flush=True)
        return False, why

    print(f"错误：阶段 {no}（{name}）失败，退出码 {rc}", flush=True)
    if dep_missing:
        print("  看起来是依赖缺失，请按 scripts/check_env.py 的提示安装",
              flush=True)
    if ctx["quiet"]:
        print("\n".join(tail), flush=True)
    return False, f"退出码 {rc}"


def main():
    ap = argparse.ArgumentParser(
        description="横评视频参数提取流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="阶段：1 probe / 2 transcribe / 3 keyframes / 4 ocr / 5 discover "
               "/ 6 parse / 7 contact / 8 table / 9 dashboard / 10 chapters\n"
               "未给 --preset 时只能跑 1-5（探版式阶段），填好预设后再跑 6-9。")
    ap.add_argument("--preset", default=None,
                    help="品类预设名或 .yaml 绝对路径；跑 6-9 阶段时必需")
    ap.add_argument("--video", default=None, help="源视频路径")
    ap.add_argument("--out-dir", default="output", help="输出目录")
    ap.add_argument("--stages", default="all",
                    help="阶段列表，如 all / 1,3,4 / 1-4,6 / ocr,parse,dashboard")
    ap.add_argument("--skip", default=None, help="从已选阶段中排除，逗号分隔")
    ap.add_argument("--from", dest="from_stage", default=None,
                    help="从该阶段开始（含），编号或名称")
    ap.add_argument("--interval", type=float, default=None,
                    help="抽帧间隔秒（默认取配置 keyframes.interval）")
    ap.add_argument("--model-dir", default=None,
                    help="faster-whisper 本地模型目录；给了才会跑阶段 2")
    ap.add_argument("--emit-preset", default=None,
                    help="阶段 5 额外输出一份预设草稿骨架")
    ap.add_argument("--max-duration", type=float, default=None,
                    help="阶段 3 只解码前 N 秒（调试用）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印每个阶段的完整命令，不执行")
    ap.add_argument("--strict", action="store_true",
                    help="可选阶段失败也中止（默认只警告并继续）")
    ap.add_argument("--quiet", action="store_true",
                    help="不实时打印子阶段输出，只在失败时打印末尾")
    ap.add_argument("--list-presets", action="store_true",
                    help="列出可用品类预设后退出")
    args = ap.parse_args()

    if args.list_presets:
        for n in cfgmod.list_presets():
            print(n)
        return

    preset = args.preset
    if preset:
        cfg = cfgmod.load_config(preset)
    else:
        cfg = cfgmod.load_base()

    try:
        stages = parse_stages(args.stages)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    # 阶段 2 / 10 依赖转写：给了模型目录或已有转写产物才启用
    out = cfg.get("output", {})
    out_dir = args.out_dir
    transcript = os.path.join(out_dir, out.get("transcript_json", "transcript.json"))
    if args.stages.strip().lower() == "all":
        if args.model_dir or os.path.exists(transcript):
            stages = sorted(set(stages) | {2})
        if os.path.exists(transcript):
            stages = sorted(set(stages) | {10})

    if args.skip:
        try:
            stages = [n for n in stages if n not in parse_stages(args.skip)]
        except ValueError as e:
            print(f"错误：--skip {e}", file=sys.stderr)
            sys.exit(1)
    if args.from_stage:
        try:
            start = parse_stages(args.from_stage)[0]
        except (ValueError, IndexError):
            print(f"错误：--from {args.from_stage} 无法识别", file=sys.stderr)
            sys.exit(1)
        stages = [n for n in stages if n >= start]

    # 需要预设但没给 -> 直接剔除并说明
    if not preset:
        need = [n for n in stages if BY_NO[n][4]]
        if need:
            names = "、".join(f"{n}({BY_NO[n][1]})" for n in need)
            print(f"提示：未给 --preset，跳过需要品类预设的阶段：{names}",
                  flush=True)
            stages = [n for n in stages if not BY_NO[n][4]]
    if not stages:
        print("没有可执行的阶段", file=sys.stderr)
        sys.exit(1)

    video = args.video
    if video and not os.path.exists(video):
        print(f"错误：视频不存在: {video}", file=sys.stderr)
        sys.exit(1)
    if not video and any(n in stages for n in (1, 3)):
        video = find_video(cfg, out_dir)
        if not video:
            sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)
    paths = {
        "video_info": os.path.join(out_dir, out.get("video_info_json", "video_info.json")),
        "wav": os.path.join(out_dir, out.get("audio_wav", "audio_16k.wav")),
        "keyframes": os.path.join(out_dir, out.get("keyframes_json", "keyframes.json")),
        "frames_dir": os.path.join(out_dir, out.get("frames_dir", "frames")),
        "frames_ocr": os.path.join(out_dir, out.get("frames_ocr_json", "frames_ocr.json")),
        "models": os.path.join(out_dir, out.get("models_json", "models.json")),
        "layout": os.path.join(out_dir, out.get("layout_report", "layout_report.md")),
        "specs_csv": os.path.join(out_dir, out.get("specs_csv", "specs.csv")),
        "specs_html": os.path.join(out_dir, out.get("specs_table_html", "specs_table.html")),
        "dashboard": os.path.join(out_dir, out.get("dashboard_html", "dashboard.html")),
    }
    ctx = {
        "out_dir": out_dir, "cfg": cfg, "paths": paths, "preset": preset,
        "video": video, "model_dir": args.model_dir,
        "interval": args.interval or cfg.get("keyframes", {}).get("interval", 1.0),
        "emit_preset": args.emit_preset, "max_duration": args.max_duration,
        "dry_run": args.dry_run, "quiet": args.quiet, "strict": args.strict,
    }

    print("=" * 60, flush=True)
    print("横评视频参数提取流水线", flush=True)
    print("=" * 60, flush=True)
    print(f"预设: {preset or '（无，仅跑探版式阶段）'}", flush=True)
    print(f"视频: {video or '（本次不需要）'}", flush=True)
    print(f"输出: {os.path.abspath(out_dir)}", flush=True)
    print(f"阶段: {', '.join(f'{n}({BY_NO[n][1]})' for n in stages)}", flush=True)
    if args.dry_run:
        print("模式: dry-run（只打印命令）", flush=True)

    failed_optional = []
    for no in stages:
        miss = prereq_missing(no, ctx)
        if miss:
            if args.dry_run:
                # dry-run 只负责把命令打全，前置条件只作提示
                print(flush=True)
                print(f"阶段 {no} · {BY_NO[no][1]}："
                      f"（提示：当前缺少 {miss}，实际执行会跳过）", flush=True)
                run_stage(no, ctx)
                continue
            kind = BY_NO[no][3]
            print(flush=True)
            print(f"阶段 {no} · {BY_NO[no][1]}：跳过（缺少 {miss}）", flush=True)
            if kind == "core":
                print(f"错误：阶段 {no} 是核心阶段，无法跳过", file=sys.stderr)
                sys.exit(1)
            failed_optional.append((no, miss))
            continue

        ok, why = run_stage(no, ctx)
        if not ok and not args.dry_run:
            if BY_NO[no][3] == "core" or args.strict:
                sys.exit(1)
            failed_optional.append((no, why))

    print(flush=True)
    print("=" * 60, flush=True)
    if args.dry_run:
        print(f"dry-run 完成：{len(stages)} 个阶段的命令已打印", flush=True)
        return
    print("流水线完成", flush=True)
    if failed_optional:
        print(f"跳过/失败的可选阶段 {len(failed_optional)} 个：", flush=True)
        for no, why in failed_optional:
            print(f"  - {no} {BY_NO[no][1]}：{why}", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
