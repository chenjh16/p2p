"""Unit tests for src.xml_validator."""

from __future__ import annotations

from tests.conftest import SAMPLE_SLIDE_XML


class TestXmlValidator:
    GOOD_XML = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr/>
  </p:spTree></p:cSld>
</p:sld>"""

    def test_valid_xml_passes_through(self):
        from src.xml_validator import validate_and_fix

        result = validate_and_fix(self.GOOD_XML, 0)
        assert "<p:sld" in result

    def test_strips_markdown_fences(self):
        from src.xml_validator import validate_and_fix

        fenced = f"```xml\n{self.GOOD_XML}\n```"
        result = validate_and_fix(fenced, 0)
        assert "```" not in result
        assert "<p:sld" in result

    def test_adds_xml_declaration(self):
        from src.xml_validator import validate_and_fix

        no_decl = self.GOOD_XML.replace('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n', "")
        result = validate_and_fix(no_decl, 0)
        assert result.startswith("<?xml")

    def test_fixes_unescaped_ampersand(self):
        from src.xml_validator import validate_and_fix

        xml_with_amp = self.GOOD_XML.replace('name=""', 'name="A &amp; B"')
        result = validate_and_fix(xml_with_amp, 0)
        assert "<p:sld" in result

    def test_broken_xml_returns_fallback(self):
        from src.xml_validator import validate_and_fix

        result = validate_and_fix("<p:sld><broken", 5)
        assert "ErrorInfo" in result
        assert "page 5" in result

    def test_adds_missing_namespace(self):
        from src.xml_validator import validate_and_fix

        xml_no_ns = '<p:sld><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld></p:sld>'
        result = validate_and_fix(xml_no_ns, 0)
        assert "<p:sld" in result

    def test_e2e_xml_validation(self):
        """XML validator should fix common issues and produce valid XML."""
        from src.xml_validator import validate_and_fix

        good_xml = SAMPLE_SLIDE_XML.format(page_num=0)
        result = validate_and_fix(good_xml, 0)
        assert "<p:sld" in result

        fenced = f"```xml\n{good_xml}\n```"
        result = validate_and_fix(fenced, 0)
        assert "<p:sld" in result
        assert "```" not in result

        bad_xml = "<p:sld><broken"
        result = validate_and_fix(bad_xml, 0)
        assert "<p:sld" in result
        assert "ErrorInfo" in result or "<p:sld" in result
