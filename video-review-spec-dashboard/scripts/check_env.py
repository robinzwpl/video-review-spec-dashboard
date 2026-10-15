# -*- coding: utf-8 -*-
"""
环境检查：确认依赖是否齐备，缺失时直接给出可复制的安装命令。

用法：
    "C:/Program Files/Python314/python.exe" scripts/check_env.py

退出码：0 齐全；1 有缺失或解释器不可用。
"""
import sys
import shutil

# 必需依赖：缺了主流程跑不起来
REQUIRED = [
    ("numpy", "numpy", "numpy"),
    ("PIL", "pillow", "Pillow"),
    ("yaml", "pyyaml", "PyYAML"),
    ("av", "av", "PyAV（视频解码）"),
    ("rapidocr_onnxruntime", "rapidocr-onnxruntime", "RapidOCR（文字识别）"),
]

# 可选依赖：缺了不影响主流程出结果
OPTIONAL = [
    ("faster_whisper", "faster-whisper",
     "音频转写，仅章节定位需要；缺失不影响参数提取"),
    ("turbojpeg", "PyTurboJPEG",
     "抽帧加速，缺失时回落 PIL 保存，速度略慢"),
]


def probe(mod_name):
    """返回 (是否可用, 版本字符串)。"""
    try:
        mod = __import__(mod_name)
        return True, getattr(mod, "__version__", "已安装")
    except Exception:
        return False, ""


def main():
    print(f"Python 解释器: {sys.executable}")
    print(f"Python 版本  : {sys.version.split()[0]}")
    print()

    missing_required = []
    missing_optional = []

    print("必需依赖：")
    for mod, pkg, desc in REQUIRED:
        ok, ver = probe(mod)
        mark = "OK  " if ok else "缺失"
        print(f"  [{mark}] {pkg:24s} {desc}")
        if not ok:
            missing_required.append(pkg)
    print()

    print("可选依赖：")
    for mod, pkg, desc in OPTIONAL:
        ok, ver = probe(mod)
        mark = "OK  " if ok else "缺失"
        print(f"  [{mark}] {pkg:24s} {desc}")
        if not ok:
            missing_optional.append(pkg)
    print()

    # 外部工具
    ffmpeg = shutil.which("ffmpeg")
    print(f"外部工具 ffmpeg: {'已找到 ' + ffmpeg if ffmpeg else '未找到（01_probe.py 需要）'}")
    print()

    if not missing_required and not missing_optional:
        print("环境齐全。")
        return 0

    if missing_required:
        print("缺失必需依赖，用下面的命令安装：")
        print(f'  "{sys.executable}" -m pip install ' + " ".join(missing_required))
        print()
        print("注意：本机 pip 访问清华源会返回 403，改用阿里云源：")
        print(f'  "{sys.executable}" -m pip install -i '
              f'https://mirrors.aliyun.com/pypi/simple/ '
              + " ".join(missing_required))

    if missing_optional:
        print("缺失可选依赖（不影响主流程），需要时再装：")
        print(f'  "{sys.executable}" -m pip install ' + " ".join(missing_optional))

    return 1 if missing_required else 0


if __name__ == "__main__":
    sys.exit(main())
