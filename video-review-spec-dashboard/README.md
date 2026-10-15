# video-review-spec-dashboard

把横评 / 测评视频里逐台展示的商品参数卡，提取成结构化参数并生成对比看板。

完整说明见 [SKILL.md](SKILL.md)。这里是 30 秒上手版。

---

## 前置：视频要在本地

本 skill 不下载视频。用 Douzy（douyin-downloader 的桌面端）先把视频下到本地：

- 项目：https://github.com/jiji262/douyin-downloader
- 安装包：https://github.com/jiji262/douyin-downloader/releases

不要用该项目的 CLI —— 抖音风控已阻断 CLI 的单视频下载，官方建议一律用桌面端。

---

## 三步跑通

```bash
PY="C:/Program Files/Python314/python.exe"

# 1 检查环境
"$PY" scripts/check_env.py

# 2 准备配置（只填 fields / identity / footer_regions 三项即可）
cp config/presets/_template.yaml config/presets/我的品类.yaml

# 3 跑流水线
"$PY" scripts/pipeline.py --preset 我的品类 --video <视频路径> all
```

Python 必须指定 `C:/Program Files/Python314/python.exe`，
本机受管 Python 3.13.12 是空环境不可用。

---

## 流水线

| 阶段 | 脚本 | 产物 |
|---|---|---|
| 1 探测/音频 | `01_probe.py` | 视频信息、wav |
| 2 转写（可选） | `02_transcribe.py` | `transcript.json` |
| 3 抽帧 | `03_keyframes.py` | `frames/`、`keyframes.json` |
| 4 OCR | `04_ocr.py` | `frames_ocr.json` |
| 5 版式探查 | `05_discover.py` | `layout_report.md` |
| 6 参数解析 | `06_parse.py` | `models.json` |
| 7 人工核对 | `07_contact_sheet.py` | `contact_sheet_*.jpg` |
| 8 核对表 | `08_specs_table.py` | `specs.csv`、`specs_table.html` |
| 9 看板 | `09_dashboard.py` | `dashboard.html` |
| 10 章节（可选） | `10_chapters.py` | `chapters.json` |

只重跑解析（已有 OCR 结果时）：

```bash
"$PY" scripts/06_parse.py --preset tv75_science \
    --input output/frames_ocr.json --output output/models.json
```

---

## 回归测试

基线冻结在 `tests/expected/tv75_models.json`（32 机型，不允许随意更新）。

```bash
"$PY" tests/test_regression.py
```

通过时会打印「32 个机型，字段与数值均与基线一致」。

---

## 本机部署为 skill

用 junction 链接到 skills 目录（不需要管理员权限）：

```cmd
mklink /J "C:\Users\DELL\.workbuddy\skills\video-review-spec-dashboard" "<本目录绝对路径>"
```

改这里的文件即改 skill，无需同步。

---

## 目录

```
config/      通用默认 + 品类预设
scripts/     流水线脚本与 lib/
references/  方法论、踩坑清单、字段手册
assets/      echarts.min.js（看板内嵌）
examples/    一次完整跑通的成品
tests/       回归夹具与基线
```
