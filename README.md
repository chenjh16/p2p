# P2P — PDF to PPTX Converter

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Ruff](https://img.shields.io/badge/linter-Ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![Pylint](https://img.shields.io/badge/Pylint-9.90%2F10-brightgreen?logo=python&logoColor=white)](https://pylint.readthedocs.io/)
[![Mypy](https://img.shields.io/badge/type--checked-Mypy-blue?logo=python&logoColor=white)](https://mypy-lang.org/)

**[English](#p2p--pdf-to-pptx-converter)** | **[中文](#p2p--pdf-转-pptx-转换器)**

Convert PDF slide decks into editable Microsoft PowerPoint (PPTX) files using multimodal LLMs (GPT-5.4 / Claude Opus-4.6).

The tool analyzes each slide image with the LLM and directly generates PresentationML (OOXML) XML, producing PowerPoint files with native vector elements — text boxes, shapes, tables, connectors, equations — rather than embedded raster images.

## Features

- **High Visual Fidelity** — reconstructed slides closely match the original PDF layout, colors, fonts, and styling
- **Native Editability** — maximizes use of PowerPoint vector elements (text boxes, shapes, tables, connectors, groups) for full editability
- **Atomic Reconstruction** — decomposes every visual region into its smallest independently rebuildable units
- **Smart Raster Handling** — only uses image placeholders for genuinely photographic content; diagrams and tables are always vectorized
- **Single API Call** — processes all pages in one LLM request via parallel tool calls
- **Streaming Output** — real-time display of LLM output (content, reasoning, tool calls) during conversion
- **Aspect Ratio Detection** — automatically detects page aspect ratio (16:9, 4:3, 16:10) and snaps to standard PowerPoint dimensions
- **Batch Processing** — automatically splits large PDFs into batches with overlap for animation continuity
- **Dry-Run Mode** — preview token usage and cost estimates without calling the API
- **Full Artifact Logging** — saves all intermediate results (images, messages, API responses, reasoning, slide XMLs) to timestamped directories
- **Bilingual Prompts** — system prompt available in English and Chinese (`--prompt-lang`)
- **Optional Animations** — Morph transitions and entrance animations when adjacent slides have similar layouts (`--enable-animations`)

## Architecture

```
PDF ──→ [PyMuPDF] ──→ Page Images ──→ [LLM API] ──→ Slide XMLs ──→ [python-pptx] ──→ PPTX
                        (288 DPI)       (streaming)       (validated)      (assembled)
                                                              │
                                                              ▼
                                                     [Post-processor]
                                                     (raster fill at 300 DPI)
```

**Pipeline stages:**

1. **PDF Preprocessing** — render each page to a high-resolution PNG image (default 288 DPI)
2. **Message Building** — construct the OpenAI Chat Completions messages with system prompt, page images, and task instructions
3. **LLM API Call** — stream the LLM's response, extracting `write_slide_xml` tool calls with PresentationML XML for each page
4. **XML Validation** — parse, validate, and repair the generated XML (strip code fences, fix common errors, register relationships)
5. **Aspect Ratio Detection** — detect page aspect ratio and snap to standard PowerPoint dimensions (16:9, 4:3, 16:10)
6. **PPTX Assembly** — create a skeleton presentation and inject the validated slide XML into each slide
7. **Post-processing** — scan for `__LLMCLIP__` placeholders, crop corresponding regions from the original PDF at 300 DPI, and replace placeholders with actual images

## Installation

**Requirements:** Python 3.11+

```bash
# Clone the repository
git clone https://github.com/your-org/p2p.git
cd p2p

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install with dependencies
pip install -e .

# Install development tools (optional)
pip install -e ".[dev]"
```

## Quick Start

### 1. Set up API credentials

```bash
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL_NAME="gpt-5.4"  # optional, defaults to gpt-5.4
```

```bash
# Or for Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-..."
export ANTHROPIC_MODEL_NAME="claude-opus-4-6"  # optional
```

### 2. Convert a PDF

```bash
# Basic conversion
p2p slides.pdf

# Specify output path
p2p slides.pdf -o output.pptx

# With animations enabled
p2p slides.pdf --enable-animations

# Chinese system prompt
p2p slides.pdf --prompt-lang zh

# Using Anthropic Claude
p2p slides.pdf --api-provider anthropic
```

### 3. Dry-run (estimate cost without calling API)

```bash
p2p slides.pdf --dry-run
```

Output:

```
DRY-RUN SUMMARY
============================================================
  PDF:              slides.pdf
  Pages:            14
  Slide size:       720pt × 405pt
  DPI:              288
  Model:            gpt-5.4
  Batches:          1
------------------------------------------------------------
  Text tokens:      3,200
  Image tokens:     72,800 (14 images)
  Total input:      76,000 tokens
  Est. output:      56,000 tokens
  Est. cost:        $1.0300
------------------------------------------------------------
  Est. response:    ~1120s (~18.7 min) at 50 tok/s
============================================================
```

## CLI Reference

```
usage: p2p [-h] [-o OUTPUT] [--api-provider {openai,anthropic}]
           [--api-base-url URL] [--api-key KEY] [--model-name MODEL]
           [--dpi DPI] [--enable-animations]
           [--reasoning-effort {low,medium,high,xhigh}]
           [--prompt-lang {en,zh}] [--batch-size N]
           [--skip-postprocess] [--dry-run]
           [--log-level {DEBUG,INFO,WARNING,ERROR}]
           pdf
```

| Argument | Env Variable | Default | Description |
|---|---|---|---|
| `pdf` | — | *(required)* | Input PDF file path |
| `-o`, `--output` | — | `<basename>.pptx` | Output PPTX file path |
| `--api-provider` | — | `openai` | API provider: `openai` or `anthropic` |
| `--api-base-url` | `OPENAI_BASE_URL` / `ANTHROPIC_API_URL` | `""` | API base URL |
| `--api-key` | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | `""` | API key |
| `--model-name` | `OPENAI_MODEL_NAME` / `ANTHROPIC_MODEL_NAME` | `gpt-5.4` | Model name |
| `--dpi` | — | `288` | Rendering DPI for LLM input images |
| `--enable-animations` | — | `off` | Enable Morph transitions and animations |
| `--reasoning-effort` | — | `medium` | Model reasoning effort (low/medium/high/xhigh) |
| `--prompt-lang` | — | `en` | System prompt language (en/zh) |
| `--batch-size` | — | `25` | Pages per API call for large documents |
| `--skip-postprocess` | — | `off` | Skip raster image post-processing |
| `--dry-run` | — | `off` | Estimate tokens and cost without calling API |
| `--log-level` | — | `INFO` | Logging verbosity |

## Artifact Directories

Every run (including dry-runs) saves all intermediate artifacts to a timestamped directory:

```
run-slides-20260309-143052/
├── run_params.json              # CLI parameters used for this run
├── pages/
│   ├── page_000.png             # Rendered page images
│   ├── page_001.png
│   └── ...
├── messages.json                # API messages (base64 replaced with file paths)
├── messages_full.json           # API messages (complete with base64)
├── system_prompt.md             # System prompt sent to the model
├── tools.json                   # Tool definitions
├── token_estimate.json          # Token count and cost estimate
├── api_response.json            # API response metadata and usage stats
├── stream_chunks.jsonl          # Raw streaming chunks (JSONL)
├── stream_batch0.log            # Real-time streaming output log
├── tool_calls.json              # Parsed tool call results
├── reasoning.txt                # Model's thinking/reasoning process
├── content.txt                  # Model's non-tool-call text output
├── slides/
│   ├── slide_000.xml            # Generated PresentationML XML per slide
│   ├── slide_001.xml
│   └── ...
└── metadata.json                # Run metadata (timing, counts, etc.)
```

Dry-run directories use the `dry-run-` prefix and contain only pre-API artifacts.

## How It Works

### System Prompt Design

The system prompt instructs the LLM to act as a "presentation reconstruction engine" that converts slide images into OOXML PresentationML XML. Key principles:

1. **Vector First** — maximize native PowerPoint elements (text boxes, shapes, tables, connectors, groups)
2. **Raster Placeholder (Last Resort)** — only for photographs and complex artistic illustrations
3. **Atomic Reconstruction** — decompose into smallest independently rebuildable units
4. **Precise Positioning** — all coordinates in EMU (1 pt = 12700 EMU)
5. **Font Size Calibration** — mandatory 20% reduction to compensate for systematic overestimation
6. **Table Vectorization** — tables must always use native `<a:tbl>`, never raster placeholders
7. **Diagram Vectorization** — flowcharts and diagrams of basic shapes must be decomposed into vector elements

### Raster Post-Processing

For regions the LLM identifies as photographic content, it outputs placeholder boxes with coordinates:

```
__LLMCLIP__:[x1, y1][x2, y2]
```

The post-processor then:
1. Scans the assembled PPTX for these placeholders
2. Crops the corresponding region from the original PDF at 300 DPI
3. Replaces the placeholder shape with the actual image

### Batch Processing

For large PDFs exceeding the batch size (default 25 pages):
- Pages are split into overlapping batches (2-page overlap)
- Each batch is processed in a separate API call
- When animations are enabled, the later batch's version of overlapping pages is preferred for better transition context

## Project Structure

```
p2p/
├── src/
│   ├── __init__.py              # Package init
│   ├── __main__.py              # python -m src entry point
│   ├── main.py                  # CLI entry point and pipeline orchestration
│   ├── system_prompt.py         # System prompts (EN/ZH) and tool definitions
│   ├── pdf_preprocessor.py      # PDF → PNG rendering via PyMuPDF
│   ├── message_builder.py       # OpenAI messages array construction
│   ├── token_estimator.py       # Token counting and cost estimation
│   ├── api_client.py            # Streaming LLM API client
│   ├── api_client_anthropic.py  # Anthropic streaming LLM API client
│   ├── xml_validator.py         # XML validation and repair
│   ├── pptx_assembler.py        # PPTX file assembly from slide XMLs
│   ├── postprocessor.py         # Raster placeholder replacement
│   ├── artifacts.py             # Artifact directory management
│   ├── dry_run.py               # Dry-run mode implementation
│   └── logging_config.py        # Rich-based logging configuration
├── tests/
│   ├── test_e2e.py              # End-to-end tests with mock LLM server
│   └── test_unit.py             # Unit tests for all modules
├── docs/
│   └── design.md                # Detailed design document (EN + ZH)
├── pyproject.toml               # Project metadata and tool configuration
├── LICENSE                      # MIT License
├── .gitignore
└── README.md
```

## Development

### Setup

```bash
pip install -e ".[dev]"
```

### Linting

```bash
# Run all linters
ruff check src/ tests/
mypy src/
pylint src/
```

### Testing

```bash
# Run end-to-end tests (uses mock LLM server, no API key needed)
python -m pytest tests/ -v
```

The test suite includes:

**End-to-end tests** (`test_e2e.py`):
- **`test_dry_run`** — verifies dry-run artifact generation
- **`test_e2e_conversion`** — full pipeline test with mock streaming server producing a valid 2-page PPTX
- **`test_xml_validator`** — XML validation and repair logic

**Unit tests** (`test_unit.py`) — 46 tests covering:
- `TestPdfPreprocessor` — page rendering, PNG output, metadata, DPI scaling
- `TestMessageBuilder` — message structure, animation toggle, image embedding, bilingual prompts, task instructions
- `TestTokenEstimator` — text/image token counting, cost estimation, output scaling
- `TestXmlValidator` — valid XML passthrough, fence stripping, declaration injection, ampersand fixing, namespace repair, fallback slides
- `TestSystemPrompt` — EN/ZH prompts, animation sections, tool definition, font calibration, table rules
- `TestArtifactStore` — directory creation, dry-run prefix, image/params/reasoning/content/metadata saving, batch indexing
- `TestPPTXAssembler` — single/multi slide assembly, dimensions, hyperlink handling
- `TestLoggingConfig` — setup and logger creation

### Code Quality

| Tool | Config | Status |
|---|---|---|
| ruff | `pyproject.toml` (line-length=120) | All checks pass |
| mypy | `pyproject.toml` (strict) | No issues |
| pylint | `pyproject.toml` (line-length=120) | 9.90/10 |

## Dependencies

| Package | Purpose |
|---|---|
| `python-pptx` | PPTX file creation and manipulation |
| `PyMuPDF` | PDF rendering to images |
| `Pillow` | Image processing |
| `openai` | OpenAI API client (streaming, tool calling) |
| `anthropic` | Anthropic API client (streaming, tool use) |
| `lxml` | XML parsing, validation, and manipulation |
| `tiktoken` | Token counting for cost estimation |
| `rich` | Colored, structured console logging |

## License

This project is licensed under the [MIT License](LICENSE).

---

# P2P — PDF 转 PPTX 转换器

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Ruff](https://img.shields.io/badge/linter-Ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![Pylint](https://img.shields.io/badge/Pylint-9.90%2F10-brightgreen?logo=python&logoColor=white)](https://pylint.readthedocs.io/)
[![Mypy](https://img.shields.io/badge/type--checked-Mypy-blue?logo=python&logoColor=white)](https://mypy-lang.org/)

**[English](#p2p--pdf-to-pptx-converter)** | **[中文](#p2p--pdf-转-pptx-转换器)**

使用多模态大语言模型（GPT-5.4 / Claude Opus-4.6）将 PDF 幻灯片转换为可编辑的 Microsoft PowerPoint（PPTX）文件。

该工具使用 LLM 分析每页幻灯片图像，直接生成 PresentationML（OOXML）XML，产出包含原生矢量元素（文本框、形状、表格、连接线、公式等）的 PowerPoint 文件，而非嵌入光栅图像。

## 功能特性

- **高视觉保真度** — 重建的幻灯片在布局、颜色、字体和样式上与原始 PDF 高度一致
- **原生可编辑性** — 最大化使用 PowerPoint 矢量元素（文本框、形状、表格、连接线、组合）以实现完全可编辑
- **原子化重建** — 将每个视觉区域分解为最小的可独立重建单元
- **智能光栅处理** — 仅对真正的照片内容使用图像占位符；图表和表格始终矢量化
- **单次 API 调用** — 通过并行工具调用在一次 LLM 请求中处理所有页面
- **流式输出** — 转换过程中实时显示 LLM 输出（内容、推理、工具调用）
- **宽高比检测** — 自动检测页面宽高比（16:9、4:3、16:10）并对齐到标准 PowerPoint 尺寸
- **批量处理** — 自动将大型 PDF 分批处理，批次间有重叠以保持动画连续性
- **试运行模式** — 无需调用 API 即可预览 token 用量和成本估算
- **完整产物日志** — 将所有中间结果（图像、消息、API 响应、推理、幻灯片 XML）保存到带时间戳的目录
- **双语提示词** — 系统提示词支持英文和中文（`--prompt-lang`）
- **可选动画** — 当相邻幻灯片布局相似时添加 Morph 转场和入场动画（`--enable-animations`）

## 架构

```
PDF ──→ [PyMuPDF] ──→ 页面图像 ──→ [LLM API] ──→ 幻灯片 XML ──→ [python-pptx] ──→ PPTX
                       (288 DPI)      (流式输出)        (已验证)         (已组装)
                                                            │
                                                            ▼
                                                     [后处理器]
                                                     (300 DPI 光栅填充)
```

**处理流程：**

1. **PDF 预处理** — 将每页渲染为高分辨率 PNG 图像（默认 288 DPI）
2. **消息构建** — 构建包含系统提示词、页面图像和任务指令的 OpenAI Chat Completions 消息
3. **LLM API 调用** — 流式接收 LLM 的响应，提取每页的 `write_slide_xml` 工具调用及 PresentationML XML
4. **XML 验证** — 解析、验证并修复生成的 XML（去除代码围栏、修复常见错误、注册关系）
5. **宽高比检测** — 检测页面宽高比并对齐到标准 PowerPoint 尺寸（16:9、4:3、16:10）
6. **PPTX 组装** — 创建骨架演示文稿并将验证后的幻灯片 XML 注入每页
7. **后处理** — 扫描 `__LLMCLIP__` 占位符，从原始 PDF 以 300 DPI 裁剪对应区域，替换占位符为实际图像

## 安装

**环境要求：** Python 3.11+

```bash
# 克隆仓库
git clone https://github.com/your-org/p2p.git
cd p2p

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -e .

# 安装开发工具（可选）
pip install -e ".[dev]"
```

## 快速开始

### 1. 设置 API 凭证

```bash
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL_NAME="gpt-5.4"  # 可选，默认为 gpt-5.4
```

```bash
# 或使用 Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-..."
export ANTHROPIC_MODEL_NAME="claude-opus-4-6"  # 可选
```

### 2. 转换 PDF

```bash
# 基本转换
p2p slides.pdf

# 指定输出路径
p2p slides.pdf -o output.pptx

# 启用动画
p2p slides.pdf --enable-animations

# 使用中文系统提示词
p2p slides.pdf --prompt-lang zh

# 使用 Anthropic Claude
p2p slides.pdf --api-provider anthropic
```

### 3. 试运行（估算成本，不调用 API）

```bash
p2p slides.pdf --dry-run
```

输出：

```
DRY-RUN SUMMARY
============================================================
  PDF:              slides.pdf
  Pages:            14
  Slide size:       720pt × 405pt
  DPI:              288
  Model:            gpt-5.4
  Batches:          1
------------------------------------------------------------
  Text tokens:      3,200
  Image tokens:     72,800 (14 images)
  Total input:      76,000 tokens
  Est. output:      56,000 tokens
  Est. cost:        $1.0300
------------------------------------------------------------
  Est. response:    ~1120s (~18.7 min) at 50 tok/s
============================================================
```

## 命令行参数

```
用法: p2p [-h] [-o OUTPUT] [--api-provider {openai,anthropic}]
          [--api-base-url URL] [--api-key KEY] [--model-name MODEL]
          [--dpi DPI] [--enable-animations]
          [--reasoning-effort {low,medium,high,xhigh}]
          [--prompt-lang {en,zh}] [--batch-size N]
          [--skip-postprocess] [--dry-run]
          [--log-level {DEBUG,INFO,WARNING,ERROR}]
          pdf
```

| 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `pdf` | — | *（必填）* | 输入 PDF 文件路径 |
| `-o`, `--output` | — | `<文件名>.pptx` | 输出 PPTX 文件路径 |
| `--api-provider` | — | `openai` | API 提供商：`openai` 或 `anthropic` |
| `--api-base-url` | `OPENAI_BASE_URL` / `ANTHROPIC_API_URL` | `""` | API 基础 URL |
| `--api-key` | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | `""` | API 密钥 |
| `--model-name` | `OPENAI_MODEL_NAME` / `ANTHROPIC_MODEL_NAME` | `gpt-5.4` | 模型名称 |
| `--dpi` | — | `288` | LLM 输入图像的渲染 DPI |
| `--enable-animations` | — | `关闭` | 启用 Morph 转场和动画 |
| `--reasoning-effort` | — | `medium` | 模型推理强度（low/medium/high/xhigh） |
| `--prompt-lang` | — | `en` | 系统提示词语言（en/zh） |
| `--batch-size` | — | `25` | 大文档每次 API 调用的页数 |
| `--skip-postprocess` | — | `关闭` | 跳过光栅图像后处理 |
| `--dry-run` | — | `关闭` | 估算 token 和成本，不调用 API |
| `--log-level` | — | `INFO` | 日志详细程度 |

## 产物目录

每次运行（包括试运行）都会将所有中间产物保存到带时间戳的目录：

```
run-slides-20260309-143052/
├── run_params.json              # 本次运行的 CLI 参数
├── pages/
│   ├── page_000.png             # 渲染的页面图像
│   ├── page_001.png
│   └── ...
├── messages.json                # API 消息（base64 替换为文件路径）
├── messages_full.json           # API 消息（包含完整 base64）
├── system_prompt.md             # 发送给模型的系统提示词
├── tools.json                   # 工具定义
├── token_estimate.json          # Token 计数和成本估算
├── api_response.json            # API 响应元数据和使用统计
├── stream_chunks.jsonl          # 原始流式数据块（JSONL）
├── stream_batch0.log            # 实时流式输出日志
├── tool_calls.json              # 解析后的工具调用结果
├── reasoning.txt                # 模型的思考/推理过程
├── content.txt                  # 模型的非工具调用文本输出
├── slides/
│   ├── slide_000.xml            # 每页生成的 PresentationML XML
│   ├── slide_001.xml
│   └── ...
└── metadata.json                # 运行元数据（耗时、计数等）
```

试运行目录使用 `dry-run-` 前缀，仅包含 API 调用前的产物。

## 工作原理

### 系统提示词设计

系统提示词指导 LLM 作为"演示文稿重建引擎"，将幻灯片图像转换为 OOXML PresentationML XML。核心原则：

1. **矢量优先** — 最大化使用原生 PowerPoint 元素（文本框、形状、表格、连接线、组合）
2. **光栅占位（最后手段）** — 仅用于照片和复杂艺术插图
3. **原子化重建** — 分解为最小的可独立重建单元
4. **精确定位** — 所有坐标使用 EMU（1 pt = 12700 EMU）
5. **字体大小校准** — 强制缩小 20% 以补偿系统性高估
6. **表格矢量化** — 表格必须始终使用原生 `<a:tbl>`，绝不使用光栅占位符
7. **图表矢量化** — 由基本形状组成的流程图和图表必须分解为矢量元素

### 光栅后处理

对于 LLM 识别为照片内容的区域，它会输出带坐标的占位框：

```
__LLMCLIP__:[x1, y1][x2, y2]
```

后处理器随后：
1. 扫描组装后的 PPTX 中的这些占位符
2. 从原始 PDF 以 300 DPI 裁剪对应区域
3. 用实际图像替换占位形状

### 批量处理

对于超过批次大小（默认 25 页）的大型 PDF：
- 页面被分为有重叠的批次（2 页重叠）
- 每个批次通过单独的 API 调用处理
- 启用动画时，重叠页面优先使用后一批次的版本以获得更好的转场上下文

## 项目结构

```
p2p/
├── src/
│   ├── __init__.py              # 包初始化
│   ├── __main__.py              # python -m src 入口
│   ├── main.py                  # CLI 入口和流程编排
│   ├── system_prompt.py         # 系统提示词（中/英）和工具定义
│   ├── pdf_preprocessor.py      # PDF → PNG 渲染（PyMuPDF）
│   ├── message_builder.py       # OpenAI 消息数组构建
│   ├── token_estimator.py       # Token 计数和成本估算
│   ├── api_client.py            # 流式 LLM API 客户端
│   ├── api_client_anthropic.py  # Anthropic 流式 LLM API 客户端
│   ├── xml_validator.py         # XML 验证和修复
│   ├── pptx_assembler.py        # 从幻灯片 XML 组装 PPTX 文件
│   ├── postprocessor.py         # 光栅占位符替换
│   ├── artifacts.py             # 产物目录管理
│   ├── dry_run.py               # 试运行模式实现
│   └── logging_config.py        # 基于 Rich 的日志配置
├── tests/
│   ├── test_e2e.py              # 端到端测试（含模拟 LLM 服务器）
│   └── test_unit.py             # 所有模块的单元测试
├── docs/
│   └── design.md                # 详细设计文档（中英双语）
├── pyproject.toml               # 项目元数据和工具配置
├── LICENSE                      # MIT 许可证
├── .gitignore
└── README.md
```

## 开发

### 环境搭建

```bash
pip install -e ".[dev]"
```

### 代码检查

```bash
# 运行所有检查工具
ruff check src/ tests/
mypy src/
pylint src/
```

### 测试

```bash
# 运行端到端测试（使用模拟 LLM 服务器，无需 API 密钥）
python -m pytest tests/ -v
```

测试套件包括：

**端到端测试**（`test_e2e.py`）：
- **`test_dry_run`** — 验证试运行产物生成
- **`test_e2e_conversion`** — 使用模拟流式服务器的完整流程测试，生成有效的 2 页 PPTX
- **`test_xml_validator`** — XML 验证和修复逻辑

**单元测试**（`test_unit.py`）— 46 项测试覆盖：
- `TestPdfPreprocessor` — 页面渲染、PNG 输出、元数据、DPI 缩放
- `TestMessageBuilder` — 消息结构、动画开关、图像嵌入、双语提示词、任务指令
- `TestTokenEstimator` — 文本/图像 token 计数、成本估算、输出缩放
- `TestXmlValidator` — 有效 XML 透传、围栏去除、声明注入、& 符号修复、命名空间修复、回退幻灯片
- `TestSystemPrompt` — 中英文提示词、动画部分、工具定义、字体校准、表格规则
- `TestArtifactStore` — 目录创建、试运行前缀、图像/参数/推理/内容/元数据保存、批次索引
- `TestPPTXAssembler` — 单页/多页组装、尺寸、超链接处理
- `TestLoggingConfig` — 日志设置和 logger 创建

### 代码质量

| 工具 | 配置 | 状态 |
|---|---|---|
| ruff | `pyproject.toml`（line-length=120） | 全部通过 |
| mypy | `pyproject.toml`（strict） | 无问题 |
| pylint | `pyproject.toml`（line-length=120） | 9.90/10 |

## 依赖

| 包 | 用途 |
|---|---|
| `python-pptx` | PPTX 文件创建和操作 |
| `PyMuPDF` | PDF 渲染为图像 |
| `Pillow` | 图像处理 |
| `openai` | OpenAI API 客户端（流式、工具调用） |
| `anthropic` | Anthropic API 客户端（流式、工具调用） |
| `lxml` | XML 解析、验证和操作 |
| `tiktoken` | Token 计数（成本估算） |
| `rich` | 彩色结构化控制台日志 |

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
