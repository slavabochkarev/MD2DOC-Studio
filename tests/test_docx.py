from zipfile import ZipFile

from docx import Document
from docx.shared import Mm
import pytest

from conftest import successful, xml, xpath


def test_headers_footers_fields_and_core_properties(project):
    project.add()
    successful(project)
    doc = Document(project.output)
    section = doc.sections[0]
    assert section.different_first_page_header_footer
    assert xpath(project.output, "//w:instrText/text()", "word/footer1.xml") == [" PAGE "]
    assert not xpath(project.output, "//w:instrText", "word/footer2.xml")
    assert xpath(project.output, "//w:pgNumType/@w:start") == ["1"]
    assert doc.core_properties.title == project.config("metadata.yaml")["title"]
    assert doc.core_properties.author == project.config("metadata.yaml")["author"]
    assert section.left_margin.twips == Mm(30).twips


def test_page_orientation_and_hyphenation(project):
    project.add()
    config = project.config()
    config["page"].update(paper="A5", orientation="landscape", mirror_margins=True)
    config["breaks"]["hyphenation"].update(enabled=True, consecutive_limit=3)
    config["headers_footers"]["page_number"].update(start=4, format="upper_roman", position="header_right")
    config["headers_footers"]["first_page"]["show_page_number"] = True
    project.write(config)
    successful(project)
    section = Document(project.output).sections[0]
    assert section.page_width.twips == Mm(210).twips and section.page_height.twips == Mm(148).twips
    assert xpath(project.output, "//w:mirrorMargins", "word/settings.xml")
    assert xpath(project.output, "//w:autoHyphenation/@w:val", "word/settings.xml") == ["1"]
    assert xpath(project.output, "//w:consecutiveHyphenLimit/@w:val", "word/settings.xml") == ["3"]
    assert xpath(project.output, "//w:pgNumType/@w:fmt") == ["upperRoman"]
    assert xpath(project.output, "//w:instrText", "word/header1.xml")
    assert xpath(project.output, "//w:instrText", "word/header2.xml")


@pytest.mark.parametrize("mode,expected", [("error", 1), ("overflow", 0), ("wrap", 0)])
def test_code_width_policy(project, mode, expected):
    project.add(text="# Code\n\n```text\n" + "x" * 400 + "\n```")
    config = project.config()
    config["breaks"]["code_long_lines"] = mode
    project.write(config)
    report, code = project.build()
    assert code == expected
    if mode == "error":
        assert report.errors[-1].code == "E_CODE_WIDTH"
    elif mode == "overflow":
        assert "W_CODE_OVERFLOW" in [d.code for d in report.warnings]
    else:
        assert "x" * 400 in Document(project.output).paragraphs[-1].text


def test_package_parts_and_property_sequence(project):
    project.add(text="# Main\n\n`code`\n\n```text\nx\n```\n\n| a |\n| --- |\n| b |")
    successful(project)
    with ZipFile(project.output) as archive:
        for name in ("word/document.xml", "word/styles.xml", "word/numbering.xml", "word/_rels/document.xml.rels", "docProps/core.xml"):
            assert name in archive.namelist()
    # Catch invalid append-only OOXML extensions that tolerant readers conceal.
    section = xpath(project.output, "//w:sectPr")[0]
    names = [n.tag.rsplit("}", 1)[-1] for n in section]
    assert names.index("pgNumType") < names.index("cols")
    for rpr in xpath(project.output, "//w:style/w:rPr", "word/styles.xml"):
        children = [n.tag.rsplit("}", 1)[-1] for n in rpr]
        if "spacing" in children and "sz" in children:
            assert children.index("spacing") < children.index("sz")
    for tcpr in xpath(project.output, "//w:tcPr"):
        children = [n.tag.rsplit("}", 1)[-1] for n in tcpr]
        assert children.index("shd") < children.index("vAlign")
