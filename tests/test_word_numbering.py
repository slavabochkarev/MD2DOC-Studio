"""Word cross-part contract regressions; never launch Word or automate its UI."""
from copy import deepcopy
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from lxml import etree
import pytest

from md2doc.diagnostics.delivery import verify_delivery
from md2doc.diagnostics.numbering_inspector import inspect_heading_numbering
from md2doc.diagnostics.report import BuildError
from md2doc.renderers.integrity import NS, verify_docx
from conftest import successful, xml
from test_heading_numbering import enable


def four_levels(project, **kwargs):
    enable(project, kwargs or None)
    project.add(text="# Chapter one\n\n## Section\n\n### Subsection\n\n#### Detail\n\n- Bullet\n- Next\n\n1. First\n2. Second")
    project.add("two", text="# Chapter two\n\n## Section two\n\n### Subsection two\n\n#### Detail two")
    successful(project, strict=True)


def test_four_levels_have_direct_word_numbering(project):
    four_levels(project)
    data = inspect_heading_numbering(project.output)
    assert [h["label"] for h in data] == ["1", "1.1", "1.1.1", "1.1.1.1", "2", "2.1", "2.1.1", "2.1.1.1"]
    assert len({h["num_id"] for h in data}) == 1
    numbering, styles = xml(project.output, "word/numbering.xml"), xml(project.output, "word/styles.xml")
    num_id = data[0]["num_id"]
    aid = numbering.xpath(f"./w:num[@w:numId='{num_id}']/w:abstractNumId/@w:val", namespaces=NS)[0]
    definition = numbering.xpath(f"./w:abstractNum[@w:abstractNumId='{aid}']", namespaces=NS)[0]
    assert definition.xpath("./w:lvl/@w:ilvl", namespaces=NS) == [str(i) for i in range(9)]
    for i in range(4):
        style = styles.xpath(f"./w:style[@w:styleId='Heading{i + 1}']", namespaces=NS)[0]
        assert not style.xpath("./w:pPr/w:numPr", namespaces=NS)
        lvl = definition.xpath(f"./w:lvl[@w:ilvl='{i}']", namespaces=NS)[0]
        assert not lvl.xpath("./w:pStyle", namespaces=NS)
        assert lvl.xpath("./w:lvlText/@w:val", namespaces=NS) == [".".join(f"%{j + 1}" for j in range(i + 1))]
    doc = Document(project.output)
    assert doc.paragraphs[0].text == "Chapter one"
    assert [p.style.name for p in doc.paragraphs[:4]] == [f"Heading {i}" for i in range(1, 5)]


@pytest.mark.parametrize("template,expected", [
    ("{n}", ["1", "1", "1", "1"]), ("{n}.", ["1."] * 4),
    ("{n})", ["1)"] * 4), ("{path}", ["1", "1.1", "1.1.1", "1.1.1.1"]),
])
def test_native_templates_keep_style_contract(project, template, expected):
    four_levels(project, template=template)
    verify_docx(project.output)
    assert [h["label"] for h in inspect_heading_numbering(project.output)][:4] == expected


def test_inserted_heading_continues_native_list(project):
    four_levels(project)
    doc = Document(project.output)
    inserted = deepcopy(doc.paragraphs[1]._p)
    ppr = inserted.find("w:pPr", NS)
    ppr.remove(ppr.find("w:outlineLvl", NS))
    for node in inserted.findall("w:bookmarkStart", NS) + inserted.findall("w:bookmarkEnd", NS):
        inserted.remove(node)
    doc.paragraphs[1]._p.addnext(inserted)
    doc.save(project.output)
    verify_docx(project.output)
    data = inspect_heading_numbering(project.output)
    assert [h["label"] for h in data][:5] == ["1", "1.1", "1.2", "1.2.1", "1.2.1.1"]


def corrupt(path, member, change):
    with ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    root = etree.fromstring(parts[member])
    change(root)
    parts[member] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)


def select(root, expr):
    return root.xpath(expr, namespaces=NS)[0]


def style_num(root, identity):
    parent = select(root, "./w:style[@w:styleId='Heading2']/w:pPr")
    num = etree.SubElement(parent, "{" + NS['w'] + "}numPr")
    etree.SubElement(num, "{" + NS['w'] + "}numId").set("{" + NS['w'] + "}val", identity)


def level_style(root):
    parent = select(root, "./w:abstractNum[w:name]/w:lvl[@w:ilvl='2']")
    etree.SubElement(parent, "{" + NS['w'] + "}pStyle").set("{" + NS['w'] + "}val", "Heading3")


def abstract_style_link(root):
    parent = select(root, "./w:abstractNum[w:name]")
    etree.SubElement(parent, "{" + NS['w'] + "}numStyleLink").set("{" + NS['w'] + "}val", "Heading1")


def explicit_restart(root, level, value):
    parent = select(root, f"./w:abstractNum[w:name]/w:lvl[@w:ilvl='{level}']")
    etree.SubElement(parent, "{" + NS['w'] + "}lvlRestart").set("{" + NS['w'] + "}val", str(value))


@pytest.mark.parametrize("member,change,message", [
    ("word/styles.xml", lambda r: style_num(r, "10"), "must not appear in style"),
    ("word/styles.xml", lambda r: style_num(r, "99999"), "Undefined numId"),
    ("word/styles.xml", lambda r: select(r, "./w:style[@w:styleId='Heading4']/w:pPr/w:outlineLvl").set("{" + NS['w'] + "}val", "0"), "outlineLvl"),
    ("word/numbering.xml", level_style, "must not link"),
    ("word/numbering.xml", lambda r: select(r, "./w:abstractNum[w:name]/w:lvl[@w:ilvl='3']/w:pPr").remove(select(r, "./w:abstractNum[w:name]/w:lvl[@w:ilvl='3']/w:pPr/w:ind")), "left/hanging"),
    ("word/numbering.xml", lambda r: select(r, "./w:abstractNum[w:name]").remove(select(r, "./w:abstractNum[w:name]/w:lvl[@w:ilvl='3']")), "levels 0..8"),
    ("word/numbering.xml", lambda r: select(r, "./w:abstractNum[w:name]/w:lvl[@w:ilvl='1']/w:lvlText").set("{" + NS['w'] + "}val", "%9"), "deeper/undefined"),
    ("word/document.xml", lambda r: select(r, "//w:p[w:pPr/w:outlineLvl[@w:val='2']]/w:pPr/w:numPr/w:ilvl").set("{" + NS['w'] + "}val", "0"), "conflicts"),
    ("word/numbering.xml", abstract_style_link, "must not contain styleLink"),
    ("word/numbering.xml", lambda r: select(r, "./w:abstractNum[w:name]/w:nsid").set("{" + NS['w'] + "}val", "wrong"), "hexadecimal nsid"),
    ("word/numbering.xml", lambda r: select(r, "./w:abstractNum[w:name]/w:tmpl").set("{" + NS['w'] + "}val", "123"), "hexadecimal tmpl"),
    ("word/numbering.xml", lambda r: explicit_restart(r, 1, 1), "must omit parent lvlRestart"),
    ("word/numbering.xml", lambda r: explicit_restart(r, 8, 8), "Word only supports"),
])
def test_central_verifier_rejects_broken_word_links(project, member, change, message):
    four_levels(project)
    corrupt(project.output, member, change)
    with pytest.raises(BuildError, match=message):
        verify_docx(project.output)
    report, _, code = verify_delivery(project.root, strict=True)
    assert code == 1 and report.errors[-1].code == "E_DOCX_INTEGRITY"


def test_heading_numbers_cannot_be_reused_by_ordinary_list(project):
    four_levels(project)
    heading_num = inspect_heading_numbering(project.output)[0]["num_id"]

    def change(root):
        node = select(root, "//w:p[not(w:pPr/w:outlineLvl)][w:pPr/w:numPr]/w:pPr/w:numPr/w:numId")
        node.set("{" + NS['w'] + "}val", heading_num)
    corrupt(project.output, "word/document.xml", change)
    with pytest.raises(BuildError, match="without heading outlineLvl"):
        verify_docx(project.output)


def test_word_schema_order_for_table_and_settings(project):
    project.add(text="# Main\n\n| A | B |\n| --- | --- |\n| a | b |")
    successful(project)
    body = xml(project.output)
    tags = [etree.QName(n).localname for n in select(body, "//w:tblPr")]
    assert tags.index("tblW") < tags.index("jc")
    assert [etree.QName(n).localname for n in select(body, "//w:tblCellMar")] == ["top", "left", "bottom", "right"]
    settings = [etree.QName(n).localname for n in xml(project.output, "word/settings.xml")]
    assert settings.index("autoHyphenation") < settings.index("consecutiveHyphenLimit") < settings.index("characterSpacingControl")


def test_native_definition_matches_user_word_reference(project):
    """Compare semantic properties extracted from the USER's Word file.

    This fixture is not generated by MD2DOC and proves structural similarity,
    not visual rendering. User templates and suffixes remain configurable.
    """
    fixture = json.loads((Path(__file__).parent / "fixtures/word-numbering-reference.json").read_text(encoding="utf-8"))
    four_levels(project, template="{path}.", number_text_separator="tab")
    root = xml(project.output, "word/numbering.xml")
    definition = select(root, "./w:abstractNum[w:name]")
    assert definition.xpath("./w:multiLevelType/@w:val", namespaces=NS) == [fixture["multiLevelType"]]
    assert len(definition.findall("w:lvl", NS)) == len(fixture["levels"]) == 9
    for level, expected in zip(definition.findall("w:lvl", NS), fixture["levels"]):
        for tag in ("start", "numFmt", "lvlText", "lvlJc"):
            assert level.xpath(f"./w:{tag}/@w:val", namespaces=NS) == [expected[tag]]
        indent = level.find("w:pPr/w:ind", NS)
        assert {etree.QName(k).localname: v for k, v in indent.attrib.items()} == expected["indent"]
        assert not level.findall("w:pStyle", NS)
        assert not level.findall("w:lvlRestart", NS)
        # The reference omits suff, whose effective value is tab.
        assert level.xpath("./w:suff/@w:val", namespaces=NS) == ["tab"]
    assert not xml(project.output, "word/styles.xml").xpath("./w:style[starts-with(@w:styleId, 'Heading')]/w:pPr/w:numPr", namespaces=NS)


def test_style_only_heading_does_not_implicitly_join_list(project):
    four_levels(project)
    doc = Document(project.output)
    p = doc.add_paragraph("New unnumbered heading", "Heading 2")
    doc.save(project.output)
    verify_docx(project.output)
    assert inspect_heading_numbering(project.output)[-1]["label"] == ""


def test_old_six_level_style_linked_documents_remain_readable(project):
    four_levels(project)
    doc = Document(project.output)
    root = doc.part.numbering_part.element
    definition = root.xpath("./w:abstractNum[w:name]")[0]
    definition.find("w:name", NS).set("{" + NS['w'] + "}val", "MD2DOC Headings legacy")
    num_id = inspect_heading_numbering(project.output)[0]["num_id"]
    for i, level in enumerate(list(definition.findall("w:lvl", NS))):
        if i >= 6:
            definition.remove(level)
            continue
        ps = etree.Element("{" + NS['w'] + "}pStyle")
        ps.set("{" + NS['w'] + "}val", f"Heading{i + 1}")
        level.insert(3 if i else 2, ps)
        ppr = doc.styles[f"Heading {i + 1}"].element.get_or_add_pPr()
        num = etree.SubElement(ppr, "{" + NS['w'] + "}numPr")
        etree.SubElement(num, "{" + NS['w'] + "}numId").set("{" + NS['w'] + "}val", num_id)
    doc.save(project.output)
    verify_docx(project.output)
    assert inspect_heading_numbering(project.output)[-1]["label"] == "2.1.1.1"
