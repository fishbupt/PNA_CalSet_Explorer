# AGENTS.md

## 项目定位

PNA CalSet Explorer 是一个用于读取、查看和导出 Keysight PNA/PNA-X 校准集数据的工程工具。

核心用途是辅助验证网分的 Mixer 校准算法，尤其是：

- SMC
- VMC
- Mixer Power Calibration
- Error Term 求解
- Calibration Standard 原始数据分析
- Golden Data 构建

本项目不是通用 VISA 示例程序。所有修改都必须优先保证校准数据的真实性、完整性、可追溯性和后续算法验证价值。

## 技术栈

统一使用：

- Python 3.10+
- PyQt6
- PyVISA
- NumPy
- pyqtgraph
- JSON
- NPZ
- pytest
- uv

## 依赖管理

本项目只使用 **uv** 管理依赖和虚拟环境。

标准命令：

```powershell
uv sync --group dev
uv run python main.py
uv run pytest
```

禁止新增：

- requirements.txt
- requirements-dev.txt
- Poetry
- Pipenv
- Conda environment.yml

除非用户明确要求。

依赖发生变化时：

1. 修改 `pyproject.toml`
2. 执行 `uv sync --group dev`
3. 提交更新后的 `uv.lock`

## PNA 默认连接地址

默认本机 PNA VISA Resource：

```text
TCPIP0::127.0.0.1::hislip0::INSTR
```

这个地址已在目标 PNA 环境中实际验证可用。

不要擅自改回：

```text
TCPIP::127.0.0.1::INSTR
```

该简写形式在目标环境中会连接失败。

## Keysight SCPI 开发规则

### 1. 禁止硬编码 CalSet 内部内容

CalSet、Standard、Error Term、ITEM、Property 等必须优先通过 Catalog 类命令动态读取。

典型命令包括：

```text
CSET:CAT?
CSET:STAN:CAT?
CSET:ETER:CAT?
CSET:ITEM:CAT?
CSET:PROP:CAT?
```

禁止假定固定存在某些名称，例如：

```text
Directivity
SourceMatch
ReflectionTracking
TransmissionTracking
SA_0
ST_0
```

不同校准类型、PNA 型号、固件版本可能返回完全不同的容器和名称。

### 2. 禁止简单 split(",")

PNA 的 Catalog 返回可能是：

```text
"CalSet_2_port,CH1_CALREG,smc_power_cal"
```

但单个名称自身也可能包含逗号：

```text
Directivity(1,1)
SourceMatch(1,1)
SA_0(1,1)
TransmissionTracking(2,1)
```

因此必须使用：

```python
parse_pna_catalog()
```

如果遇到新的 Keysight 返回格式，应：

1. 保留真实返回样例
2. 为该格式补充单元测试
3. 再修改解析器

### 3. 每个 Standard / Error Term 必须保留独立频率轴

这是本项目最重要的约束之一。

SMC/VMC 可能同时存在：

- RF frequency
- IF frequency
- LO frequency
- RF ascending / IF descending
- 不同容器点数不同

因此禁止默认所有 Standard / Error Term 使用 Channel 的同一条 frequency array。

每一个数据项都必须独立保存：

```text
name
frequency_hz[]
complex_data[]
```

### 4. Optional SCPI 必须采用 Best-effort

不同 PNA 型号和固件可能不支持相同的 CalSet 属性。

Optional SCPI 失败时：

- 不允许终止整个 Dump
- 必须生成 QueryRecord
- 必须保留错误信息
- 必须写入 raw_scpi.json
- 不允许伪造一个“看起来正常”的默认值

### 5. 不允许臆造 Keysight SCPI

如果功能依赖一个不确定的 Keysight 命令：

1. 优先查询 Keysight 官方文档
2. 或使用真实 PNA 返回验证
3. 将命令放在可审计的 reader 层
4. 保留 raw response
5. 对解析行为补充测试

不能因为“看起来像 SCPI”就自行创造命令。

## 数据模型规则

`ComplexSeries` 用于保存复数数据序列。

必须保留：

- 原始 PNA 名称
- `frequency_hz`
- complex NumPy array
- read/decode error

建议数据类型：

```python
np.float64
np.complex128
```

Magnitude、dB、Phase、Real、Imag 都只是显示或分析视图。

禁止用 dB/Phase 数据替换原始 Complex 数据。

## Dump 格式规则

Dump 格式将作为后续校准算法 Golden Data 的长期接口。

当前结构：

```text
<CalSetName>/
├── calset_info.json
├── raw_scpi.json
├── standards/
│   ├── index.json
│   └── standards.npz
└── error_terms/
    ├── index.json
    └── error_terms.npz
```

要求：

- JSON 中保留 Keysight 原始名称
- NPZ key 使用安全内部 ID
- 所有频率字段必须明确单位，例如 `frequency_hz`
- GUI 可以只显示部分点，但 Dump 必须保存所有点
- 不得因为已经解析出结构化字段就删除原始 SCPI 审计数据
- 如果 Dump Schema 不兼容修改，必须增加 `schema_version`

## 工程架构

职责划分：

### reader.py

负责：

- PyVISA
- PNA 连接
- SCPI Query
- CalSet 数据读取
- Best-effort 查询
- QueryRecord

### scpi.py

负责：

- SCPI 字符串转义
- Catalog 解析
- Real/Imag 到 Complex 转换
- 通用 SCPI 数据处理

### models.py

负责：

- 数据模型
- ComplexSeries
- CalSetSnapshot
- QueryRecord

### dump_service.py

负责：

- JSON
- NPZ
- Dump Schema
- Manifest

### workers.py

负责：

- Qt 后台任务
- 避免阻塞 UI Thread

### main_window.py

只负责：

- GUI
- 用户交互
- 数据展示
- Plot

不要把大量 SCPI 或 VISA 逻辑直接写进 GUI。

## GUI 开发规则

GUI 应保持专业仪器软件风格：

- 简洁
- 清晰
- 高信息密度
- 不花哨
- 不使用大量渐变和动画
- 深色主题优先
- 表格和曲线应是视觉核心
- 连接状态、错误状态必须明显
- 长时间仪器操作不得阻塞 GUI

现代化界面修改不得破坏已有 SCPI 和 Dump 逻辑。

## 测试要求

普通：

```powershell
uv run pytest
```

不得要求连接真实 PNA。

至少保留以下测试：

- 整体带引号的 CalSet Catalog
- 不带引号的 CalSet Catalog
- 名称内部带逗号的 Port Pair
- Real/Imag interleaved 转 Complex

真实 PNA 上发现解析问题时，应尽可能使用真实返回字符串增加 Regression Test。

## 完成修改前的验证

每次修改代码后至少检查：

1. `uv run pytest`
2. Python 语法是否可编译
3. GUI 修改是否能启动
4. SCPI 修改属于：
   - 仅单元测试验证
   - Keysight 文档验证
   - 真实 PNA 验证

不得把“代码能运行”描述为“已在真实 PNA 验证”。

## 当前重点开发方向

后续重点是深入分析 SMC/VMC CalSet：

- 识别 SMC/VMC 特有 Standard
- 识别 Power Calibration 中间数据
- 识别 Conversion Tracking 数据
- 分析 Error Term 的物理意义
- 建立 PNA Golden Data
- 使用同一份 Raw Calibration Data 对比 Keysight 和自研 Solver
- 使用同一份 Raw DUT Data 对比 Correction Algorithm
