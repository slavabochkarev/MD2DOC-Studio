from zipfile import ZipFile

from docx import Document
from PIL import Image
import pytest

from md2doc.core.markdown_parser import parse_markdown
from conftest import paragraphs, successful, xpath


def test_headings_h1_to_h6_and_no_implicit_numbers(project):
    project.add(kind="content", text="\n\n".join("#" * i + f" Heading {i}" for i in range(1, 7)))
    successful(project)
    assert [p.style.name for p in Document(project.output).paragraphs] == [f"Heading {i}" for i in range(1, 7)]
    assert paragraphs(project.output) == [f"Heading {i}" for i in range(1, 7)]


def test_inline_semantics_and_code_not_substituted(project):
    project.add(text="# Main\n\n**bold** *italic* ~~strike~~ `{{metadata.title}}`\n\n```text\n  {{metadata.title}}\n    next\n```\n\n{{metadata.author}}")
    successful(project)
    assert xpath(project.output, "//w:r[w:rPr/w:b[not(@w:val='0')]]/w:t/text()") == ["bold"]
    assert xpath(project.output, "//w:r[w:rPr/w:i[not(@w:val='0')]]/w:t/text()") == ["italic"]
    assert xpath(project.output, "//w:r[w:rPr/w:strike[not(@w:val='0')]]/w:t/text()") == ["strike"]
    assert xpath(project.output, "//w:r[w:rPr/w:rStyle]/w:t/text()") == ["{{metadata.title}}"]
    assert "  {{metadata.title}}\n    next" in [p.text for p in Document(project.output).paragraphs]
    assert project.config("metadata.yaml")["author"] in paragraphs(project.output)


def test_metadata_cannot_inject_markup(project):
    project.add(text="# Main\n\n{{metadata.author}}")
    metadata = project.config("metadata.yaml")
    metadata["author"] = "**literal** <script> & text"
    project.write(metadata, "metadata.yaml")
    successful(project)
    doc = Document(project.output)
    assert doc.paragraphs[-1].text == metadata["author"]
    assert len(doc.paragraphs[-1].runs) == 1
    assert doc.paragraphs[-1].runs[0].bold is None


@pytest.mark.parametrize("soft,breaks", [("space", 1), ("line", 2)])
def test_soft_and_hard_line_breaks(project, soft, breaks):
    project.add(text="# Main\n\nFirst\nsecond  \nthird")
    styles = project.config()
    styles["breaks"]["soft_line_break"] = soft
    project.write(styles)
    successful(project)
    assert len(xpath(project.output, "//w:br")) == breaks


def test_native_lists_nested_restart_and_start(project):
    project.add(text="# Main\n\n- Outer\n  - Nested\n- Outer two\n\n3. Three\n4. Four\n\nParagraph\n\n1. One\n2. Two")
    styles = project.config()
    styles["lists"]["ordered_start"] = 8
    project.write(styles)
    successful(project)
    ids = xpath(project.output, "//w:body/w:p/w:pPr/w:numPr/w:numId/@w:val")
    assert len(ids) == 7
    assert ids[0] == ids[2] and ids[0] != ids[1]
    assert ids[3] == ids[4] and ids[5] == ids[6] and ids[3] != ids[5]
    assert xpath(project.output, "//w:body/w:p/w:pPr/w:numPr/w:ilvl/@w:val")[:3] == ["0", "1", "0"]
    assert xpath(project.output, f"//w:num[@w:numId='{ids[3]}']/w:lvlOverride/w:startOverride/@w:val", "word/numbering.xml") == ["3"]
    assert xpath(project.output, f"//w:num[@w:numId='{ids[5]}']/w:lvlOverride/w:startOverride/@w:val", "word/numbering.xml") == ["1"]
    assert all(not p.startswith(("•", "- ")) for p in paragraphs(project.output))


def test_list_depth_error(project):
    project.add(text="# Main\n\n- A\n  - B")
    styles = project.config()
    styles["lists"]["max_depth"] = 1
    project.write(styles)
    report, code = project.build()
    assert code == 1
    assert report.errors[-1].code == "E_LIST_DEPTH"


def test_native_table_alignment_and_properties(project):
    project.add(text="# Main\n\n| Left | Right |\n| :--- | ---: |\n| a | **b** |\n| c | d |")
    report = successful(project)
    assert report.tables == 1
    doc = Document(project.output)
    assert len(doc.tables[0].rows) == 3
    assert doc.tables[0].cell(1, 1).text == "b"
    assert xpath(project.output, "//w:tr[1]/w:trPr/w:tblHeader")
    assert len(xpath(project.output, "//w:tr/w:trPr/w:cantSplit")) == 3
    assert xpath(project.output, "//w:tr[2]/w:tc[2]/w:p/w:pPr/w:jc/@w:val") == ["right"]
    assert xpath(project.output, "//w:tcPr/w:shd/@w:fill") == ["D9E2F3", "D9E2F3", "FFFFFF", "FFFFFF", "F2F2F2", "F2F2F2"]
    assert len(xpath(project.output, "//w:tblBorders/*")) == 6
    assert xpath(project.output, "//w:tblCellMar/w:left/@w:w") == ["113"]
    assert all(p.paragraph_format.first_line_indent == 0 for row in doc.tables[0].rows for cell in row.cells for p in cell.paragraphs)


@pytest.mark.parametrize("extension", ["png", "jpg", "svg", "gif"])
def test_images_embedded_and_captions(project, extension):
    path = project.root / ("assets/picture." + extension)
    if extension == "svg":
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><rect width="100" height="50" fill="red"/></svg>', encoding="utf-8")
    else:
        Image.new("RGB", (100, 50), "red").save(path)
    project.add(text=f'# Main\n\n![Alt](../assets/picture.{extension} "Caption")')
    report = successful(project)
    assert report.images == 1
    doc = Document(project.output)
    assert len(doc.inline_shapes) == 1
    assert doc.inline_shapes[0].width == doc.inline_shapes[0].height * 2
    assert paragraphs(project.output)[-1] == "Рисунок 1 — Caption"
    with ZipFile(project.output) as archive:
        assert any(n.startswith("word/media/") for n in archive.namelist())


def test_external_svg_resource_never_fetched(project):
    (project.root / "assets/bad.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://invalid.example/a.png"/></svg>', encoding="utf-8")
    project.add(text="# Main\n\n![Bad](../assets/bad.svg)")
    report, code = project.build()
    assert code == 1
    assert report.errors[-1].code == "E_IMAGE"
    assert not project.output.exists()


def test_invalid_binary_image_retains_old_docx(project):
    project.add()
    successful(project)
    previous = project.output.read_bytes()
    (project.root / "assets/broken.png").write_bytes(b"not an image")
    (project.root / "content/one.md").write_text("# Main\n\n![Bad](../assets/broken.png)", encoding="utf-8")
    report, code = project.build()
    assert code == 1
    assert report.errors[-1].code == "E_IMAGE"
    assert project.output.read_bytes() == previous


def test_image_in_table_cell_is_embedded(project):
    Image.new("RGB", (100, 50), "red").save(project.root / "assets/cell.png")
    project.add(text='# Main\n\n| Picture |\n| --- |\n| ![Alt](../assets/cell.png "Cell caption") |')
    report = successful(project)
    assert report.images == 1 and report.tables == 1
    doc = Document(project.output)
    assert len(doc.inline_shapes) == 1
    assert "Рисунок 1 — Cell caption" in doc.tables[0].cell(1, 0).text


def test_active_external_and_internal_links(project):
    project.add(text="# Main\n\n[**External**](https://example.com) [Internal](md2doc:two) [Fragment](two.md#local) [Self](#main)")
    project.add("two", text="# Other\n\n## Local")
    successful(project)
    assert len(xpath(project.output, "//w:hyperlink[@w:anchor]")) == 3
    assert len(xpath(project.output, "//w:hyperlink[@r:id]")) == 1
    assert xpath(project.output, "//w:hyperlink/w:r[w:rPr/w:b]/w:t/text()") == ["External"]
    from conftest import xml
    rels = xml(project.output, "word/_rels/document.xml.rels")
    assert any(r.get("Target") == "https://example.com" and r.get("TargetMode") == "External" for r in rels)
    bookmarks = set(xpath(project.output, "//w:bookmarkStart/@w:name"))
    assert all(a in bookmarks for a in xpath(project.output, "//w:hyperlink/@w:anchor"))


def test_duplicate_slugs_and_yaml_heading_anchor(project):
    project.add(text="# Main\n\n[Second](two.md#local-2) [YAML](two.md#virtual)")
    project.add("two", text="## Local\n\n## Local", heading={"from": "yaml", "level": 1, "text": "Virtual"})
    successful(project)
    assert len(xpath(project.output, "//w:hyperlink[@w:anchor]")) == 2


def test_special_blocks_quote_and_hr(project):
    project.add(text="# Main\n\n::: note\nNote **bold**\n:::\n\n::: warning\nWarning\n:::\n\n::: subtitle\nSubtitle\n:::\n\n> Quote\n\n---")
    successful(project)
    names = [p.style.name for p in Document(project.output).paragraphs]
    assert names[1:5] == ["MD2DOC note", "MD2DOC warning", "Subtitle", "Quote"]
    assert xpath(project.output, "//w:pBdr/w:bottom")


def test_parser_keeps_unsupported_block_text():
    blocks = parse_markdown("    indented code\n", {})
    assert blocks[0].text == "indented code\n"


@pytest.mark.parametrize("text", ["<div>HTML</div>", "::: unsupported\nText\n:::", "[a]: https://example.com\n\n[a][a]"])
def test_unsupported_profile_has_diagnostic(project, text):
    project.add(text="# Main\n\n" + text)
    report, code = project.build()
    assert code == 1
    assert "E_MARKDOWN" in [d.code for d in report.errors]


def test_unknown_ast_node_retains_text_and_warns(project, monkeypatch):
    import md2doc.core.structure_builder as builder
    from md2doc.core.document_model import Block
    original = builder.parse_markdown

    def parse(text, metadata):
        return original(text, metadata) + [Block("future_block", text="Must survive")]
    monkeypatch.setattr(builder, "parse_markdown", parse)
    project.add()
    report = successful(project)
    assert report.warnings[-1].code == "W_MARKDOWN_UNSUPPORTED"
    assert paragraphs(project.output)[-1] == "Must survive"
