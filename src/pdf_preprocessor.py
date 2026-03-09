from __future__ import annotations

import fitz  # PyMuPDF

from .logging_config import get_logger

logger = get_logger("preprocessor")


def pdf_to_images(
    pdf_path: str, dpi: int = 300
) -> list[tuple[bytes, dict]]:
    """Render each PDF page to a high-resolution PNG image.

    Returns a list of (png_bytes, metadata) tuples.
    """
    doc = fitz.open(pdf_path)
    pages: list[tuple[bytes, dict]] = []
    total_bytes = 0

    logger.info("Rendering PDF pages at %d DPI...", dpi)

    for page_num in range(doc.page_count):
        page = doc[page_num]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        total_bytes += len(img_bytes)

        metadata = {
            "page_num": page_num,
            "width_pt": page.rect.width,
            "height_pt": page.rect.height,
            "width_px": pix.width,
            "height_px": pix.height,
        }
        pages.append((img_bytes, metadata))
        logger.info(
            "  Page %3d/%d: %d×%d px, %.1f KB",
            page_num,
            doc.page_count,
            pix.width,
            pix.height,
            len(img_bytes) / 1024,
        )

    doc.close()
    logger.info(
        "All %d pages rendered (total %.1f MB)",
        len(pages),
        total_bytes / (1024 * 1024),
    )
    return pages
