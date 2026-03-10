# PDF Slides → PPTX 转换工具：方案设计

## 1. 项目概述

### 1.1 目标

构建一个基于多模态大模型（GPT-5.4 / Claude Opus-4.6）的工具，将 PDF 格式的演示文稿（slides）转换为高保真、可编辑的 Microsoft PowerPoint（PPTX）文件。核心设计原则：

- **多提供商支持**：支持 OpenAI API（GPT-5.4）与 Anthropic API（Claude Opus-4.6），通过 `--api-provider` 切换
- **视觉一致性**：转换后的 PPTX 在视觉上尽可能还原原始 slides 的外观
- **可编辑性**：最大程度使用 PowerPoint 原生矢量元素（文本框、形状、表格、公式等），而非将整页作为图片嵌入
- **光栅图占位**：对于无法矢量化的光栅图区域，使用带坐标标注的占位框，便于后处理回填
- **动画增强（可选）**：相邻页面布局相似时，利用 PowerPoint 动画 / 转场效果增强演示体验。此功能通过 `--enable-animations` 开关控制，默认关闭
- **单次 API 调用**：通过精心构建的 Messages 历史，一次 API 调用完成所有页面的分析与 Slide XML 生成
- **直接输出 Slide XML**：LLM（GPT-5.4 / Claude Opus-4.6）直接输出符合 Microsoft PowerPoint 标准的 PresentationML（OOXML）格式 slide XML，而非中间 JSON 指令，减少转换层次，最大化表达能力
- **标准兼容**：生成的 PPTX 文件严格遵循 Microsoft PowerPoint 标准，确保在 PowerPoint 中可正常打开、编辑和演示
- **Dry-run 模式**：通过 `--dry-run` 开关，完成 API 调用前的所有准备工作并导出中间产物，用于调试和成本预估
- **丰富日志**：全流程结构化日志输出，涵盖每个阶段的关键指标和进度信息

### 1.2 核心架构决策：GPT-5.4 直接输出 Slide XML

**为什么不使用中间 JSON 指令格式？**

PPTX 文件本质上是一个 ZIP 包，其中每页 slide 对应一个 XML 文件（`ppt/slides/slideN.xml`），使用 PresentationML（OOXML）格式。如果设计一套中间 JSON Schema 让 GPT-5.4 输出，再由 Python 代码翻译为 OOXML，会引入以下问题：

1. **表达能力受限**：中间 JSON 无论设计得多完善，都无法覆盖 OOXML 的全部能力（约 180 种预设形状、贝塞尔曲线、渐变、阴影、3D、公式等）
2. **翻译层引入误差**：JSON → OOXML 的翻译代码本身可能有 bug，且难以覆盖所有边界情况
3. **工具调用次数爆炸**：如果用 Tool Calling 让 GPT-5.4 逐个调用 "add_textbox"、"add_shape" 等工具，一个 20 页 PPT 可能涉及数百次顺序工具调用

**更优方案**：让 GPT-5.4 直接输出每页 slide 的 PresentationML XML 内容，通过 N 次 `write_slide_xml` 工具调用（N = 页数）将 XML 写入文件，最后由组装器将这些 XML 文件打包为合法的 PPTX。

| 方案 | 工具调用次数 | 表达能力 | 实现复杂度 |
|------|-------------|---------|-----------|
| 中间 JSON + Python 渲染 | 1 次（Structured Output） | 受限于 JSON Schema 设计 | 高（需实现完整渲染器） |
| 逐元素 Tool Calling | 数百次 | 受限于工具定义 | 高（需实现每种元素的工具） |
| **直接输出 Slide XML** | **N 次（N = 页数）** | **OOXML 全部能力** | **低（仅需组装器）** |

### 1.3 技术栈

| 组件 | 技术选型 | 用途 |
|------|----------|------|
| PDF 解析 | PyMuPDF (fitz) | PDF 页面渲染为高分辨率图片 |
| LLM | GPT-5.4 (OpenAI API) / Claude Opus-4.6 (Anthropic API) | 多模态分析 + 直接生成 Slide XML |
| PPTX 组装 | python-pptx + lxml + zipfile | 将 Slide XML 组装为合法 PPTX |
| 图片后处理 | Pillow / PyMuPDF | 光栅图区域裁剪与回填 |
| Token 估算 | tiktoken | Messages token 数量估算 |
| OpenAI SDK | openai | OpenAI API 调用 |
| Anthropic SDK | anthropic | Anthropic API 调用 |
| 日志 | Python logging (Rich) | 结构化彩色日志输出 |

---

## 2. 系统架构

### 2.1 整体流程

```
┌─────────────┐     ┌──────────────────┐     ┌───────────────────────┐     ┌──────────────────┐
│  PDF Input   │────▶│  Preprocessing   │────▶│  LLM Generation       │────▶│  PPTX Assembler   │
│  (slides)    │     │  (PDF → Images)  │     │  (Single API Call)     │     │  (XML → PPTX)     │
└─────────────┘     └──────────────────┘     │  N × write_slide_xml  │     └──────────────────┘
                                              └───────────────────────┘              │
                                                                                     ▼
                                                                              ┌──────────────┐
                                                                              │ Post-process  │
                                                                              │ (光栅图回填)   │
                                                                              └──────────────┘
                                                                                     │
                                                                                     ▼
                                                                              ┌──────────────┐
                                                                              │  Final PPTX   │
                                                                              └──────────────┘
```

### 2.2 阶段详解

#### Phase 1: 预处理（Preprocessing）

将 PDF 每页渲染为高分辨率图片，直接交给 GPT-5.4 进行视觉分析。

```python
import fitz  # PyMuPDF

def pdf_to_images(pdf_path: str, dpi: int = 288) -> list[tuple[bytes, dict]]:
    """将 PDF 每页转为 PNG 图片供 LLM 分析。"""
    doc = fitz.open(pdf_path)
    pages = []
    for page_num in range(doc.page_count):
        page = doc[page_num]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        metadata = {
            "page_num": page_num,       # 0-indexed，与 PDF 页码一致
            "width_pt": page.rect.width,
            "height_pt": page.rect.height,
            "width_px": pix.width,
            "height_px": pix.height,
        }
        pages.append((img_bytes, metadata))
    return pages
```

关键设计决策：

- **DPI 选择**：LLM 输入图片默认 192 DPI（2× 标准屏幕分辨率），可选 96/144/192/288；后处理阶段裁剪光栅图时仍使用 300 DPI 以保证输出质量
- **不提取 PDF 文本层**：完全依赖 GPT-5.4 的视觉理解能力，避免文本层提取引入的格式丢失和乱序问题。GPT-5.4 的多模态能力足以准确识别图片中的文字
- **页码编号**：使用 PDF 中的原始页码序号（0-indexed），简单直接

#### Phase 2: 构建 Messages 并调用 GPT-5.4（Single API Call with Tool Calling）

核心思路：将所有页面图片组织为一个 OpenAI Chat Completions 请求，通过 **Tool Calling** 让 GPT-5.4 为每页 slide 调用一次 `write_slide_xml` 工具，直接输出该页的 PresentationML XML。

```python
import openai, base64

def build_messages(
    pages: list[tuple[bytes, dict]],
    enable_animations: bool = False,
    prompt_lang: str = "en",
) -> list[dict]:
    """构建单次 API 调用的 Messages 数组。"""
    system_prompt = SYSTEM_PROMPT
    if enable_animations:
        system_prompt += ANIMATION_SECTION

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    user_content = []
    n = len(pages)
    slide_w = pages[0][1]["width_pt"]
    slide_h = pages[0][1]["height_pt"]
    emu_w = int(slide_w * 12700)
    emu_h = int(slide_h * 12700)

    # 简短介绍
    user_content.append({
        "type": "text",
        "text": f"Below are {n} slide page images to convert. "
                f"Slide dimensions: {slide_w}pt × {slide_h}pt.",
    })

    # 每页图片，使用 PDF 中的原始页码序号
    for img_bytes, meta in pages:
        page_num = meta["page_num"]
        user_content.append({
            "type": "text",
            "text": f"\n--- Page {page_num} ---"
        })
        b64 = base64.b64encode(img_bytes).decode()
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{b64}",
                "detail": "high"
            }
        })

    # 详细任务指令放在所有图片之后
    user_content.append({
        "type": "text",
        "text": (
            f"\n--- Task ---\n"
            f"Convert each of the {n} slide images above into OOXML (Office Open XML) "
            f"PresentationML format — the native XML representation used inside PPTX files.\n"
            f"Slide dimensions: {emu_w} EMU × {emu_h} EMU ({slide_w}pt × {slide_h}pt).\n\n"
            f"CRITICAL: You have only ONE response to complete this entire task. "
            f"In this single response, you MUST make exactly {n} parallel tool calls to "
            f"write_slide_xml — one for each page (page_num 0 through {n - 1}). "
            f"Do NOT stop after converting just one page. Convert ALL {n} pages now.\n\n"
            f"REMINDER — Atomic Reconstruction: Decompose every visual region into its smallest "
            f"independently rebuildable units. ... Apply the 20%% font size reduction rule."
        ),
    })

    messages.append({"role": "user", "content": user_content})
    return messages
```

#### Phase 3: API 调用与工具执行

```python
def call_llm(
    messages: list[dict],
    api_base_url: str = "",
    api_key: str = "",
    model_name: str = "gpt-5.4",
    max_tokens: int = 128000,
    stream_log_path: str = "",
    reasoning_effort: str = "medium",
    estimated_response_seconds: float = 0,
) -> LLMResult:
    """流式 API 调用，GPT-5.4 通过 tool calling 输出每页的 slide XML。

    使用 streaming 模式实时输出到 stderr 并记录到文件。
    超时时间动态计算：max(estimated_response_seconds * 2, 600) 秒。
    返回 LLMResult 包含 slide_xmls、response_data、raw_chunks 等。
    """
    timeout_seconds = max(estimated_response_seconds * 3, 600)
    timeout = httpx.Timeout(timeout_seconds, connect=30.0)

    client_kwargs = {"timeout": timeout, "max_retries": 0}
    if api_base_url:
        client_kwargs["base_url"] = api_base_url
    if api_key:
        client_kwargs["api_key"] = api_key
    client = openai.OpenAI(**client_kwargs)

    tools = [WRITE_SLIDE_XML_TOOL]
    create_kwargs = {
        "model": model_name,
        "messages": messages,
        "tools": tools,
        "tool_choice": "required",
        "parallel_tool_calls": True,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if reasoning_effort:
        create_kwargs["reasoning_effort"] = reasoning_effort

    stream = client.chat.completions.create(**create_kwargs)
    # 消费流式响应，实时输出到 stderr 和日志文件
    # 解析 tool calls，提取 slide_xmls
    # 返回 LLMResult(slide_xmls, response_data, raw_chunks, tool_calls_raw, content_text)
```

#### Phase 4: PPTX 组装（Assembler）

将 GPT-5.4 输出的 Slide XML 文件组装为合法的 PPTX 包。详见第 4 节。

#### Phase 5: 后处理（Post-processing）

扫描生成的 PPTX 中的 `__LLMCLIP__` 占位框，从原始 PDF 中裁剪对应区域的图片并回填。详见第 5 节。

---

## 3. Tool 定义与 Slide XML 格式

### 3.1 write_slide_xml 工具定义

```json
{
  "type": "function",
  "function": {
    "name": "write_slide_xml",
    "description": "Write the PresentationML XML for one slide page. Call this tool once for each page in the PDF.",
    "parameters": {
      "type": "object",
      "properties": {
        "page_num": {
          "type": "integer",
          "description": "The PDF page number for this slide (0-indexed)"
        },
        "slide_xml": {
          "type": "string",
          "description": "Complete PresentationML slide XML content (<p:sld> root element) containing all shapes, text, styles, animations, etc. for this page"
        }
      },
      "required": ["page_num", "slide_xml"]
    }
  }
}
```

### 3.2 Slide XML 结构概览

GPT-5.4 输出的每页 slide XML 应为完整的 `<p:sld>` 文档：

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main"
       xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
       xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
       xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main">

  <!-- 背景 -->
  <p:bg>
    <p:bgPr>
      <a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>
      <a:effectLst/>
    </p:bgPr>
  </p:bg>

  <!-- 公共 Slide 数据 -->
  <p:cSld>
    <p:spTree>
      <!-- Shape Tree 组属性 -->
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="12192000" cy="6858000"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="12192000" cy="6858000"/>
        </a:xfrm>
      </p:grpSpPr>

      <!-- === 以下为各种元素 === -->

      <!-- 文本框示例 -->
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Title"/>
          <p:cNvSpPr txBox="1"/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="457200" y="274638"/>
            <a:ext cx="8229600" cy="1143000"/>
          </a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:noFill/>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" rtlCol="0" anchor="ctr"/>
          <a:lstStyle/>
          <a:p>
            <a:pPr algn="ctr"/>
            <a:r>
              <a:rPr lang="zh-CN" sz="4400" b="1" dirty="0">
                <a:solidFill><a:srgbClr val="333333"/></a:solidFill>
                <a:latin typeface="Microsoft YaHei"/>
                <a:ea typeface="Microsoft YaHei"/>
              </a:rPr>
              <a:t>演示文稿标题</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>

      <!-- 预设形状示例（圆角矩形） -->
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="RoundedRect1"/>
          <p:cNvSpPr/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="1000000" y="2000000"/>
            <a:ext cx="3000000" cy="1500000"/>
          </a:xfrm>
          <a:prstGeom prst="roundRect">
            <a:avLst>
              <a:gd name="adj" fmla="val 16667"/>
            </a:avLst>
          </a:prstGeom>
          <a:solidFill><a:srgbClr val="4472C4"/></a:solidFill>
          <a:ln w="12700">
            <a:solidFill><a:srgbClr val="2F5496"/></a:solidFill>
          </a:ln>
          <a:effectLst>
            <a:outerShdw blurRad="50800" dist="38100" dir="5400000"
                         algn="t" rotWithShape="0">
              <a:srgbClr val="000000"><a:alpha val="40000"/></a:srgbClr>
            </a:outerShdw>
          </a:effectLst>
        </p:spPr>
        <p:txBody>
          <a:bodyPr anchor="ctr"/>
          <a:lstStyle/>
          <a:p>
            <a:pPr algn="ctr"/>
            <a:r>
              <a:rPr lang="en-US" sz="2000" b="1">
                <a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>
              </a:rPr>
              <a:t>Shape with Shadow</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>

      <!-- 表格示例 -->
      <p:graphicFrame>
        <p:nvGraphicFramePr>
          <p:cNvPr id="4" name="Table1"/>
          <p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>
          <p:nvPr/>
        </p:nvGraphicFramePr>
        <p:xfrm>
          <a:off x="500000" y="4000000"/>
          <a:ext cx="8000000" cy="2000000"/>
        </p:xfrm>
        <a:graphic>
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">
            <a:tbl>
              <a:tblPr firstRow="1" bandRow="1"/>
              <a:tblGrid>
                <a:gridCol w="4000000"/>
                <a:gridCol w="4000000"/>
              </a:tblGrid>
              <a:tr h="600000">
                <a:tc>
                  <a:txBody>
                    <a:bodyPr/><a:lstStyle/>
                    <a:p><a:r><a:rPr lang="en-US" b="1"/><a:t>Header 1</a:t></a:r></a:p>
                  </a:txBody>
                  <a:tcPr>
                    <a:solidFill><a:srgbClr val="4472C4"/></a:solidFill>
                  </a:tcPr>
                </a:tc>
                <a:tc>
                  <a:txBody>
                    <a:bodyPr/><a:lstStyle/>
                    <a:p><a:r><a:rPr lang="en-US" b="1"/><a:t>Header 2</a:t></a:r></a:p>
                  </a:txBody>
                  <a:tcPr>
                    <a:solidFill><a:srgbClr val="4472C4"/></a:solidFill>
                  </a:tcPr>
                </a:tc>
              </a:tr>
              <!-- 更多行... -->
            </a:tbl>
          </a:graphicData>
        </a:graphic>
      </p:graphicFrame>

      <!-- 自由曲线（贝塞尔）示例 -->
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="5" name="Freeform1"/>
          <p:cNvSpPr/><p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="6000000" y="2000000"/>
            <a:ext cx="2000000" cy="1500000"/>
          </a:xfrm>
          <a:custGeom>
            <a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>
            <a:rect l="0" t="0" r="2000000" b="1500000"/>
            <a:pathLst>
              <a:path w="2000000" h="1500000">
                <a:moveTo><a:pt x="0" y="1500000"/></a:moveTo>
                <a:cubicBezTo>
                  <a:pt x="500000" y="0"/>
                  <a:pt x="1500000" y="0"/>
                  <a:pt x="2000000" y="1500000"/>
                </a:cubicBezTo>
              </a:path>
            </a:pathLst>
          </a:custGeom>
          <a:solidFill><a:srgbClr val="70AD47"/></a:solidFill>
        </p:spPr>
      </p:sp>

      <!-- 光栅图占位框示例 -->
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="6" name="RasterPlaceholder1"/>
          <p:cNvSpPr/><p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="8500000" y="500000"/>
            <a:ext cx="3000000" cy="2000000"/>
          </a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:noFill/>
          <a:ln w="12700" cap="flat">
            <a:solidFill><a:srgbClr val="FF0000"/></a:solidFill>
            <a:prstDash val="dash"/>
          </a:ln>
        </p:spPr>
        <p:txBody>
          <a:bodyPr anchor="ctr"/>
          <a:lstStyle/>
          <a:p>
            <a:pPr algn="ctr"/>
            <a:r>
              <a:rPr lang="en-US" sz="1000">
                <a:solidFill><a:srgbClr val="FF0000"/></a:solidFill>
              </a:rPr>
              <a:t>__LLMCLIP__:[669.3, 39.4][905.5, 196.9]</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>

    </p:spTree>
  </p:cSld>

  <!-- 转场效果（可选，仅在启用动画时） -->
  <p:transition spd="med" advClick="1">
    <p:fade/>
  </p:transition>

  <!-- 动画定时（可选，仅在启用动画时） -->
  <p:timing>
    <p:tnLst>
      <p:par>
        <p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot">
          <p:childTnLst>
            <!-- 动画序列... -->
          </p:childTnLst>
        </p:cTn>
      </p:par>
    </p:tnLst>
  </p:timing>

</p:sld>
```

### 3.3 GPT-5.4 可使用的 OOXML 元素清单

GPT-5.4 在生成 slide XML 时，可以使用以下 PresentationML / DrawingML 元素（不限于此列表）：

| 类别 | 元素 | 用途 |
|------|------|------|
| **文本框** | `<p:sp>` + `txBox="1"` | 所有文字内容 |
| **预设形状** | `<p:sp>` + `<a:prstGeom>` | 矩形、椭圆、箭头、星形等 ~180 种 |
| **自由曲线** | `<p:sp>` + `<a:custGeom>` | 自定义路径、贝塞尔曲线、多边形 |
| **表格** | `<p:graphicFrame>` + `<a:tbl>` | 结构化行列数据 |
| **图表** | `<p:graphicFrame>` + `<c:chart>` | 柱状图、折线图、饼图等 |
| **数学公式** | `<a14:m>` + `<m:oMath>` | Office Math ML 原生公式 |
| **组合** | `<p:grpSp>` | 将多个形状组合为一组 |
| **连接线** | `<p:cxnSp>` | 形状间的连接线 |
| **图片引用** | `<p:pic>` | 引用嵌入的图片资源 |
| **填充** | `<a:solidFill>` / `<a:gradFill>` / `<a:pattFill>` | 纯色 / 渐变 / 图案填充 |
| **线条** | `<a:ln>` | 边框、线条样式 |
| **阴影** | `<a:outerShdw>` / `<a:innerShdw>` | 外阴影 / 内阴影 |
| **3D** | `<a:sp3d>` / `<a:scene3d>` | 3D 效果 |
| **旋转** | `<a:xfrm rot="...">` | 元素旋转 |
| **透明度** | `<a:alpha val="..."/>` | 透明度控制 |
| **转场** | `<p:transition>` | 页面切换效果 |
| **Morph 转场** | `<p14:morph>` + `<mc:AlternateContent>` | 平滑变形动画 |
| **动画** | `<p:timing>` + `<p:tnLst>` | 元素级动画 |
| **项目符号** | `<a:buChar>` / `<a:buAutoNum>` | 列表项目符号 |
| **超链接** | `<a:hlinkClick>` | 可点击链接 |
| **字体** | `<a:latin>` / `<a:ea>` / `<a:cs>` | 西文 / 东亚 / 复杂文字字体 |

### 3.4 坐标系与单位

- **单位**：EMU（English Metric Units），1 pt = 12700 EMU，1 inch = 914400 EMU
- **原点**：页面左上角
- **x 轴**：向右为正
- **y 轴**：向下为正
- **标准 slide 尺寸**：
  - 16:9 → 12192000 × 6858000 EMU（960pt × 540pt）
  - 4:3 → 9144000 × 6858000 EMU（720pt × 540pt）

---

## 4. PPTX 组装器（Assembler）

### 4.1 PPTX 包结构

PPTX 文件是一个 ZIP 包，包含以下结构：

```
output.pptx (ZIP)
├── [Content_Types].xml
├── _rels/
│   └── .rels
├── ppt/
│   ├── presentation.xml
│   ├── _rels/
│   │   └── presentation.xml.rels
│   ├── slides/
│   │   ├── slide1.xml          ← GPT-5.4 生成
│   │   ├── slide2.xml          ← GPT-5.4 生成
│   │   ├── ...
│   │   └── _rels/
│   │       ├── slide1.xml.rels
│   │       ├── slide2.xml.rels
│   │       └── ...
│   ├── slideLayouts/
│   │   └── slideLayout1.xml    ← 空白布局（模板）
│   ├── slideMasters/
│   │   └── slideMaster1.xml    ← 主幻灯片（模板）
│   ├── theme/
│   │   └── theme1.xml          ← 主题（模板）
│   └── media/                  ← 后处理阶段填入的图片
│       ├── image1.png
│       └── ...
└── docProps/
    ├── app.xml
    └── core.xml
```

### 4.2 组装器实现

```python
from pptx import Presentation
from pptx.util import Pt
from lxml import etree
import copy

class PPTXAssembler:
    """将 GPT-5.4 生成的 Slide XML 组装为合法 PPTX 文件。"""

    def __init__(self, slide_width_pt: float, slide_height_pt: float):
        # 创建一个空的 Presentation 作为骨架
        self.prs = Presentation()
        self.prs.slide_width = Pt(slide_width_pt)
        self.prs.slide_height = Pt(slide_height_pt)
        self.blank_layout = self.prs.slide_layouts[6]

    def assemble(self, slide_xmls: dict[int, str]) -> Presentation:
        """
        按页码顺序将 slide XML 注入到 Presentation 中。

        Args:
            slide_xmls: {page_num: slide_xml_string} 字典
        """
        for page_num in sorted(slide_xmls.keys()):
            xml_str = slide_xmls[page_num]
            logger.info(f"  Assembling slide {page_num}...")

            # 先添加一个空白 slide 以建立 relationships
            slide = self.prs.slides.add_slide(self.blank_layout)

            # 解析 GPT-5.4 生成的 XML
            new_sld = etree.fromstring(xml_str.encode("utf-8"))

            # 替换 slide 的内容为 GPT-5.4 生成的内容
            old_sld = slide._element
            # 保留 relationship 相关属性，替换子元素
            for child in list(old_sld):
                old_sld.remove(child)
            for child in new_sld:
                old_sld.append(copy.deepcopy(child))

            # 复制命名空间声明
            for prefix, uri in new_sld.nsmap.items():
                if prefix and prefix not in old_sld.nsmap:
                    old_sld.attrib[f'{{{uri}}}'] = ''

            logger.info(f"  Slide {page_num}: "
                        f"{len(new_sld.findall('.//' + _qn('p:sp')))} shapes, "
                        f"{len(new_sld.findall('.//' + _qn('p:graphicFrame')))} frames")

        return self.prs

    def save(self, output_path: str):
        self.prs.save(output_path)
        logger.info(f"PPTX saved: {output_path}")

def _qn(tag: str) -> str:
    """将简写标签转为完整 Clark notation。"""
    nsmap = {
        'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    }
    prefix, local = tag.split(':')
    return f'{{{nsmap[prefix]}}}{local}'
```

### 4.3 Relationship 处理

当 slide XML 中引用了外部资源（如图片），组装器需要：

1. 扫描 slide XML 中的 `r:embed` 和 `r:link` 属性
2. 为每个引用创建对应的 relationship entry
3. 将引用的资源文件放入 `ppt/media/` 目录

对于光栅图占位框，在组装阶段不需要处理 relationship（占位框是纯文本形状），图片 relationship 在后处理阶段回填时建立。

---

## 5. 光栅图后处理

```python
import fitz, re
from pptx import Presentation
from pptx.util import Pt, Emu
from io import BytesIO

CLIP_PATTERN = re.compile(
    r'__LLMCLIP__:\[([0-9.]+),\s*([0-9.]+)\]\[([0-9.]+),\s*([0-9.]+)\]'
)

def postprocess_raster_fills(pptx_path: str, pdf_path: str, output_path: str, dpi: int = 300):
    """扫描 PPTX 中的 __LLMCLIP__ 占位框，从 PDF 裁剪对应区域并回填。

    后处理阶段固定使用 300 DPI 以保证输出图片质量。
    """
    prs = Presentation(pptx_path)
    doc = fitz.open(pdf_path)
    fill_count = 0

    for slide_idx, slide in enumerate(prs.slides):
        page = doc[slide_idx]
        shapes_to_replace = []

        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            text = shape.text_frame.text.strip()
            match = CLIP_PATTERN.search(text)
            if not match:
                continue

            x1, y1 = float(match.group(1)), float(match.group(2))
            x2, y2 = float(match.group(3)), float(match.group(4))

            # 从 PDF 裁剪对应区域
            clip_rect = fitz.Rect(x1, y1, x2, y2)
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, clip=clip_rect)
            img_bytes = pix.tobytes("png")

            shapes_to_replace.append((shape, img_bytes))

        for shape, img_bytes in shapes_to_replace:
            # 在相同位置插入图片，然后移除占位框
            left, top, width, height = shape.left, shape.top, shape.width, shape.height
            slide.shapes.add_picture(BytesIO(img_bytes), left, top, width, height)
            sp = shape._element
            sp.getparent().remove(sp)
            fill_count += 1

        if shapes_to_replace:
            logger.info(f"  Slide {slide_idx}: {len(shapes_to_replace)} placeholders filled")

    prs.save(output_path)
    logger.info(f"Post-processing complete: {fill_count} raster images filled")
```

---

## 6. GPT-5.4 系统提示词（System Prompt）

> **语言选择**：与 GPT-5.4 交互的所有内容（系统提示词、用户消息）均使用英文，以获得最佳的模型表现。下方提供英文原文及中文译文。

### 6.1 英文原文（实际使用）

```
You are a professional presentation reconstruction engine. Your task is to convert images of PDF slides into OOXML (Office Open XML) PresentationML slide XML — the native XML format used inside PPTX files. The reconstructed slides should visually match the originals as closely as possible while maintaining good editability. The output must be fully compatible with PowerPoint — all elements should be openable, editable, and presentable without errors.

## Output Method

You must convert ALL pages in a single response by making multiple parallel tool calls. For each page, call `write_slide_xml` with:
- `page_num`: the page number (0-indexed, matching the Page number in the user message)
- `slide_xml`: the complete `<p:sld>` XML document

IMPORTANT: Make ALL tool calls in one response. Do not stop after one page — process every page.

## Core Principles

1. **Vector First**: Use PowerPoint native vector elements to express slide content whenever possible. You have access to the full capabilities of PresentationML and DrawingML, including but not limited to:

   - **Text boxes** `<p:sp txBox="1">`: all recognizable text content including titles, body text, annotations, page numbers, etc.
   - **Preset shapes** `<a:prstGeom>`: rectangle `rect`, rounded rectangle `roundRect`, ellipse `ellipse`, arrows, stars, callouts, flowchart symbols, and approximately 180 other preset shapes
   - **Freeform shapes** `<a:custGeom>`: irregular shapes and custom paths built with `<a:moveTo>`, `<a:lnTo>`, `<a:cubicBezTo>`, `<a:close>`
   - **Tables** `<a:tbl>`: structured row-column data with merged cells (`gridSpan`/`rowSpan`), border styles, and cell fills
   - **Math equations** `<a14:m>` + `<m:oMath>`: natively editable formulas in Office Math ML (OMML) format
   - **Charts** `<c:chart>`: bar charts, line charts, pie charts, scatter plots, etc.
   - **Connectors** `<p:cxnSp>`: straight, elbow, and curved connector lines between shapes
   - **Groups** `<p:grpSp>`: logically related elements grouped together

2. **Raster Placeholder**: When a region is a raster image or visual effect that cannot be accurately reproduced using PowerPoint's built-in editing tools (such as photographs, screenshots, complex illustrations, complex gradient backgrounds, textures, etc.), use a rectangle with a red dashed border as a placeholder. The text inside the rectangle should be:
   ```
   __LLMCLIP__:[x1, y1][x2, y2]
   ```
   where x1, y1 are the top-left coordinates and x2, y2 are the bottom-right coordinates, in pt (points), with the origin at the top-left corner of the page. The placeholder's position and size should match the original image region.

3. **Precise Positioning**: All element positions and dimensions must use EMU (English Metric Units). 1 pt = 12700 EMU. Ensure consistency with the original slide layout.

4. **Complete Styling**: Provide as complete styling information as possible for each element:
   - **Fonts**: `<a:latin>`/`<a:ea>`/`<a:cs>` for font families, `sz` for size (hundredths of a point), `b`/`i`/`u`/`strike` for bold/italic/underline/strikethrough
   - **Colors**: `<a:srgbClr val="RRGGBB"/>` for precise color specification
   - **Paragraphs**: `<a:pPr>` with `algn` for alignment, `lnSpc` for line spacing, `spcBef`/`spcAft` for paragraph spacing, `marL`/`indent` for indentation
   - **Bullets**: `<a:buChar>`/`<a:buAutoNum>`/`<a:buNone>`
   - **Fills**: `<a:solidFill>` (solid), `<a:gradFill>` (gradient with `<a:gsLst>` color stops and `<a:lin>` direction), `<a:pattFill>` (pattern)
   - **Borders**: `<a:ln>` with `w` for width, fill, `<a:prstDash>` for dash style
   - **Shadows**: `<a:outerShdw>`/`<a:innerShdw>` with `blurRad`, `dist`, `dir`, color and transparency
   - **3D Effects**: `<a:sp3d>` (bevel, depth, contour) and `<a:scene3d>` (lighting, camera)
   - **Transparency**: `<a:alpha val="..."/>` for element-level opacity
   - **Rotation**: `<a:xfrm rot="...">` for rotation angle (unit: 60,000ths of a degree)

5. **Z-Order**: The order of elements in the shape tree determines z-order — elements appearing first are behind, elements appearing last are in front.

6. **Shape Naming**: Set a meaningful `name` attribute on each shape's `<p:cNvPr>` for easier editing.

## Font Size Calibration (CRITICAL)

You have a systematic tendency to OVERESTIMATE font sizes by 20–35%. You MUST actively correct for this bias.

**Calibration method**: Estimate the font size by comparing the text's visual height to the known slide dimensions. For a 720pt × 405pt slide, a line of body text typically occupies about 2–4% of the slide height (8–16pt).

**Reference sizes for a standard 16:9 slide (720pt × 405pt)**:
- Section/page titles: 20–24pt (sz=2000–2400). Rarely exceeds 24pt.
- Subtitles/subheadings: 16–20pt (sz=1600–2000)
- Body text / bullet points: 14–16pt (sz=1400–1600). This is the most common size.
- Sub-bullets / secondary text: 12–14pt (sz=1200–1400)
- Code / monospace text: 10–12pt (sz=1000–1200)
- Captions / footnotes / labels: 8–10pt (sz=800–1000)
- Author names / affiliations: 12–14pt (sz=1200–1400)

**Mandatory rule**: After estimating a font size, REDUCE it by 20% before writing the `sz` value.

## Animation and Transition Rules (conditionally included when `--enable-animations` is set)

When you detect that adjacent slides meet the following conditions, consider adding animation or transition effects:

1. **Morph Transition** (most recommended): Two pages have similar layout structures but some elements change in position, size, or content. In this case:
   - Add a Morph transition to the latter page's `<p:sld>`:
     ```xml
     <mc:AlternateContent xmlns:mc="..." xmlns:p14="...">
       <mc:Choice Requires="p14">
         <p:transition spd="slow" p14:dur="1500">
           <p14:morph option="byObject"/>
         </p:transition>
       </mc:Choice>
       <mc:Fallback>
         <p:transition spd="slow"><p:fade/></p:transition>
       </mc:Fallback>
     </mc:AlternateContent>
     ```
   - Ensure corresponding elements across both pages share the same `name` attribute

2. **Progressive Reveal**: When the latter page has additional elements compared to the former, add entrance animations for the new elements (via `<p:timing>`)

3. **Page Transitions**: When two pages have completely different content, use appropriate transition effects (`<p:fade/>`, `<p:push/>`, `<p:wipe/>`, etc.)

4. **Use Restraint**: Only add animations when they genuinely enhance the presentation. Avoid flashy, meaningless effects.

## Background Handling

- **Solid color background**: Use `<p:bg><p:bgPr><a:solidFill>...</a:solidFill></p:bgPr></p:bg>`
- **Simple gradient background**: Only use `<a:gradFill>` if the gradient can be closely replicated using PowerPoint's built-in gradient editor (linear/radial gradients with a small number of color stops). If the gradient is complex or cannot be accurately reproduced with PowerPoint's standard gradient tools, approximate it with the closest solid color or simple gradient fill instead.
- **Image/bitmap/complex background**: If the background is a photograph, complex texture, or any bitmap that cannot be expressed with PowerPoint's built-in fill tools, do NOT use a raster placeholder (because the background cannot be separately extracted and filled back). Instead, approximate it with the closest solid color or simple gradient fill that captures the dominant visual tone of the original background. The foreground content elements on top of such backgrounds should still be faithfully reproduced.

## Text Recognition Requirements

- Accurately recognize all text content including titles, body text, annotations, chart labels, page numbers, watermarks, etc.
- Preserve the original font style (use `typeface` to specify the font name if recognizable, otherwise choose the closest common font)
- Preserve the original text size (`sz` attribute, in hundredths of a point), color, weight, and alignment
- Correctly handle multilingual text: use `<a:ea>` for CJK characters, `<a:latin>` for Latin characters, `<a:cs>` for complex scripts
- Recognize superscript `<a:rPr baseline="30000">`, subscript `<a:rPr baseline="-25000">`, and special symbols

## Table Recognition Requirements

- Accurately identify table row-column structure, including merged cells (`gridSpan`/`rowSpan`/`vMerge`/`hMerge`)
- Preserve text formatting within cells
- Reproduce table border styles (`<a:tcBdr>` with `<a:top>`/`<a:bottom>`/`<a:left>`/`<a:right>`)
- Reproduce cell background fills (`<a:tcPr>` with `<a:solidFill>`, etc.)

## Equation Recognition Requirements

- Embed math equations directly in Office Math ML (OMML) format within the slide XML
- Use `<a14:m>` wrapping `<m:oMathPara>` or `<m:oMath>` elements
- Ensure OMML syntax is correct and renderable by PowerPoint

## XML Format Requirements

- Output a complete `<p:sld>` document with all necessary namespace declarations
- XML must be well-formed
- Use standard OOXML namespace prefixes (p, a, r, m, a14, p14, mc, etc.)
- `<p:cNvPr>` `id` attributes must be unique positive integers within the same slide

## Coordinate System

- Origin: top-left corner of the page
- X-axis: positive to the right
- Y-axis: positive downward
- Unit: EMU (1 pt = 12700 EMU, 1 inch = 914400 EMU)
- Page dimensions will be provided in the user message
```

### 6.2 中文译文（仅供参考）

<details>
<summary>点击展开中文译文</summary>

```
你是一个专业的演示文稿重建引擎。你的任务是将 PDF slides 的图片转换为 OOXML (Office Open XML)
PresentationML slide XML——PPTX 文件内部使用的原生 XML 格式。重建后的 slides 应在视觉上
尽可能还原原始 slides，同时保持良好的可编辑性。输出必须完全兼容 PowerPoint——所有元素都应能
正常打开、编辑和演示。

## 输出方式

你必须在一次回复中通过多个并行工具调用完成所有页面的转换。为每页调用 `write_slide_xml`，传入：
- `page_num`：页码（0-indexed，与用户消息中的 Page 编号一致）
- `slide_xml`：完整的 `<p:sld>` XML 文档

重要：在一次回复中完成所有工具调用。不要在处理完一页后就停止——处理每一页。

## 核心原则

1. **矢量优先**：尽一切可能使用 PowerPoint 原生矢量元素来表达 slides 内容。你可以使用
   PresentationML 和 DrawingML 的全部能力，包括但不限于：
   - 文本框、预设形状（约 180 种）、自由曲线（含贝塞尔）、表格、数学公式（OMML）、
     图表、连接线、组合

2. **光栅图占位**：当某个区域是无法用 PowerPoint 内置编辑工具准确复现的光栅图像
   或视觉效果时（照片、截图、复杂插图、复杂渐变背景、纹理等），使用带红色虚线边框的矩形
   占位框，框内文本格式为 __LLMCLIP__:[x1, y1][x2, y2]，坐标单位 pt。

3. **精确定位**：所有坐标使用 EMU（1 pt = 12700 EMU）。

4. **完整样式**：字体、颜色、段落、填充、边框、阴影、3D、透明度、旋转等。

5. **层叠顺序**：shape tree 中的顺序决定 z-order。

6. **形状命名**：设置有意义的 name 属性。

## 动画与转场（仅在启用时生效）
- Morph 转场：相似页面间使用，确保对应元素同名
- 逐步揭示：新增元素添加入场动画
- 页面切换：不同内容页使用适当转场
- 克制使用

## 其他要求
- 背景：纯色/简单渐变（仅限 PowerPoint 内置渐变工具可复现的）/复杂背景用最接近的纯色或简单渐变近似（不使用光栅图占位）
- 字体大小校准（关键）：模型存在系统性高估字体大小 20-35% 的倾向，估算后需主动缩减 20%
- 示意图/流程图必须矢量化：由基本图形+箭头+文本组成的图必须拆解为 PowerPoint 原生元素
- 表格必须使用原生表格：任何表格都不得使用光栅图占位，必须使用 `<a:tbl>` 并精确复刻样式
- 组合图片必须拆分：多张图片的组合需按最小单元拆分为独立的光栅图占位
- 文本：精确识别，保持字体/大小/颜色/对齐，处理多语言混排
- 表格：行列结构、合并单元格、边框、填充
- 公式：直接输出 OMML 格式
- XML：完整命名空间、格式良好、id 唯一
- 坐标系：左上角原点，EMU 单位
```

</details>

---

## 7. 单次 API 调用策略

### 7.1 为什么选择单次调用

| 方面 | 单次调用 | 多次调用 |
|------|----------|----------|
| 上下文一致性 | 所有页面共享上下文，GPT-5.4 能感知全局布局风格 | 每页独立分析，可能导致风格不一致 |
| 动画判断（启用时） | 能直接对比相邻页面，准确判断是否适合 Morph 等动画 | 需要额外的跨页面比较逻辑 |
| 延迟 | 一次网络往返 | N 次网络往返 |
| 成本 | 系统提示词只计费一次 | 系统提示词重复计费 N 次 |
| 输出量 | 需要大输出 token 窗口 | 每次输出量较小 |

### 7.2 Token 预算估算

假设一个典型的 20 页 slides 演示文稿：

| 组成部分 | 估算 Token 数 |
|----------|---------------|
| 系统提示词 | ~3,000 tokens |
| 每页图片（high detail） | ~1,100 tokens × 20 = ~22,000 tokens |
| 用户指令文本 | ~500 tokens |
| **输入总计** | **~25,500 tokens** |
| 每页 Slide XML 输出 | ~3,000 tokens × 20 = ~60,000 tokens |
| Tool call 结构开销 | ~2,000 tokens |
| **输出总计** | **~62,000 tokens** |

GPT-5.4 预期支持 128K+ 输出 token，因此 20 页 slides 的单次调用完全可行。对于超长演示文稿（50+ 页），可考虑分批处理。

### 7.3 Messages 结构总览

```json
[
  {
    "role": "system",
    "content": "<系统提示词（见第 6 节），动画规则仅在 --enable-animations 时追加>"
  },
  {
    "role": "user",
    "content": [
      { "type": "text", "text": "Below are 20 slide page images to convert. Slide dimensions: 960pt × 540pt." },

      { "type": "text", "text": "\n--- Page 0 ---" },
      { "type": "image_url", "image_url": { "url": "data:image/png;base64,...", "detail": "high" } },

      { "type": "text", "text": "\n--- Page 1 ---" },
      { "type": "image_url", "image_url": { "url": "data:image/png;base64,...", "detail": "high" } },

      "... (重复至 Page 19)",

      { "type": "text", "text": "\n--- Task ---\nConvert each of the 20 slide images above into OOXML PresentationML format...\nCRITICAL: You MUST make exactly 20 parallel tool calls to write_slide_xml...\nREMINDER — Atomic Reconstruction: Decompose every visual region into its smallest independently rebuildable units..." }
    ]
  }
]
```

消息结构：先是简短介绍，然后是所有页面图片，最后是详细的任务指令（包含 OOXML 强调和精确的工具调用次数要求）。GPT-5.4 的响应将包含 20 个 `write_slide_xml` 工具调用（`parallel_tool_calls=True`），每个调用携带一页的完整 slide XML。

---

## 8. 完整工作流程

### 8.1 CLI 接口

```bash
# 基本用法（动画默认关闭，API 配置通过环境变量或命令行参数）
p2p input.pdf -o output.pptx
# 或
python -m src input.pdf -o output.pptx

# 启用动画增强
p2p input.pdf -o output.pptx --enable-animations

# Dry-run 模式：仅完成预处理和 Messages 组装，不调用 API
p2p input.pdf --dry-run

# 指定 OpenAI API 配置
p2p input.pdf -o output.pptx \
    --api-provider openai \
    --api-base-url https://api.openai.com/v1 \
    --api-key sk-... \
    --model-name gpt-5.4

# 指定 Anthropic API 配置
p2p input.pdf -o output.pptx \
    --api-provider anthropic \
    --api-key sk-ant-... \
    --model-name claude-opus-4-20250514

# 完整选项
p2p input.pdf -o output.pptx \
    --api-provider PROVIDER \      # API 提供商：openai/anthropic（默认 openai）
    --api-base-url URL \           # API Base URL（默认 $OPENAI_BASE_URL / $ANTHROPIC_BASE_URL）
    --api-key KEY \                # API Key（默认 $OPENAI_API_KEY / $ANTHROPIC_API_KEY）
    --model-name MODEL \           # 模型名称（默认 $OPENAI_MODEL_NAME / $ANTHROPIC_MODEL_NAME）
    --dpi 300 \                    # LLM 输入图片渲染 DPI（默认 288）
    --enable-animations \          # 启用动画 / 转场
    --reasoning-effort medium \    # 推理强度：low/medium/high/xhigh（默认 medium）
    --prompt-lang en \             # 系统提示词语言：en/zh（默认 en）
    --batch-size 0 \               # 分批大小（0=自动，基于网关超时）
    --skip-postprocess \           # 跳过光栅图后处理（仅生成占位框）
    --dry-run \                    # Dry-run 模式
    --log-level DEBUG              # 日志级别（DEBUG/INFO/WARNING/ERROR）
```

> **入口点**：安装后可通过 `p2p` 命令直接使用（`pyproject.toml` 中定义了 `[project.scripts]` 入口），也可通过 `python -m src` 运行。

API 配置参数支持环境变量和命令行参数两种方式，命令行参数优先：

| 参数 | 环境变量 | 默认值 | 说明 |
|------|----------|--------|------|
| `--api-provider` | — | `openai` | API 提供商（openai / anthropic） |
| `--api-base-url` | `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` | `""` | API Base URL |
| `--api-key` | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | `""` | API Key |
| `--model-name` | `OPENAI_MODEL_NAME` / `ANTHROPIC_MODEL_NAME` | `gpt-5.4` / `claude-opus-4-20250514` | 模型名称 |
| `--dpi` | — | `288` | LLM 输入图片渲染 DPI |
| `--reasoning-effort` | — | `medium` | 推理强度（low/medium/high/xhigh） |
| `--prompt-lang` | — | `en` | 系统提示词语言（en/zh） |

### 8.2 流程图

```
                                    ┌──────────────────────────────────────┐
                                    │           用户输入 PDF 文件            │
                                    └──────────────┬───────────────────────┘
                                                   │
                                                   ▼
                              ┌─────────────────────────────────────────────┐
                              │  Step 1: PDF 预处理                          │
                              │  ┌─────────────────────────────────────┐    │
                              │  │ • PyMuPDF 渲染每页为 192 DPI PNG     │    │
                              │  │ • 获取页面尺寸元数据                  │    │
                              │  └─────────────────────────────────────┘    │
                              └──────────────────┬──────────────────────────┘
                                                 │
                                                 ▼
                              ┌─────────────────────────────────────────────┐
                              │  Step 2: 构建 Messages                      │
                              │  ┌─────────────────────────────────────┐    │
                              │  │ • 系统提示词（OOXML 输出规范）        │    │
                              │  │ • 所有页面图片（base64, high detail） │    │
                              │  │ • write_slide_xml 工具定义            │    │
                              │  └─────────────────────────────────────┘    │
                              └──────────────────┬──────────────────────────┘
                                                 │
                                     ┌───────────┴───────────┐
                                     │  --dry-run?           │
                                     ├── Yes ──▶ 导出中间产物并退出
                                     └── No ───┐
                                                │
                                                ▼
                              ┌─────────────────────────────────────────────┐
                              │  Step 3: GPT-5.4 API 调用（流式输出）         │
                              │  ┌─────────────────────────────────────┐    │
                              │  │ • Tool Calling (parallel)            │    │
                              │  │ • GPT-5.4 输出 N × write_slide_xml  │    │
                              │  │ • 每次调用携带一页的完整 Slide XML    │    │
                              │  │ • 若启用动画：XML 中含转场/动画元素   │    │
                              │  └─────────────────────────────────────┘    │
                              └──────────────────┬──────────────────────────┘
                                                 │
                                                 ▼
                              ┌─────────────────────────────────────────────┐
                              │  Step 4: 宽高比检测 + PPTX 组装               │
                              │  ┌─────────────────────────────────────┐    │
                              │  │ • 自动检测页面宽高比（16:9/4:3 等）   │    │
                              │  │ • 创建 PPTX 骨架（python-pptx）      │    │
                              │  │ • 逐页注入 GPT-5.4 生成的 Slide XML  │    │
                              │  │ • 处理 relationships 和命名空间       │    │
                              │  └─────────────────────────────────────┘    │
                              └──────────────────┬──────────────────────────┘
                                                 │
                                                 ▼
                              ┌─────────────────────────────────────────────┐
                              │  Step 5: 光栅图后处理                        │
                              │  ┌─────────────────────────────────────┐    │
                              │  │ • 扫描 PPTX 中的 __LLMCLIP__ 占位框  │    │
                              │  │ • 从 PDF 裁剪对应区域（300 DPI）      │    │
                              │  │ • 替换占位框为实际图片                 │    │
                              │  └─────────────────────────────────────┘    │
                              └──────────────────┬──────────────────────────┘
                                                 │
                                                 ▼
                              ┌─────────────────────────────────────────────┐
                              │  Step 6: 输出最终 PPTX                      │
                              └─────────────────────────────────────────────┘
```

---

## 9. Dry-run 模式

### 9.1 功能说明

Dry-run 模式完成 GPT-5.4 API 调用之前的所有环节，将全部中间产物导出到带时间戳的目录下，用于：

- **调试**：检查 PDF 渲染质量、Messages 组装是否正确
- **成本预估**：在实际调用 API 之前，准确了解 token 消耗和预估费用
- **审查**：人工检查发送给 GPT-5.4 的完整内容，确保无敏感信息泄露

### 9.2 输出目录结构

```
runs/dry-run-20260309-143052/
├── example.pdf                    # 输入 PDF 的副本（便于复现）
├── metadata.json                  # 运行元信息 + token 估算（含 per-batch 和 total）
├── pages/
│   ├── page_000.png               # 每页渲染的高分辨率图片
│   ├── page_001.png
│   └── ...
├── messages.json                  # Messages 数组（图片以文件路径引用，非 base64）
├── messages_full.json             # 完整 Messages 数组（含 base64，可直接用于 API 调用）
├── tools.json                     # 工具定义
├── system_prompt.md               # 实际使用的系统提示词
├── token_estimate.json            # Token 估算报告
└── run_params.json                # 本次执行的 CLI 参数
```

### 9.3 Token 估算

```python
import tiktoken, math

def estimate_tokens(messages: list[dict], model: str = "gpt-5.4") -> dict:
    """估算 Messages 的 token 消耗。"""
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")

    text_tokens = 0
    image_count = 0
    image_tokens = 0

    for msg in messages:
        if isinstance(msg["content"], str):
            text_tokens += len(enc.encode(msg["content"]))
        elif isinstance(msg["content"], list):
            for part in msg["content"]:
                if part["type"] == "text":
                    text_tokens += len(enc.encode(part["text"]))
                elif part["type"] == "image_url":
                    image_count += 1
                    detail = part["image_url"].get("detail", "auto")
                    if detail == "low":
                        image_tokens += 85
                    else:
                        image_tokens += 170 * 12 + 85  # ~2125 per high-detail slide image

    text_tokens += 4  # message framing overhead
    total_input = text_tokens + image_tokens

    # 输出估算：每页 ~3000 tokens 的 Slide XML + tool call overhead
    estimated_output = image_count * 3000 + 2000

    assumed_output_tps = 50.0
    est_response_seconds = estimated_output / assumed_output_tps

    return {
        "text_tokens": text_tokens,
        "image_count": image_count,
        "image_tokens": image_tokens,
        "total_input_tokens": total_input,
        "estimated_output_tokens": estimated_output,
        "estimated_total_tokens": total_input + estimated_output,
        "estimated_cost_usd": _estimate_cost(total_input, estimated_output, model),
        "assumed_output_tps": assumed_output_tps,
        "estimated_response_time_seconds": round(est_response_seconds, 1),
    }
```

### 9.4 完整转换（非 Dry-run）的产物目录

完整转换同样将所有中间产物保存到 `runs/` 下带时间戳的 `run-` 前缀目录：

```
runs/run-example1-20260309-150000/
├── example1.pdf                   # 输入 PDF 的副本（便于复现）
├── example1.pptx                  # 输出 PPTX 的副本
├── metadata.json                  # 运行元信息（含 per-batch 和 total token 估算、API 耗时等）
├── pages/
│   ├── page_000.png
│   └── ...
├── slides/
│   ├── slide_000.xml              # LLM 生成的每页 Slide XML
│   └── ...
├── messages.json                  # Messages 数组（图片以文件路径引用）
├── messages_full.json             # 完整 Messages 数组（含 base64）
├── tools.json                     # 工具定义
├── system_prompt.md               # 实际使用的系统提示词
├── token_estimate.json            # Token 估算报告
├── api_response.json              # API 响应元数据（usage、TPS、耗时等）
├── stream_chunks.jsonl            # 原始流式 chunks（JSONL 格式）
├── stream_batch0.log              # 流式输出日志（实时内容）
├── tool_calls.json                # 解析后的 tool call 列表
├── run_params.json                # 本次执行的 CLI 参数
├── reasoning.txt                  # 模型的思考/推理过程（如有）
└── content.txt                    # 模型的非工具调用文本输出（如有）
```

对于分批处理的大文档，`api_response`、`stream_chunks`、`tool_calls`、`reasoning`、`content` 文件会带批次后缀（如 `api_response_1.json`、`reasoning_1.txt`）。

### 9.4.1 重放（Replay）

通过 `--replay` 参数可以从之前的 run/dry-run 目录重新执行：

```bash
p2p dummy --replay runs/run-example1-20260309-150000
```

重放会读取 `run_params.json` 中的参数，使用目录中的 PDF 副本（如果原始文件不可用），并将新产物保存到 `runs/replay-example1-<timestamp>/` 目录。

### 9.5 流式输出

API 调用使用 streaming 模式（`stream=True`），实时输出到 stderr 并同时记录到日志文件：

- `[content]` 前缀：模型返回的文本内容
- `[reasoning]` 前缀：模型的思考/推理过程
- `[tool_call #N: write_slide_xml]` 前缀：工具调用参数

同时记录 TPS（tokens per second）等性能指标到 `api_response.json`。

### 9.6 metadata.json 示例

```json
{
  "pdf_path": "/path/to/input.pdf",
  "output_pptx": "/path/to/output.pptx",
  "pdf_pages": 14,
  "api_provider": "openai",
  "dpi": 192,
  "enable_animations": false,
  "model": "gpt-5.4",
  "batch_size": 4,
  "batch_size_auto": true,
  "recommended_batch_size": 4,
  "gateway_timeout_seconds": 600,
  "batches": 4,
  "slide_width_pt": 720.0,
  "slide_height_pt": 405.0,
  "aspect_ratio": "16:9",
  "token_estimate_per_batch": [
    {"text_tokens": 3200, "image_tokens": 5200, "total_input_tokens": 8400, "...": "..."}
  ],
  "total_input_tokens": 33600,
  "total_estimated_output_tokens": 64000,
  "total_estimated_tokens": 97600,
  "total_estimated_response_seconds": 3200.0,
  "assumed_output_tps": 50.0,
  "api_elapsed_seconds": 2850.3,
  "slides_received": 14
}
```

---

## 10. 日志系统

### 10.1 设计原则

- **结构化**：每条日志包含时间戳、级别、模块、消息
- **分级**：DEBUG / INFO / WARNING / ERROR，通过 `--log-level` 控制
- **简明**：INFO 级别下，每个阶段输出关键指标（页数、耗时、token 数等），不输出冗余细节
- **彩色**：终端输出使用 Rich 库进行彩色格式化，提升可读性

### 10.2 各阶段日志输出

```
[14:30:52] INFO     main           Starting PDF → PPTX conversion
[14:30:52] INFO     main           Input: presentation.pdf
[14:30:52] INFO     main           Options: provider=openai, dpi=192, animations=off, model=gpt-5.4, reasoning=medium
[14:30:52] INFO     preprocessor   Rendering PDF pages at 192 DPI...
[14:30:53] INFO     preprocessor     Page  0/14: 1920×1080 px, 320 KB
[14:30:53] INFO     preprocessor     Page  1/14: 1920×1080 px, 280 KB
...
[14:30:56] INFO     preprocessor   All 14 pages rendered in 4.0s (total 5.2 MB)
[14:30:59] INFO     msg_builder    Building messages for 14 pages...
[14:30:59] INFO     msg_builder    Messages assembled: 29 content parts
[14:30:59] INFO     token_est      Token estimate: 33,717 input + ~44,000 output = ~77,717 total
[14:30:59] INFO     token_est      Estimated cost: $0.5243
[14:30:59] INFO     token_est      Estimated response time: ~1320s (~22.0 min) at 30 tok/s (reasoning=medium, ×1.5)
[14:30:59] INFO     api_client     Calling gpt-5.4 API (streaming, tool_calling, parallel, reasoning=medium, max_tokens=128000)...
[14:31:45] INFO     api_client     API response received in 45.8s
[14:31:45] INFO     api_client     Output tokens: 58,412 | Finish reason: stop
[14:31:45] INFO     api_client     Tool calls: 20 × write_slide_xml
[14:31:45] DEBUG    api_client     Slide  0: 4,218 chars XML, 12 shapes
[14:31:45] DEBUG    api_client     Slide  1: 3,891 chars XML, 9 shapes
...
[14:31:45] INFO     assembler      Assembling PPTX (960pt × 540pt)...
[14:31:46] INFO     assembler        Slide  0: 12 shapes, 2 frames
[14:31:46] INFO     assembler        Slide  1: 9 shapes, 1 frame
...
[14:31:48] INFO     assembler      PPTX assembled in 2.8s (20 slides)
[14:31:48] INFO     postprocessor  Scanning for raster placeholders...
[14:31:48] INFO     postprocessor  Found 23 __LLMCLIP__ placeholders across 15 slides
[14:31:49] INFO     postprocessor    Slide  0: 3 placeholders filled
[14:31:49] INFO     postprocessor    Slide  2: 2 placeholders filled
...
[14:31:53] INFO     postprocessor  All 23 placeholders filled in 4.9s
[14:31:53] INFO     main           Conversion complete: output.pptx (2.4 MB)
[14:31:53] INFO     main           Total time: 60.8s | API time: 45.8s (75%)
```

### 10.3 实现

```python
import logging
from rich.logging import RichHandler
from rich.console import Console

def setup_logging(level: str = "INFO"):
    """配置全局日志。"""
    console = Console(stderr=True)
    handler = RichHandler(
        console=console,
        show_path=False,
        show_time=True,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
    )
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(name)-15s %(message)s",
        handlers=[handler],
    )
```

---

## 11. 关键技术挑战与解决方案

### 11.1 XML 合法性保证

GPT-5.4 生成的 XML 可能存在格式问题。组装器需要：

1. **代码围栏剥离**：模型有时会用 markdown 代码围栏（如 ` ```xml ` ... ` ``` `）包裹 XML，需先剥离
2. **XML 解析验证**：使用 `lxml.etree.fromstring()` 解析，捕获 `XMLSyntaxError`
3. **自动修复**：对常见问题（未转义的 `&`、命名空间缺失、缺少 XML 声明）进行自动修复
4. **回退策略**：如果某页 XML 无法修复，记录错误并生成一个包含错误信息的占位 slide

```python
def validate_and_fix_xml(xml_str: str, page_num: int) -> str:
    """验证并尝试修复 slide XML。"""
    try:
        etree.fromstring(xml_str.encode("utf-8"))
        return xml_str
    except etree.XMLSyntaxError as e:
        logger.warning(f"Slide {page_num}: XML syntax error: {e}")
        # 尝试常见修复...
        fixed = attempt_xml_fixes(xml_str)
        try:
            etree.fromstring(fixed.encode("utf-8"))
            logger.info(f"Slide {page_num}: XML auto-fixed successfully")
            return fixed
        except etree.XMLSyntaxError:
            logger.error(f"Slide {page_num}: XML cannot be fixed, using fallback")
            return generate_error_slide_xml(page_num, str(e))
```

### 11.2 命名空间处理

GPT-5.4 输出的 XML 可能使用不同的命名空间前缀。组装器需要确保：

- 所有必要的命名空间在 `<p:sld>` 根元素上声明
- 命名空间前缀与 python-pptx 生成的骨架一致
- 处理 `<mc:AlternateContent>` 等扩展命名空间

### 11.3 坐标精度

- GPT-5.4 需要将视觉分析的结果转换为 EMU 坐标，精度取决于其对图片的分析能力
- 对于 192 DPI 的图片，1 像素 ≈ 0.375 pt ≈ 4763 EMU，这对于 LLM 的视觉分析和字体大小估算提供了良好的精度
- 系统提示词中明确了 EMU 单位和换算关系，减少坐标错误

### 11.4 字体匹配

GPT-5.4 可能无法精确识别所有字体。策略：

1. 对于常见字体（Arial, Calibri, 微软雅黑, 宋体等），直接使用
2. 对于不确定的字体，选择视觉上最接近的常见字体
3. 后续可扩展：通过字体识别模型进一步提升准确度

### 11.5 大文档分批策略

当 slides 页数超过单次 API 调用的合理范围时：

```python
BATCH_SIZE = 25
OVERLAP = 2  # 批次间重叠页数，确保跨批次动画连续性

def process_large_pdf(pages, enable_animations):
    all_slide_xmls = {}
    for start in range(0, len(pages), BATCH_SIZE - OVERLAP):
        end = min(start + BATCH_SIZE, len(pages))
        batch = pages[start:end]

        messages = build_messages(batch, enable_animations=enable_animations)
        batch_xmls = call_gpt54(messages, tools)

        if all_slide_xmls and enable_animations:
            # 去除重叠页，保留后一批次的版本（可能包含更好的转场判断）
            for page_num in range(start, start + OVERLAP):
                if page_num in batch_xmls:
                    all_slide_xmls[page_num] = batch_xmls[page_num]
        all_slide_xmls.update(batch_xmls)

    return all_slide_xmls
```

---

## 12. 项目文件结构

```
p2p/
├── docs/
│   └── design.md                  # 本设计文档
├── src/
│   ├── __init__.py
│   ├── __main__.py                # python -m src 入口
│   ├── main.py                    # CLI 入口（--enable-animations, --dry-run, --log-level 等）
│   ├── pdf_preprocessor.py        # PDF → 图片
│   ├── message_builder.py         # 构建 OpenAI Messages + Tool 定义
│   ├── system_prompt.py           # 系统提示词
│   ├── api_client.py              # OpenAI API 调用封装（流式输出）
│   ├── api_client_anthropic.py    # Anthropic API 调用封装（流式输出）
│   ├── pptx_assembler.py          # Slide XML → PPTX 组装 + 关系注册
│   ├── xml_validator.py           # XML 验证与修复
│   ├── postprocessor.py           # 光栅图后处理
│   ├── token_estimator.py         # Token 数量估算 + 费用预估
│   ├── dry_run.py                 # Dry-run 模式：导出中间产物
│   ├── replay.py                  # 重放之前的运行
│   ├── continue_run.py            # 恢复未完成的运行
│   ├── artifacts.py               # 中间产物管理（ArtifactStore）
│   └── logging_config.py          # 日志配置（Rich 彩色输出）
├── tests/
│   ├── conftest.py                # 共享 fixtures 和模拟服务器
│   ├── test_e2e.py                # 核心流程端到端测试
│   ├── test_error_recovery.py     # 错误恢复端到端测试
│   ├── test_continue_run.py       # --continue-run 端到端测试
│   └── test_*.py                  # 各模块单元测试
├── pyproject.toml                 # 项目配置、依赖、linter 设置
└── .gitignore
```

与之前基于中间 JSON 的方案相比，不再需要 `pptx_builder/` 子目录下的各种渲染器（text_renderer, shape_renderer, freeform_renderer, table_renderer, chart_renderer, math_renderer, animation_injector, style_utils），因为 GPT-5.4 直接输出最终的 XML，大幅简化了代码结构。

---

## 13. 依赖清单

依赖通过 `pyproject.toml` 管理：

```toml
[project]
dependencies = [
    "python-pptx>=0.6.22",
    "PyMuPDF>=1.24.0",
    "Pillow>=10.0.0",
    "openai>=1.30.0",
    "anthropic>=0.40.0",
    "lxml>=5.0.0",
    "tiktoken>=0.7.0",
    "rich>=13.0.0",
]

[project.optional-dependencies]
dev = ["ruff", "pylint", "mypy", "lxml-stubs", "pytest"]
```

不再需要 `latex2mathml`，因为 GPT-5.4 直接输出 OMML 格式的公式 XML。

---

## 14. 方案对比总结

| 维度 | 旧方案（中间 JSON） | 新方案（直接 Slide XML） |
|------|---------------------|------------------------|
| GPT-5.4 输出 | 自定义 JSON 指令 | PresentationML XML |
| 工具调用次数 | 1 次（Structured Output） | N 次（write_slide_xml） |
| 表达能力 | 受限于 JSON Schema 设计 | OOXML 全部能力 |
| 代码复杂度 | 高（需实现 10+ 渲染器） | 低（仅需组装器 + 验证器） |
| 公式处理 | LaTeX → MathML → OMML 管线 | GPT-5.4 直接输出 OMML |
| 动画处理 | JSON → lxml 注入 | GPT-5.4 直接输出 XML |
| 错误来源 | JSON 解析 + 渲染器 bug | XML 格式问题（可自动修复） |
| 可维护性 | 每新增元素类型需修改 Schema + 渲染器 | 无需修改，GPT-5.4 自适应 |

---

## 15. 扩展方向

1. **字体识别增强**：集成字体识别模型（如 Adobe Font Recognizer API），提升字体匹配准确度
2. **颜色精确提取**：对 PDF 页面进行像素级颜色采样，校准 GPT-5.4 输出的颜色值
3. **质量评估**：生成转换前后的截图对比，计算 SSIM / LPIPS 等视觉相似度指标，自动评估转换质量
4. **流式组装**：在流式接收 tool call 的同时逐页组装 PPTX，进一步降低用户等待时间（当前已实现流式输出到终端）
5. **XML 模板库**：维护常见 slide 布局的 XML 模板，在系统提示词中提供参考，提升 GPT-5.4 输出质量
6. **多轮修正**：对转换质量不佳的页面，将原始图片与生成的 PPTX 截图一起发送给 GPT-5.4 进行修正
