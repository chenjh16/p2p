from __future__ import annotations

import re
from io import BytesIO

import fitz  # PyMuPDF
from pptx import Presentation

from .logging_config import get_logger

logger = get_logger("postprocessor")

_CLIP_PATTERN = re.compile(
    r"__LLMCLIP__:\[([0-9.]+),\s*([0-9.]+)\]\[([0-9.]+),\s*([0-9.]+)\]"
)


def postprocess_raster_fills(
    pptx_path: str,
    pdf_path: str,
    output_path: str,
    dpi: int = 300,
) -> None:
    """Scan PPTX for __LLMCLIP__ placeholders and fill them with cropped PDF regions."""
    prs = Presentation(pptx_path)
    doc = fitz.open(pdf_path)
    fill_count = 0

    logger.info("Scanning for raster placeholders...")

    for slide_idx, slide in enumerate(prs.slides):
        if slide_idx >= doc.page_count:
            logger.warning(
                "Slide %d has no corresponding PDF page, skipping", slide_idx
            )
            continue

        page = doc[slide_idx]
        shapes_to_replace: list[tuple] = []

        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            text = shape.text_frame.text.strip()
            match = _CLIP_PATTERN.search(text)
            if not match:
                continue

            x1 = float(match.group(1))
            y1 = float(match.group(2))
            x2 = float(match.group(3))
            y2 = float(match.group(4))

            clip_rect = fitz.Rect(x1, y1, x2, y2)
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, clip=clip_rect)
            img_bytes = pix.tobytes("png")

            shapes_to_replace.append((shape, img_bytes))

        for shape, img_bytes in shapes_to_replace:
            left, top = shape.left, shape.top
            width, height = shape.width, shape.height

            slide.shapes.add_picture(
                BytesIO(img_bytes), left, top, width, height
            )

            sp = shape._element
            sp.getparent().remove(sp)
            fill_count += 1

        if shapes_to_replace:
            logger.info(
                "  Slide %3d: %d placeholders filled",
                slide_idx,
                len(shapes_to_replace),
            )

    doc.close()
    prs.save(output_path)
    logger.info("Post-processing complete: %d raster images filled", fill_count)
