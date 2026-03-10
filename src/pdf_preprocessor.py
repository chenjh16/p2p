"""Render PDF pages to PNG images for LLM input, or load images from a folder."""

from __future__ import annotations

import os

import fitz  # PyMuPDF
from PIL import Image

from .logging_config import get_logger

logger = get_logger("preprocessor")

STANDARD_ASPECT_RATIOS: list[tuple[str, float, float, float]] = [
    ("16:9", 16 / 9, 720, 405),
    ("4:3", 4 / 3, 720, 540),
    ("16:10", 16 / 10, 720, 450),
    ("A4 landscape", 297 / 210, 720, 509),
]


def snap_slide_dimensions(width_pt: float, height_pt: float) -> tuple[float, float, str]:
    """Snap PDF page dimensions to the closest standard PowerPoint aspect ratio.

    Returns (snapped_width_pt, snapped_height_pt, ratio_label).
    """
    if height_pt == 0:
        return width_pt, height_pt, "unknown"

    page_ratio = width_pt / height_pt

    best_label = "custom"
    best_diff = float("inf")
    best_w = width_pt
    best_h = height_pt

    for label, ratio, std_w, std_h in STANDARD_ASPECT_RATIOS:
        diff = abs(page_ratio - ratio)
        if diff < best_diff:
            best_diff = diff
            best_label = label
            best_w = std_w
            best_h = std_h

    tolerance = 0.05
    if best_diff > tolerance:
        logger.info(
            "Page ratio %.3f does not match any standard ratio (closest: %s, diff=%.3f). Using original dimensions.",
            page_ratio, best_label, best_diff,
        )
        return width_pt, height_pt, "custom"

    logger.info(
        "Detected aspect ratio: %s (page=%.1f×%.1f → snapped=%.1f×%.1f)",
        best_label, width_pt, height_pt, best_w, best_h,
    )
    return best_w, best_h, best_label


def pdf_to_images(
    pdf_path: str, dpi: int = 192
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


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}


def images_from_folder(
    folder_path: str,
) -> list[tuple[bytes, dict]]:
    """Load slide images from a folder, sorted by filename in ascending order.

    Each image is read as PNG bytes. Dimensions are converted to pt assuming
    96 DPI (1 px = 0.75 pt) for consistent coordinate handling with the rest
    of the pipeline.

    Returns a list of (png_bytes, metadata) tuples identical in structure to
    ``pdf_to_images`` output.
    """
    entries = sorted(os.listdir(folder_path))
    image_files = [
        f for f in entries
        if os.path.isfile(os.path.join(folder_path, f))
        and os.path.splitext(f)[1].lower() in _IMAGE_EXTS
    ]

    if not image_files:
        msg = f"No image files found in {folder_path}"
        raise FileNotFoundError(msg)

    pages: list[tuple[bytes, dict]] = []
    total_bytes = 0

    logger.info("Loading %d images from folder: %s", len(image_files), folder_path)

    for page_num, fname in enumerate(image_files):
        fpath = os.path.join(folder_path, fname)
        with Image.open(fpath) as img:
            img = img.convert("RGB")
            width_px, height_px = img.size
            import io

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()

        width_pt = width_px * 0.75
        height_pt = height_px * 0.75
        total_bytes += len(img_bytes)

        metadata = {
            "page_num": page_num,
            "width_pt": width_pt,
            "height_pt": height_pt,
            "width_px": width_px,
            "height_px": height_px,
            "source_file": fname,
        }
        pages.append((img_bytes, metadata))
        logger.info(
            "  Page %3d/%d: %s (%d×%d px, %.1f KB)",
            page_num,
            len(image_files),
            fname,
            width_px,
            height_px,
            len(img_bytes) / 1024,
        )

    logger.info(
        "All %d images loaded (total %.1f MB)",
        len(pages),
        total_bytes / (1024 * 1024),
    )
    return pages
