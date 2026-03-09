from __future__ import annotations

import copy

from lxml import etree
from pptx import Presentation
from pptx.util import Pt

from .logging_config import get_logger
from .xml_validator import validate_and_fix

logger = get_logger("assembler")

_NSMAP = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _qn(tag: str) -> str:
    """Convert a prefixed tag like 'p:sp' to Clark notation."""
    prefix, local = tag.split(":")
    return f"{{{_NSMAP[prefix]}}}{local}"


class PPTXAssembler:
    """Assemble GPT-generated Slide XMLs into a valid PPTX file."""

    def __init__(self, slide_width_pt: float, slide_height_pt: float):
        self.prs = Presentation()
        self.prs.slide_width = Pt(slide_width_pt)
        self.prs.slide_height = Pt(slide_height_pt)
        self._blank_layout = self.prs.slide_layouts[6]  # blank layout

    def assemble(self, slide_xmls: dict[int, str]) -> Presentation:  # type: ignore[valid-type]
        """Inject slide XMLs into the presentation in page order."""
        w = self.prs.slide_width or 0
        h = self.prs.slide_height or 0
        logger.info("Assembling PPTX (%.0fpt × %.0fpt)...", w / 12700, h / 12700)

        for page_num in sorted(slide_xmls.keys()):
            raw_xml = slide_xmls[page_num]
            xml_str = validate_and_fix(raw_xml, page_num)

            slide = self.prs.slides.add_slide(self._blank_layout)

            try:
                new_sld = etree.fromstring(xml_str.encode("utf-8"))
            except etree.XMLSyntaxError:
                logger.error(
                    "Slide %d: failed to parse even after validation", page_num
                )
                continue

            old_sld = slide._element

            # Remove existing children from the blank slide
            for child in list(old_sld):
                old_sld.remove(child)

            # Copy children from the generated XML
            for child in new_sld:
                old_sld.append(copy.deepcopy(child))

            # Copy namespace declarations from the new element
            for prefix, uri in new_sld.nsmap.items():
                if prefix is not None:
                    existing = old_sld.nsmap.get(prefix)
                    if existing is None or existing != uri:
                        etree.register_namespace(prefix, uri)

            # Count shapes for logging
            shapes = new_sld.findall(".//" + _qn("p:sp"))
            frames = new_sld.findall(".//" + _qn("p:graphicFrame") if "p" in _NSMAP else ".//graphicFrame")
            logger.info(
                "  Slide %3d: %d shapes, %d frames",
                page_num,
                len(shapes),
                len(frames) if frames else 0,
            )

        logger.info("PPTX assembled (%d slides)", len(self.prs.slides))
        return self.prs

    def save(self, output_path: str) -> None:
        self.prs.save(output_path)
        logger.info("PPTX saved: %s", output_path)
