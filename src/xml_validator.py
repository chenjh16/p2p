from __future__ import annotations

import re

from lxml import etree

from .logging_config import get_logger

logger = get_logger("xml_validator")

_REQUIRED_NAMESPACES = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

_FALLBACK_SLIDE_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="ErrorInfo"/>
          <p:cNvSpPr txBox="1"/>
          <p:nvPr/>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm>
            <a:off x="914400" y="914400"/>
            <a:ext cx="7315200" cy="1828800"/>
          </a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" rtlCol="0"/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="1400">
                <a:solidFill><a:srgbClr val="FF0000"/></a:solidFill>
              </a:rPr>
              <a:t>[Slide generation error for page {page_num}] {error}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>"""


def validate_and_fix(xml_str: str, page_num: int) -> str:
    """Validate slide XML and attempt to fix common issues.

    Returns valid XML string, or a fallback error slide if unfixable.
    """
    xml_str = xml_str.strip()

    # Strip markdown code fences if the model wrapped the XML
    xml_str = _strip_code_fences(xml_str)

    # Ensure XML declaration
    if not xml_str.startswith("<?xml") and xml_str.startswith("<p:sld"):
        xml_str = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + xml_str

    # Try parsing
    try:
        etree.fromstring(xml_str.encode("utf-8"))
        return xml_str
    except etree.XMLSyntaxError as e:
        logger.warning("Slide %d: XML syntax error: %s", page_num, e)

    # Attempt fixes
    fixed = _attempt_fixes(xml_str)
    try:
        etree.fromstring(fixed.encode("utf-8"))
        logger.info("Slide %d: XML auto-fixed successfully", page_num)
        return fixed
    except etree.XMLSyntaxError as e2:
        logger.error("Slide %d: XML cannot be fixed, using fallback", page_num)
        return _FALLBACK_SLIDE_TEMPLATE.format(
            page_num=page_num, error=str(e2).replace('"', "&quot;")
        )


def _strip_code_fences(xml_str: str) -> str:
    """Remove markdown code fences that models sometimes add."""
    xml_str = re.sub(r"^```(?:xml)?\s*\n?", "", xml_str)
    xml_str = re.sub(r"\n?```\s*$", "", xml_str)
    return xml_str.strip()


def _attempt_fixes(xml_str: str) -> str:
    """Try common XML fixes."""
    fixed = xml_str

    # Fix unescaped ampersands (but not already-escaped ones)
    fixed = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)", "&amp;", fixed)

    # Ensure root element has required namespaces
    for prefix, uri in _REQUIRED_NAMESPACES.items():
        ns_decl = f'xmlns:{prefix}="{uri}"'
        if ns_decl not in fixed and f"<{prefix}:" in fixed:
            fixed = fixed.replace(
                "<p:sld", f"<p:sld {ns_decl}", 1
            )

    return fixed
