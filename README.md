# 横评视频 → 结构化参数对比看板

把横评 / 测评视频里逐台展示的商品参数卡，用「关键帧 OCR + 音频转写」双通道提取成
结构化参数表，并生成单文件 ECharts 参数对比看板。

品类不限于电视 —— 手机、耳机、扫地机、笔记本、家电同样适用，换品类只需换一份配置。

---

## 先看这里：本仓库只处理本地视频

**这套流程不能下载视频**，它的输入是已经下载到本地的视频文件。

### 第 0 步：用 Douzy 把视频下载到本地

Douzy 是开源项目 [douyin-downloader](https://github.com/jiji262/douyin-downloader) 的
桌面端（当前 0.11.6），支持抖音 / TikTok / YouTube / Telegram / X，粘贴链接即可下载并
管理本地归档，有 Windows 与 macOS 安装包。

| 项 | 地址 |
|---|---|
| 上游项目 | https://github.com/jiji262/douyin-downloader |
| 维护中的 fork | https://github.com/robinzwpl/douyin-downloader |
| Douzy 安装包（Windows / macOS） | https://github.com/jiji262/douyin-downloader/releases |

**请走桌面端，不要用命令行版本。** 该项目 README 明确声明：抖音风控
（ArgusSecurityPlugin）自 2026-09 起已阻断 CLI 的单视频 / 图集 / 合集 / 音乐 / 点赞 /
收藏下载，主页作品只剩 Playwright 浏览器兜底且成功率不保证，官方建议日常下载一律使用
Douzy。

下载器导出的元数据建议一并留着，作为溯源凭据（本仓库根目录就有一次实际下载的样例：
`download_manifest.jsonl`、`douyin-history-*.csv`）。

---

## 目录导航

```
.
├── README.md                      本文件
├── LICENSE                        MIT
├── 流程步骤.txt                    最初的需求记述
├── douyin-history-* / download_manifest.jsonl    下载溯源凭据
│
└── video-review-spec-dashboard/   skill 本体，可独立复制使用
    ├── SKILL.md                   skill 入口，从这里读起
    ├── README.md                  快速上手
    ├── config/                    配置（通用默认 + 品类预设）
    ├── scripts/                   流水线脚本
    ├── references/                方法论与踩坑清单
    ├── assets/                    内嵌用的 echarts.min.js
    ├── examples/                  一次完整跑通的成品样例
    └── tests/                     回归夹具与基线
```

**源码只有一套**，全部在 `video-review-spec-dashboard/scripts/` 下，不存在第二份副本。

---

## 快速开始

```bash
PY="C:/Program Files/Python314/python.exe"
cd video-review-spec-dashboard

# 1 检查环境（缺什么会直接给出安装命令）
"$PY" scripts/check_env.py

# 2 复制配置模板，按你的视频填写
cp config/presets/_template.yaml config/presets/我的品类.yaml

# 3 跑流水线
"$PY" scripts/pipeline.py --preset 我的品类 --video <视频路径> all
```

**Python 解释器必须明确指定。** 本机受管 Python 3.13.12 是空环境（连 numpy 都没有），
实际可用的是 `C:/Program Files/Python314/python.exe`。

---

## 成品样例

`video-review-spec-dashboard/examples/tv75-2026-09/` 下是一次完整跑通的结果：

- `tv_dashboard.html` —— 32 台 75 寸电视的分价位性能看板（单文件，双击即开）
- `tv_specs.csv` —— 同数据的表格，32 条机型数据 + 1 行表头，共 25 列

复现命令与已知限制见该目录下的 README。

---

## 哪些文件没有进仓库

`.gitignore` 排除了体积大或可重新生成的产物：

- `科技绝对值/` —— 113MB 源视频
- `output/` —— 226 张关键帧、日志、转写结果、核对拼图
- `.workbuddy/` —— 项目工作数据，其中的知识已提炼进 `references/`

原始过程脚本已整体迁入 skill 目录并做了通用化改造，不存在两份重复代码。

---

## 许可证

MIT，见 LICENSE。
