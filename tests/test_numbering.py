import pytest

from md2doc.core.numbering import alpha
from conftest import paragraphs, successful


@pytest.mark.parametrize("number,expected", [(1, "A"), (26, "Z"), (27, "AA"), (52, "AZ"), (53, "BA"), (703, "AAA")])
def test_appendix_letters(number, expected):
    assert alpha(number) == expected


def test_chapters_nested_reset_and_unnumbered_ancestor(project):
    first = project.add(text="# First")
    child = project.add("child", "section", "## Child", parent=first, numbering={"enabled": False})
    project.add("grandchild", "section", "### Grandchild", parent=child, numbering={"enabled": True})
    project.add("sibling", "section", "## Sibling", parent=first)
    second = project.add("second", text="# Second", numbering={"enabled": False})
    project.add("restart", "section", "## Restart", parent=second, numbering={"enabled": True})
    project.add("third", text="# Third")
    successful(project)
    assert paragraphs(project.output) == ["1 First", "Child", "1.1 Grandchild", "1.1 Sibling", "Second", "1 Restart", "2 Third"]


def test_appendices_and_children(project):
    project.add(text="# Chapter")
    appendix = project.add("a", "appendix", "# Appendix")
    project.add("section", "section", "## Section", parent=appendix)
    project.add("b", "appendix", "Body", heading={"from": "yaml", "level": 1, "text": "Checklist"})
    successful(project)
    assert paragraphs(project.output) == ["1 Chapter", "Приложение A — Appendix", "A.1 Section", "Приложение B — Checklist", "Body"]
