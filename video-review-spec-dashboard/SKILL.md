---
name: video-review-spec-dashboard
description: 把横评/测评视频（抖音等长视频）里逐台展示的商品参数卡，用「关键帧 OCR + 音频转写」双通道提取成结构化参数表，并生成单文件 ECharts 参数对比看板。当用户要做一个横向评测的参数对比表、性能对比看板、规格速查表，提到横评、测评、对比、参数表、规格表、对比图、看板，或需要从一个长视频里批量提取每个型号的数值时使用。品类不限于电视，手机/耳机/扫地机/笔记本/家电等同样适用，换品类只需换一份 preset 配置。
version: 0.1.0
agent_created: true
keywords:
  - 横评
  - 测评视频
  - 参数对比
  - 对比看板
  - 规格表
  - 看板生成
  - OCR 提取
  - 音频转写
  - 关键帧
  - 结构化提取
  - ECharts
requirements:
  network: true
  runtime: python
---

# 横评视频 → 结构化参数对比看板

## 0. 本 skill 保证什么、不保证什么

**保证可复用**：差异自适应抽帧、分区域 OCR、标签-值几何配对、机型聚类与冲突检测、
核对表与看板骨架。这套骨架与品类无关。

**每个新视频必须配的三项**：`fields`（字段表）、`identity`（品牌/型号识别）、
`footer_regions`（底部栏区域）。`config/presets/_template.yaml` 带注释，5 分钟能填完。

**可以留空**：品牌识别、特殊技术词典、章节定位。留空不影响主流程出结果。

**不保证**：不能下载视频（见第 1 节），不能保证 OCR 100% 正确（所以设计了一整套
溯源与人工核对闭环）。

---

## 1. 输入契约：本地视频，不是链接

**本 skill 不负责下载视频**，只处理已经落到本地的视频文件。
先要把视频弄到本地，再来跑流水线。

### 第 0 步：用 Douzy 把视频下载到本地

Douzy 是开源项目 douyin-downloader 的桌面端（当前 0.11.6），支持抖音 / TikTok /
YouTube / Telegram / X，粘贴链接即可下载并管理本地归档，有 Windows 与 macOS 安装包。

| 项 | 地址 |
|---|---|
| 上游项目 | `https://github.com/jiji262/douyin-downloader` |
| 维护中的 fork | `https://github.com/robinzwpl/douyin-downloader` |
| Douzy 安装包 | `https://github.com/jiji262/douyin-downloader/releases` |

**务必走桌面端，不要用 CLI。** 该项目 README 明确声明：抖音风控（ArgusSecurityPlugin）
自 2026-09 起已阻断 CLI 的单视频 / 图集 / 合集 / 音乐 / 点赞 / 收藏下载，
主页作品只剩 Playwright 浏览器兜底且成功率不保证，官方原话是
"Use Douzy for everyday downloads"。

下载器导出的元数据（`download_manifest.jsonl`、`douyin-history-*.csv`）建议一并留着，
作为溯源凭据。

---

## 2. 三步上手

### 第一步：检查环境

```bash
"C:/Program Files/Python314/python.exe" scripts/check_env.py
```

**解释器必须明确指定。** 本机受管 Python 3.13.12 是空环境（numpy 都没有，不可用）；
实际可用的是 `C:/Program Files/Python314/python.exe`（含 av、rapidocr、PIL、numpy）。

缺失依赖时脚本会直接给出安装命令，照抄执行即可。

### 第二步：为你的视频准备一份 preset

```bash
cp config/presets/_template.yaml config/presets/<你的品类>.yaml
```

只填三项就能跑：

| 配置段 | 作用 | 留空会怎样 |
|---|---|---|
| `fields` | 画面上有哪些字段、各是什么类型 | **必填，缺了直接报错** |
| `identity.brand_map` | 品牌识别表 | 留空则不识别品牌，整行标题当型号 |
| `footer_regions` | 底部横排栏的区域划分 | 留空则跳过底部栏提取 |

不确定画面版式时，先跑 `05_discover.py` 生成版式报告，它会统计跨帧标签频次、
给出标题行与底部栏的建议边界，照着填即可。

### 第三步：跑流水线

```bash
PY="C:/Program Files/Python314/python.exe"
$PY scripts/pipeline.py --preset <你的品类> --video <视频路径> all
```

只重跑后半段（已有 OCR 结果时）：

```bash
$PY scripts/06_parse.py --preset tv75_science \
    --input output/frames_ocr.json --output output/models.json
```

---

## 3. 流水线阶段

| 阶段 | 脚本 | 产物 | 说明 |
|---|---|---|---|
| 0 下载 | Douzy（外部） | 本地 mp4 | 本 skill 不管这一步 |
| 1 探测/音频 | `01_probe.py` | 视频信息、`audio_16k.wav` | |
| 2 转写（可选） | `02_transcribe.py` | `transcript.json` | 需要 faster-whisper 模型；**缺了也能出全套产物**，只是少了章节定位 |
| 3 抽帧 | `03_keyframes.py` | `frames/*.jpg`、`keyframes.json` | 差异自适应，不靠固定间隔 |
| 4 OCR | `04_ocr.py` | `frames_ocr.json` | 分区域识别 + 预处理 |
| 5 版式探查 | `05_discover.py` | `layout_report.md` | 新视频先跑它，省去手量坐标 |
| 6 参数解析 | `06_parse.py` | `models.json` | 核心环节，配置驱动 |
| 7 人工核对 | `07_contact_sheet.py` | `contact_sheet_*.jpg` | 分批出图逐项核对 |
| 8 核对表 | `08_specs_table.py` | `specs.csv`、`specs_table.html` | 全字段平铺 |
| 9 看板 | `09_dashboard.py` | `dashboard.html` | 单文件、内嵌 ECharts |
| 10 章节（可选） | `10_chapters.py` | `chapters.json` | 依赖转写结果 |

---

## 4. 铁律（违反即返工）

1. **缺失一律标「未提取」，不填 0、不推测填充。** 填 0 会让下游图表把"没数据"
   当成"真的是 0"，是这类任务最常见也最致命的错误。
2. **冲突不静默覆盖。** 同一字段出现不同值时记入 `conflicts` 并保留现值，交人工处理。
3. **每个值都可溯源。** 必须带 `source`、`source_timestamp`、`raw` 原文。
4. **口径陷阱显式化。** 色域有 sRGB/DCI-P3/BT.2020/BT.709 多种标准，量纲不同不可混算；
   刷新率要区分原生与倍频；价格可能是补贴后价。每个字段带 `note` 说明。
5. **配置文件里没有的东西不许凭空推断。** 参数卡解析尤其如此：早期版本曾因
   "按 x 排序取最近值"这一条自动规则，导致 5 台机型的刷新率全部解析错误。

---

## 5. 配置说明

两层配置，预设覆盖默认：

- `config/default.yaml` —— 几何阈值、渲染规则、输出文件名，与品类无关
- `config/presets/<名称>.yaml` —— 品牌表、字段表、底部栏、人工确认值、看板档位

### 字段类型（type）选择

| type | 适用 | 例子 |
|---|---|---|
| `money` | 金额 | 价格 |
| `enum_map` | 从固定词典里取值 | 屏幕类型（Mini LED / OLED / VA软屏…） |
| `zones` | 分区数（含无分区/区间形态） | 背光分区 |
| `zones_named` | 品牌专属控光口径 | 海信玲珑控色区 |
| `range_num` | 可能是区间的数值 | 峰值亮度 |
| `refresh_hz` | 刷新率，区分原生与降分辨率 | 原生 4K 144Hz |
| `percent_std` | 带标准的百分比 | 色域（分标准不可混算） |
| `capacity_gb` | 容量 | 内存、存储 |
| `cpu_text` | 芯片型号 | 四核A73 |
| `size_inch` | 英寸尺寸 | 屏幕尺寸 |
| `count_by_version` | 按版本分别计数 | HDMI 2.1 / 2.0 各几个 |
| `int_unit` | 「N 个」计数 | 发声单元 |
| `text_short` | 纯文本 | 认证、游戏特性 |

**注意**：只有 `text_short` 会做短文本兜底收录。数值类字段解析不出就是解析不出，
不会拿原文凑数，否则会污染数值字段。

---

## 6. Troubleshooting

| 现象 | 根因 | 解法 |
|---|---|---|
| 所有帧识别到 0 个文本框 | RapidOCR **不接受 PIL Image 对象**，只收路径 / numpy / bytes；传 PIL 抛 LoadImageError，若被 try/except 吞掉就表现为全 0 | 传 numpy 数组或文件路径 |
| `TypeError: metadata_errors` | `av` 新版本移除了该参数，而 `faster-whisper` 仍传它 | 本地已有 16kHz WAV 时，用 `wave` 读成 float32 numpy 直接喂 `model.transcribe(array)`，绕开 `decode_audio` |
| 图表一片空白 | `cdn.jsdelivr.net` 本机不可达 | 看板改为内嵌 `assets/echarts.min.js`（默认已开启） |
| `ImportError: turbojpeg` | 未装 PyTurboJPEG | 抽帧会回落到 PIL 保存，速度略慢但不影响结果 |
| 视频路径含 `!` 报错 | bash 双引号内触发历史展开 | 用 Python 内部 glob，不要经 shell 传参 |
| HuggingFace 连不上 | 可能 502；`hf-mirror.com` 返回 308 不可用 | 用 PowerShell `WebClient` 直连下载到本地目录，再用路径加载 |
| 底部栏字段大量缺失 | 按等分切分区域无效 | 必须按**实测 x 边界**切分，实测覆盖率可从 2/32 提升到 31/32 |
| 型号被识别成 "P3" | 色域标准词被当成型号 | 填 `identity.model_negative` 负向词表 |
| 开篇总览页导致错配 | 多机型卡片同屏，文本框混杂 | 设 `exclude_before_sec` 整体丢弃该时间点之前的帧 |

---

## 7. 交付区分（别搞混）

| 文件 | 是什么 | 给谁看 |
|---|---|---|
| `dashboard.html` | **看板**，含图表、画像卡、选购建议 | 最终交付 |
| `specs_table.html` | **核对表**，全字段平铺无图表 | 内部逐项核对用 |

这两个是不同文件、不同用途。曾发生过误把核对表当看板交付的事故。

---

## 8. 已知限制

- 依赖抽帧与 OCR 质量，参数卡文字被压在花哨背景上时会下降，需人工核对兜底
- 音频转写通道需要额外下载数百 MB 模型，属可选环节
- 换视频分辨率时，`card.title_max_y`（标题行纵向阈值）需按同比例调整
- `03`/`04` 阶段依赖视频本体与 OCR 环境，无法纯离线回归；`06` 及之后可纯文本回归
