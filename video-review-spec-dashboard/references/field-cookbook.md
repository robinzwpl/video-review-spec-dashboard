# 字段类型手册

## 一、这份手册解决什么问题

写品类预设（config/presets/&lt;名称&gt;.yaml）时，最核心的一步是给每个字段挑一个 `type`。
`type` 决定 `scripts/lib/schema.py` 用哪个 handler 去解析 OCR 出来的文本。

挑错了不会报错——只会**静默解析不出**（该字段在所有机型上都是「未提取」），
或者更糟：解析出一个看起来对、实际错的值。本手册给出全部 13 种 type 的处理逻辑、
真实配置片段和适用边界，以及**换品类前必读的 6 处内置假设**（第五章）。

行号均指 `scripts/lib/schema.py`。

---

## 二、类型速查表

| type | 一句话用途 | 输入例子 | 输出 value | 短文本兜底 |
|---|---|---|---|---|
| `money` | 金额 / 价格 | `¥3299`、`3,299元` | float | 否 |
| `enum_map` | 值来自封闭词典的分类 | `QD-Mini LED` | 词典里的 `name` | 否 |
| `size_inch` | 两位数英寸尺寸 | `75英寸` | int | 否 |
| `zones` | 分区数（无 / 精确 / 区间三态） | `300级`、`100-200级`、`无分区` | int | 否 |
| `zones_named` | 品牌专属控光口径 | `16个控色区` | int 或原文 | 否 |
| `range_num` | 可能是区间的数值（取上限） | `1500-2000 nits` | int | 否 |
| `refresh_hz` | 刷新率（区分原生 4K） | `4K 144Hz`、`144Hz` | int | 否 |
| `percent_std` | 百分比但标准不唯一 | `95% DCI-P3` | float | 否 |
| `capacity_gb` | GB 容量 | `4GB` | int | 否 |
| `cpu_text` | 芯片型号文本 | `四核A73` | str | 否 |
| `count_by_version` | 按协议版本分别计数 | `HDMI2.1 2个` | int | 否 |
| `int_unit` | 「N 个」形态计数 | `2个` | int | 否 |
| `text_short` | 纯文本，无法结构化 | `288Hz`、`杜比全景声` | 原文 | **是** |

**只有 `text_short` 会做短文本兜底**（`FALLBACK_TYPES`，:198）。
其余类型解析不出就是 `None`，绝不用原文凑数——这是铁律 M8。

---

## 三、逐类型详解

### 3.1 `money` — `_money` (:18)

**处理逻辑**：正则 `[¥￥]?\s*([\d,]+(?:\.\d+)?)` 抓第一个数字，去千分位后转 float。
`unit` 取 `fd.unit`（默认「元」），`fd.note` 原样透传到结果的 `note`。

**配置参数**：`unit`、`note`、`aliases`

**tv75 真实片段**：
```yaml
- name: 价格
  label: "参考价(元)"
  type: money
  unit: "元"
  aliases: ["参考价", "价格", "售价", "到手价"]
  note: "参考价为国补后价格，需符合地区补贴条件"
```

**适用**：价格、金额。
**不适用**：带单位的非货币数值（用 `int_unit` / `range_num`）。
**注意**：`note` 是唯一能写价格口径的地方——「国补后价」「限时价」「到手价」都要在这里说清，
否则下游会把不同口径的数字放在一起比较。

---

### 3.2 `enum_map` — `_enum_map` (:27)

**处理逻辑**：按 `patterns` 列表**顺序**逐个 `re.search(p["pattern"], v, re.I)`，
**首个命中的**返回其 `name`。

**配置参数**：`patterns`（有序）、`unit`

**tv75 真实片段**：
```yaml
- name: 屏幕
  type: enum_map
  aliases: ["屏幕", "面板", "屏体", "软屏", "硬屏"]
  patterns:
    - {pattern: "QD-?Mini\\s*LED", name: "QD-Mini LED"}
    - {pattern: "SQD-?Mini\\s*LED", name: "SQD-Mini LED"}
    - {pattern: "Mini\\s*LED", name: "Mini LED"}
    ...
    - {pattern: "直下式\\s*/?\\s*DLED", name: "直下式DLED"}
    - {pattern: "直下式", name: "直下式"}
    - {pattern: "DLED", name: "DLED"}
```

**适用**：值来自固定封闭词典的分类字段（面板类型、材质、接口形态）。
**不适用**：值域开放的字段（型号、芯片名）。

> **顺序敏感，这是最容易出错的地方。**
> 更特殊的写法必须排在更通用的前面：`QD-Mini LED` 必须在 `Mini LED` 之前，
> `SQD-Mini LED` 又必须在 `QD-Mini LED` 之前。反过来写会让所有 QD-Mini LED 都被记成 Mini LED，
> 且不报任何错。

---

### 3.3 `zones` — `_zones` (:35)

**处理逻辑**：三分支，按顺序判定
1. 命中 `no_zone_pattern` → `{value: 0, exact: True, zone_type: "无分区"}`
2. 正则 `(\d{3,5})\s*个?` → 精确值，`exact: True`
3. 正则 `(\d{2,5})[-—~至](\d{2,5})\s*级` → 取上限 `hi`，带 `value_min`，`exact: False`

同时扫描 `zone_types` 列表，命中的口径词写进 `zone_type`。

**配置参数**：`no_zone_pattern`、`zone_types`、`notes{none,exact,range}`、`unit`

**tv75 真实片段**：
```yaml
- name: 分区数
  type: zones
  unit: "区"
  aliases: ["背光分区", "分区"]
  no_zone_pattern: "无独立背光分区|无光分区|无分区"
  zone_types: ["万象分区", "超级分区", "独立背光分区", "背光分区"]
  notes:
    none: "无独立背光分区（侧光/直下式无控光分区），记为0"
    exact: "分区类型：{zone_type}；需确认单/双/多重分区，算法不同不可直接比较"
    range: "卡片标注 {lo}-{hi} 级分区区间，取上限；非精确分区数"
```

**适用**：存在「无 / 精确 / 区间」三态的计数（背光分区、控光分区、档位数）。
**不适用**：只有单一形态的计数（用 `int_unit`）。

> **坑**：区间分支要求文本以「**级**」字收尾。写成 `100-200` 或 `100-200区` 抓不到。
> 见第五章 5.4。

---

### 3.4 `zones_named` — `_zones_named` (:66)

**处理逻辑**：先试 `(\d{2,5})\s*个` 取数字；否则若文本含「控色区」则**原文收录**（value 是字符串）。

**配置参数**：`unit`、`note`、`aliases`

**tv75 真实片段**：
```yaml
- name: 控色区
  type: zones_named
  unit: "个控色区"
  aliases: ["玲珑控色区", "控色区", "品牌控色区", "控色"]
  note: "玲珑控色区（海信专属口径），与背光分区算法不同，不可与背光分区直接比较"
```

**适用**：品牌专属、与通用口径**不可混算**的同类指标，必须单列一栏。
**不适用**：可以和其他机型横向比较的通用指标。

---

### 3.5 `range_num` — `_range_num` (:77)

**处理逻辑**：
1. `(\d{3,5})[-—~至](\d{3,5})` → `{value: hi, value_min: lo, is_range: True}`
2. 否则 `(\d{3,5})` → 单值，`is_range: False`

**配置参数**：`unit`、`notes{range,single}`

**tv75 真实片段**：
```yaml
- name: 峰值亮度
  type: range_num
  unit: "nit"
  aliases: ["亮度范围", "亮度", "峰值亮度"]
  notes:
    range: "标称区间 {lo}-{hi} nit，取上限；注意测试窗口口径"
    single: "需注意测试窗口口径（3%/10%窗口 vs 全屏）"
```

**适用**：可能标成区间的数值，且约定取上限（亮度、续航、功率）。
**不适用**：区间两端都有意义、不能取上限的（需新增 type）。

> **坑**：要求**至少 3 位数字**。`80nit` 抓不到。见第五章 5.6。

---

### 3.6 `refresh_hz` — `_refresh_hz` (:93)

**处理逻辑**：先试 `4K\s*(\d{2,3})\s*Hz` → `is_native: True`；
否则 `(\d{2,3})\s*Hz` → `is_native: False`（即「可能有水分」的高刷）。

**配置参数**：`notes{native,non_native}`、`boost_field` / `boost_pattern` / `boost_note`

**tv75 真实片段**：
```yaml
- name: 刷新率
  type: refresh_hz
  aliases: ["原生刷新", "刷新率", "刷新"]
  notes:
    native: "原生 4K 刷新率"
    non_native: "卡片未标4K，可能为 2K/降分辨率模式下的高刷"
  # 倍频值单独成字段，不与原生刷新率混算
  boost_field: "刷新率_倍频"
  boost_pattern: '(\d{2,3})\s*Hz\s*[（(]?\s*倍频'
  boost_note: "倍频值，非原生刷新率，不可与原生值直接比较"
```

**适用**：「同数值不同口径」的指标——刷新率最典型（原生 4K / 倍频 / 2K 模式高刷，
三者数字差 2-3 倍但说的是同一台机器）。配 `boost_field` 可把倍频值拆成独立字段，
避免污染原生值。

> 这套设计来自一次真实事故：早期按 x 坐标取最近值，把下一行的「144Hz高刷·HDMI1080P输入」
> 当成原生刷新率，导致 5 台机型的刷新率全错。见 `troubleshooting.md`。

---

### 3.7 `percent_std` — `_percent_std` (:107)

**处理逻辑**：遍历 `standards`，首个命中的标准取其数字与 `name`。
`val > 100` 时**不改写**（覆盖率不可能超过 100%），而是保留原值 + `ocr_error: True` 交人工。

**配置参数**：`standards`（有序，`{pattern, name}`）、`notes{over100, srgb, default}`

**tv75 真实片段**：
```yaml
- name: 色域
  type: percent_std
  aliases: ["色域", "色彩覆盖"]
  standards:
    - {pattern: '(\d{2,3}(?:\.\d)?)\s*%\s*DCI-?P3', name: "% DCI-P3"}
    - {pattern: '(\d{2,3}(?:\.\d)?)\s*%\s*BT\.?2020', name: "% BT.2020"}
    - {pattern: '(\d{2,3}(?:\.\d)?)\s*%\s*BT\.?709', name: "% BT.709"}
    - {pattern: '(\d{2,3}(?:\.\d)?)\s*%\s*sRGB', name: "% sRGB"}
  notes:
    over100: "画面标注为 {val}%，超过 100% 覆盖率上限，技术上不成立（原图如此，非识别误差），需人工核对"
    srgb: "色域标准为 sRGB，与 DCI-P3/BT.2020 非同一量纲，不可直接比较"
    default: "色域标准 {std}，与其他标准不可直接比较"
```

**适用**：百分比但**标准不唯一**、量纲不可混算的指标（色域、色准、覆盖率）。
**不适用**：标准唯一的百分比。

> `over100` 的处理是刻意的：画面确实出现过 `130% BT.709`、`110% DCI-P3` 这类标注。
> 已核实为**画面原图如此**（OCR 无误），技术上不成立。这里据实记录并标「需人工核对」，
> **不擅自改写成 100%**——擅自改写会掩盖"这个视频的标注本身有问题"这个事实。

---

### 3.8 `capacity_gb` — `_capacity_gb` (:130)

**处理逻辑**：`(\d+)\s*GB`（忽略大小写）→ int。

**配置参数**：`unit`（默认 GB）、`aliases`

**tv75 真实片段**：
```yaml
- name: 内存
  type: capacity_gb
  unit: "GB"
  aliases: ["运行内存", "内存"]
```

**适用**：内存、存储、显存等 GB 容量。大小写不敏感，`4gb` 也能抓到。

---

### 3.9 `cpu_text` — `_cpu_text` (:138)

**处理逻辑**：捕获 `(?:双核|单核|四核|五核|八核|四核A|双核A)?\s*[A-Z]?\d{2,3}(?:\+\s*…)*`，
返回字符串（不是数字）。

**配置参数**：`unit`、`aliases`

**tv75 真实片段**：
```yaml
- name: 处理器
  type: cpu_text
  unit: ""
  aliases: ["处理器", "芯片", "cpu", "CPU"]
```

**适用**：芯片型号（四核A73、双核A55+A73）。
**不适用**：非中文核数词 + A/数字 形态的芯片名（如 `MT9652`、`Pentonic 800`）——
见第五章 5.2，需改代码或改用 `text_short`。

---

### 3.10 `size_inch` — `_size_inch` (:147)

**处理逻辑**：`(\d{2})\s*(?:英寸|寸)` → int。

**配置参数**：`unit`（默认「英寸」）、`aliases`
**适用**：屏幕尺寸这类两位数英寸值。**只匹配 2 位数字**，`5.5英寸` 抓不到（见第五章 5.5）。

---

### 3.11 `count_by_version` — `_count_by_version` (:155)

**处理逻辑**：对每个 `versions[i]` 拼正则 `HDMI\s*<ver>\D{0,8}?(\d+)\s*个?`，首个命中返回。

**配置参数**：`versions`（有序）、`unit`

**tv75 真实片段**：
```yaml
- name: HDMI
  type: count_by_version
  unit: "个"
  aliases: ["hdm", "接口"]
  versions: ["2.1", "2.0"]
```

**适用**：按协议版本号分别计数的接口（HDMI 2.1 / 2.0 各几个）。
**坑**：正则里 **"HDMI" 是写死的**，USB / DP / 雷电接口用不了（见第五章 5.1）。

---

### 3.12 `int_unit` — `_int_unit` (:166)

**处理逻辑**：`(\d+)\s*个` → int。

**配置参数**：`unit`（默认「个」）、`aliases`
**适用**：「N 个」形态的纯计数（扬声器数、接口数）。
**坑**：必须有「个」字，`HDMI2.1×4` 这种写法抓不到。

---

### 3.13 `text_short` — `_text_short` (:174)

**处理逻辑**：handler 本身**直接返回 None**，完全依赖 `parse_value` 的兜底：
文本长度 ≤ `parse.fallback_text_max_len`（默认 24）时原样收录为 `{value: 原文, unit: ""}`。

**配置参数**：`unit`、`aliases`

**tv75 真实片段**：
```yaml
  # 不是画面标签，由倍频提取生成，因此不设 aliases（设了会参与标签匹配）
- name: 刷新率_倍频
  type: text_short
  unit: "Hz"
  aliases: []
```

**适用**：纯文本 / 无法结构化的字段（倍频值、声道、音频格式、认证、画质技术）。
**关键约定**：给**只做下游展示、不参与画面标签匹配**的字段用 `text_short` 且 `aliases: []`
——一旦给了 aliases，它就会参与标签匹配，可能抢走本该属于别的字段的文本。

---

## 四、通用机制

### 4.1 解析入口 `parse_value` (:201)

所有字段值都经 `parse_value(v, fd, cfg, source)`：
1. 空值直接 None
2. 未知 type → **抛 ValueError**（拼错 type 会立刻发现，不会静默）
3. 调 handler
4. 兜底判定（见 4.2）
5. 打上 `raw`（原文）与 `source`（来源标记），便于溯源
6. `_clean` 去掉值为 None 的键

### 4.2 短文本兜底的边界：`FALLBACK_TYPES` (:198)

```python
FALLBACK_TYPES = {"text_short"}
```

只有 `text_short` 会在解析不出时原样收录原文。**数值类字段解析不出就是 None**。
原因：原文兜底会把「不认识的文本」混进数值字段，污染统计与图表，
而且这种污染是静默的——看数字"有值"，实际是错的。

> 改造踩过的坑：早期实现对**所有**类型兜底，结果多出 3 个机型的「屏幕」字段
> （把长文本当成了屏幕类型值）。靠回归测试才抓到。

### 4.3 note 模板与占位符

`notes` 支持 `{}` 占位符，由各 handler 格式化：

| type | 可用占位符 |
|---|---|
| `zones` | `{zone_type}`、`{lo}`、`{hi}` |
| `range_num` | `{lo}`、`{hi}` |
| `percent_std` | `{val}`、`{std}` |

`money` 的 `note` 是纯文本，不格式化。

### 4.4 返回 None 的语义（铁律 M8）

解析不出 → `None` → 下游显示「未提取」。**不填 0、不推测填充。**
填 0 会让下游图表把「没数据」当成「真的是 0」，是这类任务最常见也最致命的错误。

---

## 五、⚠ 内置品类假设（换品类前必读）

这 6 处的共同模式：**通用 handler 里藏着电视领域的字面量**。
换品类时它们不会报错，只会静默失效——某个字段在所有机型上都是「未提取」，
或者给出错误的值。

### 5.1 `count_by_version` 写死 "HDMI" 前缀 (:158)
```python
pat = r"HDMI\s*" + re.escape(ver) + r"\D{0,8}?(\d+)\s*个?"
```
- **失效表现**：USB-C / DP / 雷电接口数量全部解析不出
- **绕过**：要么给 `schema.py` 加一个 `interface_prefix` 配置参数（推荐，改动小），
  要么相关字段改用 `text_short` + 人工核对

### 5.2 `cpu_text` 正则写死中文核数词 (:140-141)
```python
r"((?:双核|单核|四核|五核|八核|四核A|双核A)?\s*[A-Z]?\d{2,3}…"
```
- **失效表现**：`MT9652`、`Pentonic 800`、`Amlogic T982` 这类芯片名解析不出
- **绕过**：改用 `text_short` 收录原文，或扩展正则

### 5.3 `_percent_std` 写死 "% sRGB" 字面量 (:124)
```python
note = (notes.get("srgb") if name == "% sRGB" else …)
```
- **失效表现**：想给 sRGB 走专门文案，但 preset 里 `name` 写成 `sRGB` 或 `%sRGB` 都不生效（必须一字不差是 `"% sRGB"`）
- **绕过**：preset 的 `standards[].name` 严格写成 `"% sRGB"`；或改代码用可配置的判断

### 5.4 `_zones` 区间分支要求「级」字 (:57)
```python
m = re.search(r"(\d{2,5})\s*[-—~至]\s*(\d{2,5})\s*级", v)
```
- **失效表现**：`100-200` 或 `100-200区` 抓不到，退化到「无分区」或 None
- **绕过**：在 preset 的 `ocr_fixes.regex` 里把单位统一补成「级」；或改用 `range_num`

### 5.5 `_size_inch` 只匹配 2 位数 (:149)
```python
m = re.search(r"(\d{2})\s*(?:英寸|寸)", v)
```
- **失效表现**：`5.5英寸`（手机）抓不到
- **绕过**：改用 `text_short`，或扩展正则支持小数

### 5.6 `range_num` 要求至少 3 位数 (:81, :86)
```python
r"(\d{3,5})[-—~至](\d{3,5})"   # 区间
r"(\d{3,5})"                    # 单值
```
- **失效表现**：`80nit`、`2.5W` 这类小数值解析不出
- **绕过**：改用 `int_unit`（若带「个」）或 `text_short`

---

## 六、新增一种 type 的步骤

1. 在 `scripts/lib/schema.py` 写 handler：`def _xxx(v, fd) -> dict | None`
   - 解析不出必须 `return None`（铁律 M8）
   - 需要多档文案时，用 `fd.get("notes", {})` + `{}` 占位符
2. 注册到 `HANDLERS` (:179)
3. 若需要短文本兜底，把 type 名加进 `FALLBACK_TYPES` (:198)——**默认不加**
4. 在 preset 里用一个真实字段试跑，确认输出符合预期
5. 回归：`python tests/test_regression.py` 应仍通过（新增 handler 不影响既有类型）

---

## 七、调试：字段解析不出来时怎么查

按这个顺序排查，能覆盖绝大多数情况：

1. **标签有没有命中**：跑 `05_discover.py` 看「候选字段标签」表里有没有这个词。
   没有 → 补 `aliases`；有但拼错 → 补 `ocr_fixes`。
2. **`aliases` 是不是空的**：只做展示的字段用 `aliases: []`，
   要参与匹配的字段必须有 aliases。写反了会导致字段永远是空。
3. **别名顺序**：两个字段的 aliases 有包含关系时，靠前的字段优先判定
   （`lib/config.py` 的 `label_index` 按 fields 定义顺序构建）。
4. **值文本有没有被 OCR 修正表改坏**：看结果的 `raw` 字段，它保存的是修正后的原文。
5. **type 是不是选错**：拿 `raw` 的值手工套一遍第五章的正则。
6. **是不是第五章的 6 处内置假设之一**。
7. **是不是被短文本兜底拦截**：非 `text_short` 类型解析不出不会兜底，看日志里
   「未提取」的字段数是否异常。
