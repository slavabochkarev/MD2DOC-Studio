from conftest import paragraphs, successful, xpath


def test_preorder_and_no_alphabetical_sort(project):
    parent = project.add("z-first", text="# Parent\n\nParent body")
    project.add("a-child", "section", "## Child\n\nChild body", parent=parent)
    project.add("b-last", text="# Last\n\nLast body")
    successful(project)
    assert paragraphs(project.output) == ["1 Parent", "Parent body", "1.1 Child", "Child body", "2 Last", "Last body"]


def test_yaml_heading_once_and_markdown_heading_once(project):
    project.add(text="Body\n\n## Local", heading={"from": "yaml", "text": "From YAML", "level": 1})
    successful(project)
    assert paragraphs(project.output) == ["1 From YAML", "Body", "Local"]


def test_disabled_subtree(project):
    parent = project.add(enabled=False)
    project.add("child", "section", "## Excluded", parent=parent, enabled=True)
    project.add("last", text="# Last")
    report = successful(project)
    assert report.processed_files == 1
    assert paragraphs(project.output) == ["1 Last"]


def test_page_breaks_after_subtree_and_coalescing(project):
    parent = project.add(text="# Parent", page_break={"before": True, "after": True})
    project.add("child", "section", "## Child", parent=parent)
    project.add("last", text="# Last\n\n<!-- pagebreak -->\n\n<!-- pagebreak -->\n\nText\n\n<!-- pagebreak -->", page_break={"before": True, "after": True})
    successful(project)
    from docx import Document
    assert [p.paragraph_format.page_break_before for p in Document(project.output).paragraphs] == [False, False, True, True]
    assert len(paragraphs(project.output)) == 4


def test_excluded_target_prevents_release(project):
    project.add(text="# Main\n\n[No](md2doc:excluded)")
    project.add("excluded", text="# Excluded", enabled=False)
    report, code = project.build()
    assert code == 1
    assert "W_EXCLUDED_LINK" in [d.code for d in report.warnings]
    assert "E_EXCLUDED_LINK" in [d.code for d in report.errors]
