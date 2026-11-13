from docx import Document
from docx.shared import Mm
import pytest

from md2doc.core.style_resolver import StyleResolver
from conftest import successful, xpath


def test_style_overrides_do_not_rematerialize_base(project):
    styles = project.config()
    styles["named_styles"].update(red={"based_on": "body", "font": {"color": "#FF0000", "bold": True}}, heading={"based_on": "h2", "font": {"bold": False}})
    resolver = StyleResolver(styles)
    result = resolver.resolve("red", "heading")
    assert result["font"]["color"] == "#FF0000"
    assert result["font"]["bold"] is False
    assert result["paragraph"]["line_spacing"] == {"mode": "multiple", "value": 1.5}


def test_body_inheritance_heading_not_inherited(project):
    styles = project.config()
    styles["named_styles"]["red"] = {"font": {"color": "#FF0000"}}
    project.write(styles)
    parent = project.add(text="# Parent", style={"body": "red", "heading": "title"})
    project.add("child", "section", "## Child\n\nBody", parent=parent)
    successful(project)
    doc = Document(project.output)
    assert doc.paragraphs[1].style.name == "MD2DOC red / h2"
    assert doc.paragraphs[1].style.font.size.pt == 14
    assert str(doc.paragraphs[1].style.font.color.rgb) == "FF0000"
    assert doc.paragraphs[2].style.name == "MD2DOC red"


def test_yaml_changes_reach_ooxml(project):
    project.add()
    styles = project.config()
    styles["font"]["size"] = 11
    styles["page"]["margins"]["left"] = "42mm"
    styles["paragraph"]["space_after"] = 9
    project.write(styles)
    successful(project)
    assert xpath(project.output, "//w:style[@w:styleId='Normal']/w:rPr/w:sz/@w:val", "word/styles.xml") == ["22"]
    assert xpath(project.output, "//w:style[@w:styleId='Normal']/w:pPr/w:spacing/@w:after", "word/styles.xml") == ["180"]
    assert xpath(project.output, "//w:pgMar/@w:left") == [str(Mm(42).twips)]


@pytest.mark.parametrize("mode,value,expected_rule,expected_value", [("multiple", 1.15, "auto", "276"), ("exact", 18, "exact", "360"), ("at_least", 16, "atLeast", "320")])
def test_spacing_modes_and_cyrillic_fonts(project, mode, value, expected_rule, expected_value):
    project.add()
    styles = project.config()
    styles["paragraph"]["line_spacing"] = {"mode": mode, "value": value}
    project.write(styles)
    successful(project)
    base = "//w:style[@w:styleId='Normal']"
    assert xpath(project.output, base + "/w:pPr/w:spacing/@w:lineRule", "word/styles.xml") == [expected_rule]
    assert xpath(project.output, base + "/w:pPr/w:spacing/@w:line", "word/styles.xml") == [expected_value]
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        assert xpath(project.output, base + "/w:rPr/w:rFonts/@w:" + attr, "word/styles.xml") == ["Times New Roman"]
