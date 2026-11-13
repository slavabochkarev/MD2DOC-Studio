from conftest import successful, xpath


def test_library_title_border_and_subtitle_numbering_do_not_leak(project):
    project.add(kind="title_page", text="# Title\n\n::: subtitle\nSubtitle\n:::")
    successful(project)
    assert not xpath(project.output, "//w:style[@w:styleId='Title']/w:pPr/w:pBdr", "word/styles.xml")
    assert not xpath(project.output, "//w:style[@w:styleId='Subtitle']/w:pPr/w:numPr", "word/styles.xml")
    assert not xpath(project.output, "//w:updateFields[@w:val='true']", "word/settings.xml")


def test_unexpected_renderer_failure_is_reported_and_atomic(project, monkeypatch):
    project.add()
    successful(project)
    previous = project.output.read_bytes()
    from md2doc.renderers.docx_renderer import DocxRenderer

    def fail(self, output):
        raise RuntimeError("Renderer failed")
    monkeypatch.setattr(DocxRenderer, "render", fail)
    report, code = project.build()
    assert code == 2
    assert report.errors[-1].code == "E_INTERNAL"
    assert project.output.read_bytes() == previous


def test_break_before_first_table_does_not_move_to_following_text(project):
    from docx import Document
    project.add(kind="content", text="| A |\n| --- |\n| B |\n\nAfter table", page_break={"before": True})
    successful(project)
    assert Document(project.output).paragraphs[-1].paragraph_format.page_break_before is False
