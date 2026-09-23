# PNA CalSet Explorer

PNA CalSet Explorer 是一个基于 **Python + PyQt6** 的 Keysight PNA/PNA-X 校准集（CalSet）查看与导出工具，主要用于 **SMC/VMC 校准算法验证**、中间数据分析以及 Golden Data 构建。

## 项目目标

这个工具不是一个通用 VISA 示例程序，而是面向网分校准算法开发的工程辅助工具。它需要尽可能完整、可追溯地读取 PNA 中的 CalSet 数据，包括：

- CalSet 列表
- Standard 原始采集数据
- Error Term 数据
- 每个 Standard / Error Term 独立的频率轴
- CalSet ITEM
- CalSet Property
- Sweep / Port / Power / Converter 等相关属性
- 原始 SCPI 查询结果和失败信息

这些数据后续可用于：

- 对比 Keysight 与自研 SMC/VMC 校准求解结果
- 验证 Error Term 求解是否正确
- 构建离线 Golden Data
- 分析 Keysight CalSet 内部结构
- 支持校准算法自动化回归测试

## 技术栈

- Python 3.10+
- PyQt6
- PyVISA
- NumPy
- pyqtgraph
- JSON
- NPZ
- pytest
- uv

## 获取代码

```powershell
git clone https://github.com/fishbupt/PNA_CalSet_Explorer.git
cd PNA_CalSet_Explorer
```

## 依赖管理

本项目统一使用 **uv** 管理 Python 环境和依赖，不再使用 `requirements.txt`。

安装依赖：

```powershell
uv sync --group dev
```

运行程序：

```powershell
uv run python main.py
```

运行测试：

```powershell
uv run pytest
```

如果依赖发生变化，应修改 `pyproject.toml`，然后重新执行：

```powershell
uv sync --group dev
```

并将生成或更新后的 `uv.lock` 一并提交。

## 默认 PNA 连接地址

目标 PNA 本机运行时，默认 VISA Resource 为：

```text
TCPIP0::127.0.0.1::hislip0::INSTR
```

该地址已在实际 PNA 环境中验证可以正常连接。

不要改回：

```text
TCPIP::127.0.0.1::INSTR
```

该简写形式在目标环境中会出现 VISA Resource Not Found 类错误。

## 主要功能

### CalSet 浏览

程序可以动态读取 PNA 中的所有 CalSet，例如：

```text
CalSet_2_port
CH1_CALREG
smc_power_cal
```

### Standard 数据查看

对每个 Standard 显示：

- 名称
- 点数
- 起始频率
- 终止频率
- Frequency
- Real
- Imag
- Magnitude
- Phase

### Error Term 数据查看

对每个 Error Term 显示：

- 名称
- 点数
- 起始频率
- 终止频率
- Frequency
- Real
- Imag
- Magnitude
- Magnitude dB
- Phase

### 数据绘图

支持：

- Magnitude (dB)
- Magnitude
- Phase
- Real
- Imag

### CalSet Dump

支持：

- Dump 当前选中的 CalSet
- Dump 全部 CalSet

单个 CalSet 的输出结构：

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

其中：

- JSON 保存元信息、名称、属性和 SCPI 审计数据
- NPZ 保存完整数值数组和 complex128 数据

## 重要设计原则

### 不硬编码 Keysight 内部名称

CalSet、Standard、Error Term、ITEM 等内容必须动态枚举。

不能假设一定存在：

```text
Directivity
SourceMatch
TransmissionTracking
SA_0
```

因为不同校准类型、PNA 型号和固件版本可能不同。

### 不允许直接使用 split(",")

PNA 可能返回：

```text
"CalSet_2_port,CH1_CALREG,smc_power_cal"
```

同时名称本身也可能包含逗号：

```text
Directivity(1,1)
SA_0(1,1)
TransmissionTracking(2,1)
```

因此项目使用专门的 `parse_pna_catalog()` 解析器。

### 每个数据项保留独立频率轴

SMC/VMC 中可能同时存在 RF、IF、LO 频率关系。

不能假设：

```text
所有 Standard
所有 Error Term
全部共用同一条频率轴
```

每个 Standard 和 Error Term 都必须独立读取并保存自己的 x-axis。

### Best-effort Dump

不同 PNA 型号和固件支持的 CalSet 属性可能不同。

对于不支持的 Optional SCPI：

- 记录失败
- 保存在 `raw_scpi.json`
- 不影响整个 CalSet 继续 Dump
- 不伪造默认值

## 项目结构

```text
PNA_CalSet_Explorer/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── main.py
├── pna_cal_explorer/
│   ├── __init__.py
│   ├── models.py
│   ├── scpi.py
│   ├── reader.py
│   ├── dump_service.py
│   ├── workers.py
│   └── main_window.py
└── tests/
    └── test_parsing.py
```

## AI 辅助开发

使用 ChatGPT、Codex 或其他 AI Agent 修改本工程前，请先阅读：

```text
AGENTS.md
```

其中定义了本项目的架构边界、Keysight SCPI 开发规则、测试要求和 SMC/VMC 数据处理约束。
