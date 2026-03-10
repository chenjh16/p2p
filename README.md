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
- **Error Recovery** — interactive retry/skip/quit when API calls fail mid-batch; preserves progress and allows partial assembly
- **Continue Run** — resume incomplete conversions from a previous run directory (`--continue-run`)
- **Replay** — re-run a previous conversion with the same parameters (`--replay`)
- **Immediate Slide Persistence** — each slide XML is written to disk as soon as its tool call completes during streaming, preventing data loss on crashes
- **Configurable TPS** — tune estimated output tokens-per-second for accurate time estimates (`--output-tps`, default 50)
- **Auto Provider Detection** — automatically selects Anthropic API format when model name starts with `claude-`
- **Image Folder Input** — accepts a folder of slide screenshots (PNG, JPG, etc.) as input, sorted by filename, in addition to PDF files
- **Bilingual Prompts** — system prompt available in English and Chinese (`--prompt-lang`)
- **Optional Animations** — Morph transitions and entrance animations when adjacent slides have similar layouts (`--enable-animations`)

## Architecture

```
PDF ──→ [PyMuPDF] ──→ Page Images ──→ [LLM API] ──→ Slide XMLs ──→ [python-pptx] ──→ PPTX
                        (192 DPI)       (streaming)       (validated)      (assembled)
                                                              │
                                                              ▼
                                                     [Post-processor]
                                                     (raster fill at 300 DPI)
```

**Pipeline stages:**

1. **Preprocessing** — render each PDF page to a high-resolution PNG image (default 192 DPI), or load images directly from a folder (sorted by filename)
2. **Message Building** — construct the OpenAI Chat Completions messages with system prompt, page images, and task instructions
3. **LLM API Call** — stream the LLM's response, extracting `write_slide_xml` tool calls with PresentationML XML for each page; each slide XML is persisted to disk immediately upon tool call completion
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

# From a folder of slide images
p2p ./slide_images/
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
  DPI:              192
  Model:            gpt-5.4
  Batch size:       4 (auto)
  Batches:          4
------------------------------------------------------------
  Per-batch estimate:
    Text tokens:    3,200
    Image tokens:   5,200 (4 images)
    Input tokens:   8,400
    Output tokens:  ~16,000
    Response time:  ~800s (~13.3 min)
  Total estimate (4 batches):
    Input tokens:   33,600
    Output tokens:  ~64,000
    Total tokens:   ~97,600
    Response time:  ~3200s (~53.3 min)
  Est. cost:        $0.6200
------------------------------------------------------------
  Output TPS:       50 tok/s (reasoning=medium, ×1.5)
============================================================
```

### 4. Replay a previous run

```bash
# Re-run a previous conversion with the same parameters
p2p dummy --replay runs/run-slides-20260309-143052
```

### 5. Continue an incomplete run

```bash
# Resume from where a previous run left off
p2p dummy --continue-run runs/run-slides-20260310-161844
```

## CLI Reference

```
usage: p2p [-h] [-o OUTPUT] [--api-provider {openai,anthropic}]
           [--api-base-url URL] [--api-key KEY] [--model-name MODEL]
           [--dpi {96,144,192,288}] [--enable-animations]
           [--reasoning-effort {low,medium,high,xhigh}]
           [--prompt-lang {en,zh}] [--max-pages N] [--pages SPEC]
           [--batch-size N] [--output-tps TPS] [--skip-postprocess]
           [--dry-run] [--replay DIR] [--continue-run DIR]
           [--log-level {DEBUG,INFO,WARNING,ERROR}]
           pdf
```

| Argument | Env Variable | Default | Description |
|---|---|---|---|
| `pdf` | — | *(required)* | Input PDF file or folder of slide images |
| `-o`, `--output` | — | `<basename>.pptx` | Output PPTX file path |
| `--api-provider` | `LLM_PROVIDER` | `openai` | API provider: `openai` or `anthropic` (auto-detected from model name) |
| `--api-base-url` | `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` | `""` | API base URL |
| `--api-key` | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | `""` | API key |
| `--model-name` | `OPENAI_MODEL_NAME` / `ANTHROPIC_MODEL_NAME` | `gpt-5.4` | Model name |
| `--dpi` | — | `192` | Rendering DPI for LLM input (96/144/192/288) |
| `--enable-animations` | — | `off` | Enable Morph transitions and animations |
| `--reasoning-effort` | — | `medium` | Model reasoning effort (low/medium/high/xhigh) |
| `--prompt-lang` | — | `en` | System prompt language (en/zh) |
| `--max-pages` | — | `5` | Max pages to convert (0=all); mutually exclusive with `--pages` |
| `--pages` | — | `""` | Specific pages, e.g. `0,2,5-8`; mutually exclusive with `--max-pages` |
| `--batch-size` | — | `0` (auto) | Pages per API call (0=auto based on gateway timeout) |
| `--output-tps` | — | `50` | Assumed output tokens/second for time estimation |
| `--skip-postprocess` | — | `off` | Skip raster image post-processing |
| `--dry-run` | — | `off` | Estimate tokens and cost without calling API |
| `--replay` | — | `""` | Replay a previous run from its artifact directory |
| `--continue-run` | — | `""` | Resume an incomplete run from its artifact directory |
| `--log-level` | — | `INFO` | Logging verbosity |

## Artifact Directories

Every run (including dry-runs) saves all intermediate artifacts to a timestamped directory under `runs/`:

```
runs/
├── run-slides-20260309-143052/       # Full conversion
├── dry-run-slides-20260309-142000/   # Dry-run
└── replay-slides-20260310-100000/    # Replay of a previous run
```

Each directory contains:

```
runs/run-slides-20260309-143052/
├── slides.pdf                   # Copy of input PDF (for reproducibility)
├── slides.pptx                  # Copy of output PPTX
├── run_params.json              # CLI parameters used for this run
├── pages/
│   ├── page_000.png             # Rendered page images
│   ├── page_001.png
│   └── ...
├── messages_00.json             # API messages (base64 replaced with file paths)
├── messages_01.json             # (per-batch)
├── messages_full_00.json        # API messages (complete with base64)
├── messages_full_01.json        # (per-batch)
├── system_prompt.md             # System prompt sent to the model
├── tools.json                   # Tool definitions
├── token_estimate.json          # Token count and cost estimate
├── api_response_00.json         # API response metadata and usage stats
├── api_response_01.json         # (per-batch)
├── stream_chunks_00.jsonl       # Raw streaming chunks (JSONL)
├── stream_chunks_01.jsonl       # (per-batch)
├── stream_batch_00.log          # Real-time streaming output log
├── stream_batch_01.log          # (per-batch)
├── tool_calls_00.json           # Parsed tool call results
├── tool_calls_01.json           # (per-batch)
├── reasoning_00.txt             # Model's thinking/reasoning process
├── reasoning_01.txt             # (per-batch)
├── content_00.txt               # Model's non-tool-call text output
├── content_01.txt               # (per-batch)
├── slides/
│   ├── slide_000.xml            # Generated PresentationML XML per slide
│   ├── slide_001.xml
│   └── ...
└── metadata.json                # Run metadata (timing, token totals, etc.)
```

For multi-batch conversions, per-batch artifacts use zero-padded suffixes (e.g., `_00`, `_01`). Single-batch runs also use `_0` suffix.

Dry-run directories use the `dry-run-` prefix and contain only pre-API artifacts. Replay directories use the `replay-` prefix and include a `replay_of` field in `metadata.json`.

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

Batch size is auto-calculated based on a 600-second gateway timeout, the assumed output TPS (50 tok/s, configurable via `--output-tps`), and the reasoning effort multiplier. For large PDFs exceeding the batch size:
- Pages are split into overlapping batches (2-page overlap)
- Each batch is processed in a separate API call
- Each batch uses batch-local page indices (0 to batch_size-1) when communicating with the LLM, with an internal mapping to actual PDF page numbers for artifact storage
- When animations are enabled, the later batch's version of overlapping pages is preferred for better transition context

## Project Structure

```
p2p/
├── src/
│   ├── __init__.py              # ApiConfig dataclass
│   ├── __main__.py              # python -m src entry point
│   ├── main.py                  # CLI entry point and pipeline orchestration
│   ├── system_prompt.py         # System prompts (EN/ZH) and tool definitions
│   ├── pdf_preprocessor.py      # PDF → PNG rendering via PyMuPDF
│   ├── message_builder.py       # OpenAI/Anthropic messages construction
│   ├── token_estimator.py       # Token counting, cost estimation, batch sizing
│   ├── api_client.py            # OpenAI streaming LLM API client
│   ├── api_client_anthropic.py  # Anthropic streaming LLM API client
│   ├── xml_validator.py         # XML validation and repair
│   ├── pptx_assembler.py        # PPTX file assembly from slide XMLs
│   ├── postprocessor.py         # Raster placeholder replacement
│   ├── artifacts.py             # Artifact directory management (under runs/)
│   ├── dry_run.py               # Dry-run mode implementation
│   ├── replay.py                # Replay a previous run from saved parameters
│   ├── continue_run.py          # Resume incomplete runs (--continue-run)
│   └── logging_config.py        # Rich-based logging configuration
├── tests/
│   ├── conftest.py              # Shared fixtures and mock servers
│   ├── test_e2e.py              # Core pipeline e2e tests
│   ├── test_error_recovery.py   # Error recovery e2e tests
│   ├── test_continue_run.py     # --continue-run e2e tests
│   ├── test_pdf_preprocessor.py # PDF preprocessing unit tests
│   ├── test_message_builder.py  # Message building unit tests
│   ├── test_token_estimator.py  # Token estimation unit tests
│   ├── test_xml_validator.py    # XML validation unit tests
│   ├── test_system_prompt.py    # System prompt unit tests
│   ├── test_artifacts.py        # Artifact store unit tests
│   ├── test_pptx_assembler.py   # PPTX assembly unit tests
│   └── test_misc.py             # Anthropic effort/budget mapping + logging tests
├── docs/
│   └── design.md                # Detailed design document (EN + ZH)
├── Makefile                     # Development and conversion commands
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

The test suite includes 89 tests across 11 focused modules:

**End-to-end tests:**
- `test_e2e.py` — core pipeline: dry-run, full conversion (OpenAI + Anthropic), custom output TPS, multi-batch conversion, folder input conversion and dry-run
- `test_error_recovery.py` — batch-level error recovery: retry, skip to post-processing, quit with metadata
- `test_continue_run.py` — resume incomplete runs: post-process only, generate missing, quit, missing directory

**Unit tests** (one module per source file):
- `test_pdf_preprocessor.py` — page rendering, PNG output, metadata, DPI scaling, aspect ratio detection
- `test_message_builder.py` — message structure, animation toggle, image embedding, bilingual prompts, Anthropic format
- `test_token_estimator.py` — text/image token counting, cost estimation, response time, custom TPS, model-aware image tokens
- `test_xml_validator.py` — valid XML passthrough, fence stripping, declaration injection, namespace repair, fallback slides
- `test_system_prompt.py` — EN/ZH prompts, animation sections, tool definitions (OpenAI + Anthropic), font calibration
- `test_artifacts.py` — directory creation, dry-run/replay prefixes, input copying, metadata/params/reasoning saving
- `test_pptx_assembler.py` — single/multi slide assembly, dimensions, hyperlink handling
- `test_misc.py` — Anthropic adaptive effort level mapping, thinking budget (legacy models), logging configuration

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

## Notes

When using folder input, raster post-processing is automatically skipped since there is no source PDF to crop from. Supported image formats: PNG, JPG, JPEG, BMP, TIFF, WebP.

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
- **错误恢复** — API 调用失败时交互式重试/跳过/退出；保留已完成进度，支持部分组装
- **继续运行** — 从之前的运行目录恢复未完成的转换（`--continue-run`）
- **重放** — 使用相同参数重新运行之前的转换（`--replay`）
- **即时幻灯片持久化** — 流式传输过程中，每个幻灯片 XML 在其工具调用完成后立即写入磁盘，防止崩溃导致数据丢失
- **可配置 TPS** — 调整预估输出 token 速率以获得准确的时间估算（`--output-tps`，默认 50）
- **自动提供商检测** — 当模型名称以 `claude-` 开头时自动选择 Anthropic API 格式
- **图片文件夹输入** — 除 PDF 文件外，还支持以幻灯片截图文件夹（PNG、JPG 等）作为输入，按文件名升序排列
- **双语提示词** — 系统提示词支持英文和中文（`--prompt-lang`）
- **可选动画** — 当相邻幻灯片布局相似时添加 Morph 转场和入场动画（`--enable-animations`）

## 架构

```
PDF ──→ [PyMuPDF] ──→ 页面图像 ──→ [LLM API] ──→ 幻灯片 XML ──→ [python-pptx] ──→ PPTX
                       (192 DPI)      (流式输出)        (已验证)         (已组装)
                                                            │
                                                            ▼
                                                     [后处理器]
                                                     (300 DPI 光栅填充)
```

**处理流程：**

1. **预处理** — 将每页 PDF 渲染为高分辨率 PNG 图像（默认 192 DPI），或直接从文件夹加载图片（按文件名排序）
2. **消息构建** — 构建包含系统提示词、页面图像和任务指令的 OpenAI Chat Completions 消息
3. **LLM API 调用** — 流式接收 LLM 的响应，提取每页的 `write_slide_xml` 工具调用及 PresentationML XML；每个幻灯片 XML 在工具调用完成后立即持久化到磁盘
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

# 从幻灯片截图文件夹转换
p2p ./slide_images/
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
  DPI:              192
  Model:            gpt-5.4
  Batch size:       4 (auto)
  Batches:          4
------------------------------------------------------------
  Per-batch estimate:
    Text tokens:    3,200
    Image tokens:   5,200 (4 images)
    Input tokens:   8,400
    Output tokens:  ~16,000
    Response time:  ~800s (~13.3 min)
  Total estimate (4 batches):
    Input tokens:   33,600
    Output tokens:  ~64,000
    Total tokens:   ~97,600
    Response time:  ~3200s (~53.3 min)
  Est. cost:        $0.6200
------------------------------------------------------------
  Output TPS:       50 tok/s (reasoning=medium, ×1.5)
============================================================
```

### 4. 重放之前的运行

```bash
# 使用相同参数重新运行之前的转换
p2p dummy --replay runs/run-slides-20260309-143052
```

### 5. 继续未完成的运行

```bash
# 从之前中断的运行恢复
p2p dummy --continue-run runs/run-slides-20260310-161844
```

## 命令行参数

```
用法: p2p [-h] [-o OUTPUT] [--api-provider {openai,anthropic}]
          [--api-base-url URL] [--api-key KEY] [--model-name MODEL]
          [--dpi {96,144,192,288}] [--enable-animations]
          [--reasoning-effort {low,medium,high,xhigh}]
          [--prompt-lang {en,zh}] [--max-pages N] [--pages SPEC]
          [--batch-size N] [--output-tps TPS] [--skip-postprocess]
          [--dry-run] [--replay DIR] [--continue-run DIR]
          [--log-level {DEBUG,INFO,WARNING,ERROR}]
          pdf
```

| 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `pdf` | — | *（必填）* | 输入 PDF 文件或幻灯片截图文件夹 |
| `-o`, `--output` | — | `<文件名>.pptx` | 输出 PPTX 文件路径 |
| `--api-provider` | `LLM_PROVIDER` | `openai` | API 提供商：`openai` 或 `anthropic`（可从模型名自动检测） |
| `--api-base-url` | `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` | `""` | API 基础 URL |
| `--api-key` | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | `""` | API 密钥 |
| `--model-name` | `OPENAI_MODEL_NAME` / `ANTHROPIC_MODEL_NAME` | `gpt-5.4` | 模型名称 |
| `--dpi` | — | `192` | LLM 输入图像的渲染 DPI（96/144/192/288） |
| `--enable-animations` | — | `关闭` | 启用 Morph 转场和动画 |
| `--reasoning-effort` | — | `medium` | 模型推理强度（low/medium/high/xhigh） |
| `--prompt-lang` | — | `en` | 系统提示词语言（en/zh） |
| `--max-pages` | — | `5` | 最大转换页数（0=全部）；与 `--pages` 互斥 |
| `--pages` | — | `""` | 指定页面，如 `0,2,5-8`；与 `--max-pages` 互斥 |
| `--batch-size` | — | `0`（自动） | 每次 API 调用的页数（0=根据网关超时自动计算） |
| `--output-tps` | — | `50` | 预估输出 token 速率（tok/s），用于时间估算 |
| `--skip-postprocess` | — | `关闭` | 跳过光栅图像后处理 |
| `--dry-run` | — | `关闭` | 估算 token 和成本，不调用 API |
| `--replay` | — | `""` | 从产物目录重放之前的运行 |
| `--continue-run` | — | `""` | 从产物目录恢复未完成的运行 |
| `--log-level` | — | `INFO` | 日志详细程度 |

## 产物目录

每次运行（包括试运行）都会将所有中间产物保存到 `runs/` 下的带时间戳目录：

```
runs/
├── run-slides-20260309-143052/       # 完整转换
├── dry-run-slides-20260309-142000/   # 试运行
└── replay-slides-20260310-100000/    # 重放之前的运行
```

每个目录包含：

```
runs/run-slides-20260309-143052/
├── slides.pdf                   # 输入 PDF 的副本（便于复现）
├── slides.pptx                  # 输出 PPTX 的副本
├── run_params.json              # 本次运行的 CLI 参数
├── pages/
│   ├── page_000.png             # 渲染的页面图像
│   ├── page_001.png
│   └── ...
├── messages_00.json             # API 消息（base64 替换为文件路径）
├── messages_01.json             # （每批次）
├── messages_full_00.json        # API 消息（包含完整 base64）
├── messages_full_01.json        # （每批次）
├── system_prompt.md             # 发送给模型的系统提示词
├── tools.json                   # 工具定义
├── token_estimate.json          # Token 计数和成本估算
├── api_response_00.json         # API 响应元数据和使用统计
├── api_response_01.json         # （每批次）
├── stream_chunks_00.jsonl       # 原始流式数据块（JSONL）
├── stream_chunks_01.jsonl       # （每批次）
├── stream_batch_00.log          # 实时流式输出日志
├── stream_batch_01.log          # （每批次）
├── tool_calls_00.json           # 解析后的工具调用结果
├── tool_calls_01.json           # （每批次）
├── reasoning_00.txt             # 模型的思考/推理过程
├── reasoning_01.txt             # （每批次）
├── content_00.txt               # 模型的非工具调用文本输出
├── content_01.txt               # （每批次）
├── slides/
│   ├── slide_000.xml            # 每页生成的 PresentationML XML
│   ├── slide_001.xml
│   └── ...
└── metadata.json                # 运行元数据（耗时、token 总计等）
```

对于多批次转换，每批次的产物文件使用零填充后缀（如 `_00`、`_01`）。单批次运行也使用 `_0` 后缀。

试运行目录使用 `dry-run-` 前缀，仅包含 API 调用前的产物。重放目录使用 `replay-` 前缀，`metadata.json` 中包含 `replay_of` 字段。

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

批次大小根据 600 秒网关超时、假设的输出速度（50 tok/s，可通过 `--output-tps` 配置）和推理强度倍率自动计算。对于超过批次大小的大型 PDF：
- 页面被分为有重叠的批次（2 页重叠）
- 每个批次通过单独的 API 调用处理
- 每个批次在与 LLM 通信时使用批次内部页码索引（0 到 batch_size-1），通过内部映射表将其转换为实际 PDF 页码用于产物存储
- 启用动画时，重叠页面优先使用后一批次的版本以获得更好的转场上下文

## 项目结构

```
p2p/
├── src/
│   ├── __init__.py              # ApiConfig 数据类
│   ├── __main__.py              # python -m src 入口
│   ├── main.py                  # CLI 入口和流程编排
│   ├── system_prompt.py         # 系统提示词（中/英）和工具定义
│   ├── pdf_preprocessor.py      # PDF → PNG 渲染（PyMuPDF）
│   ├── message_builder.py       # OpenAI/Anthropic 消息构建
│   ├── token_estimator.py       # Token 计数、成本估算、批次大小计算
│   ├── api_client.py            # OpenAI 流式 LLM API 客户端
│   ├── api_client_anthropic.py  # Anthropic 流式 LLM API 客户端
│   ├── xml_validator.py         # XML 验证和修复
│   ├── pptx_assembler.py        # 从幻灯片 XML 组装 PPTX 文件
│   ├── postprocessor.py         # 光栅占位符替换
│   ├── artifacts.py             # 产物目录管理（runs/ 下）
│   ├── dry_run.py               # 试运行模式实现
│   ├── replay.py                # 从保存的参数重放之前的运行
│   ├── continue_run.py          # 恢复未完成的运行（--continue-run）
│   └── logging_config.py        # 基于 Rich 的日志配置
├── tests/
│   ├── conftest.py              # 共享 fixtures 和模拟服务器
│   ├── test_e2e.py              # 核心流程端到端测试
│   ├── test_error_recovery.py   # 错误恢复端到端测试
│   ├── test_continue_run.py     # --continue-run 端到端测试
│   ├── test_pdf_preprocessor.py # PDF 预处理单元测试
│   ├── test_message_builder.py  # 消息构建单元测试
│   ├── test_token_estimator.py  # Token 估算单元测试
│   ├── test_xml_validator.py    # XML 验证单元测试
│   ├── test_system_prompt.py    # 系统提示词单元测试
│   ├── test_artifacts.py        # 产物存储单元测试
│   ├── test_pptx_assembler.py   # PPTX 组装单元测试
│   └── test_misc.py             # Anthropic effort/budget 映射 + 日志测试
├── docs/
│   └── design.md                # 详细设计文档（中英双语）
├── Makefile                     # 开发和转换命令
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

测试套件包含 89 项测试，分布在 11 个专注模块中：

**端到端测试：**
- `test_e2e.py` — 核心流程：试运行、完整转换（OpenAI + Anthropic）、自定义输出 TPS、多批次转换、文件夹输入转换和试运行
- `test_error_recovery.py` — 批次级错误恢复：重试、跳过到后处理、退出并保存元数据
- `test_continue_run.py` — 恢复未完成运行：仅后处理、生成缺失页、退出、目录不存在

**单元测试**（每个源文件一个测试模块）：
- `test_pdf_preprocessor.py` — 页面渲染、PNG 输出、元数据、DPI 缩放、宽高比检测
- `test_message_builder.py` — 消息结构、动画开关、图像嵌入、双语提示词、Anthropic 格式
- `test_token_estimator.py` — 文本/图像 token 计数、成本估算、响应时间、自定义 TPS、模型感知图像 token
- `test_xml_validator.py` — 有效 XML 透传、围栏去除、声明注入、命名空间修复、回退幻灯片
- `test_system_prompt.py` — 中英文提示词、动画部分、工具定义（OpenAI + Anthropic）、字体校准
- `test_artifacts.py` — 目录创建、试运行/重放前缀、输入复制、元数据/参数/推理保存
- `test_pptx_assembler.py` — 单页/多页组装、尺寸、超链接处理
- `test_misc.py` — Anthropic adaptive effort 映射、思考预算（旧模型）、日志配置

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

## 说明

使用文件夹输入时，光栅后处理会自动跳过，因为没有源 PDF 可供裁剪。支持的图片格式：PNG、JPG、JPEG、BMP、TIFF、WebP。

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
