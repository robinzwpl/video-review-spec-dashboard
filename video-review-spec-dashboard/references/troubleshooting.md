# 踩坑清单

按「现象 → 根因 → 解法」组织。前三条是真正造成过事故的。

---

## 环境坑

### 1. 所有帧都识别到 0 个文本框

- **现象**：OCR 跑完不报错，但结果是 0 帧有文字、0 个文本框
- **根因**：RapidOCR **不接受 PIL Image 对象**，只收路径 / numpy 数组 / bytes。
  传 PIL 会抛 `LoadImageError`，如果这个异常被 try/except 吞掉，
  就表现为"全部帧识别为空"而不是报错
- **解法**：传 numpy 数组或文件路径
- **附注**：该版本 RapidOCR 的 `score` 返回字符串，要 `float()` 而不是 `round()`

### 2. `TypeError: metadata_errors`

- **现象**：转写阶段崩溃
- **根因**：`faster-whisper` 调用 `av.open(..., metadata_errors="ignore")`，
  而 `av` 19.0 起移除了该参数。本机实测为 **18.1.0**（该参数仍在），
  但 `02_transcribe.py` 始终走绕过路径，以保证跨版本都能用
- **解法**：本地已有 16kHz WAV 时，用 `wave` 读成 float32 numpy 数组，
  直接喂 `model.transcribe(array)`，绕开 `decode_audio`

### 3. 看板图表一片空白

- **现象**：HTML 打开后布局在，但图全空，控制台无报错
- **根因**：`cdn.jsdelivr.net` 在本机不可达
- **解法**：把 `echarts.min.js` 内嵌进 HTML（本 skill 默认已开启）

### 4. `ImportError: turbojpeg`

- **现象**：抽帧脚本起不来
- **根因**：未装 PyTurboJPEG
- **解法**：`03_keyframes.py` 已内置回落——未装时自动打印提示并用 PIL 保存，
  结果可用，只是抽帧慢一些。想提速就装 PyTurboJPEG
  （注意：PIL 与 turbojpeg 是不同编码器，重抽的帧与既有帧会有像素级差异，
  因此不要拿两者做逐字节比对）
- **附注**：`turbojpeg` 的导入名是 `from turbojpeg import compress`（不是 `TurboJPEG`）；
  枚举是 `SAMP.Y420`（不是 YUV420）；参数名是 `pixelformat`（不是 `pixel_format`）；
  `subsamp` 必传

### 5. 视频路径含 `!` 导致报错

- **根因**：bash 双引号内 `!` 触发历史展开
- **解法**：用 Python 内部 glob 找文件，不要经 shell 传参

### 6. HuggingFace 下载模型失败

- **根因**：可能 502；`hf-mirror.com` 返回 308 不可用
- **解法**：用 PowerShell 的 `WebClient` 直连下载到本地目录，再用路径加载

### 7. 后台进程随 shell 退出被回收

- **现象**：`nohup ... &` 启动的预览服务或长任务，过一会儿就没了
- **解法**：长任务与预览服务用任务机制启动，不要用 shell 后台

### 8. 受管 Python 是空环境

- **现象**：`import numpy` 都失败
- **根因**：本机受管 Python 3.13.12 只装了 pip，什么都没有
- **解法**：明确指定 `C:/Program Files/Python314/python.exe`（含 av、rapidocr、PIL、numpy）

### 9. pip 装包报 `from versions: none`

- **根因**：本机 pip 访问清华源会返回 HTTP 403，不是网络或代理问题
- **解法**：换阿里云源 `-i https://mirrors.aliyun.com/pypi/simple/`

---

## 算法坑

### 10. 刷新率普遍偏低

- **现象**：多台机型的刷新率被记成 60Hz、120Hz 等偏小值
- **根因**：配对时"按 x 排序取最近值"，误取到下一行的补充说明文字
- **解法**：改为先按 |Δy| 取最近行，同行内再按 x 拼接（M4）

### 11. 底部栏字段大量缺失

- **现象**：内存、存储、HDMI 这类字段覆盖率极低（实测曾只有 2/32）
- **根因**：底部横排栏与字幕区域重叠，且按等分切分区域不对
- **解法**：按**实测 x 边界**切分区域，并靠 region 标签区分字段归属
  （实测覆盖率提升到 31/32）

### 12. 型号被识别成 "P3"

- **现象**：型号字段出现色域标准词
- **根因**：负向词表缺失
- **解法**：填 `identity.model_negative`，把 DCI / P3 / BT / 2020 / 709 / sRGB 等排除

### 13. 开篇几台机型的参数全错

- **现象**：最前面若干条记录的参数明显不属于同一台机器
- **根因**：开篇总览页多机型卡片同屏，文本框混杂导致错配
- **解法**：设 `exclude_before_sec` 整体丢弃该时间点之前的帧（M5）
