import json
import os
from pathlib import Path
import subprocess
import sys

from docx import Document
import pytest

from md2doc.diagnostics.numbering_inspector import inspect_heading_numbering
from conftest import successful, xpath


def enable(project, config=None):
    project.manifest["schema_version"] = "0.2"
    for name in ("metadata.yaml", "styles.yaml"):
        value = project.config(name)
        value["schema_version"] = "0.2"
        if name == "styles.yaml":
            value["heading_numbering"] = config or {"enabled": True}
        project.write(value, name)


def labels(project):
    return [h["label"] for h in inspect_heading_numbering(project.output)]


@pytest.mark.parametrize("format,expected", [
    ("decimal", ["1", "2", "3"]), ("decimal_dot", ["1.", "2.", "3."]),
    ("decimal_paren", ["1)", "2)", "3)"]), ("decimal_both_parens", ["(1)", "(2)", "(3)"]),
    ("multilevel", ["1", "2", "3"]), ("multilevel_dot", ["1.", "2.", "3."]),
    ("lower_alpha", ["a", "b", "c"]), ("upper_alpha", ["A", "B", "C"]),
    ("lower_roman", ["i", "ii", "iii"]), ("upper_roman", ["I", "II", "III"]),
])
def test_all_formats_native(project, format, expected):
    enable(project, {"levels": {"h1": {"format": format}}})
    for i in range(3):
        project.add(f"chapter-{i}", text=f"# Chapter {i}")
    successful(project, strict=True)
    assert labels(project) == expected
    assert [p.text for p in Document(project.output).paragraphs] == [f"Chapter {i}" for i in range(3)]
    assert all(h["native"] for h in inspect_heading_numbering(project.output))
    assert len(set(h["num_id"] for h in inspect_heading_numbering(project.output))) == 1


def test_unified_structure_and_markdown_reset(project):
    enable(project)
    chapter = project.add(text="# Main\n\n## Local\n\n### A\n\n### B\n\n## Next")
    project.add("section", "section", "## From manifest\n\n### C", parent=chapter)
    project.add("two", text="# Second\n\n## Local\n\n### D")
    successful(project, strict=True)
    assert labels(project) == ["1", "1.1", "1.1.1", "1.1.2", "1.2", "1.3", "1.3.1", "2", "2.1", "2.1.1"]
    assert len(set(h["num_id"] for h in inspect_heading_numbering(project.output))) == 1


def test_mixed_level_format_template_separator_tab(project):
    enable(project, {"separator": "/", "number_text_separator": "tab", "levels": {
        "h1": {"format": "upper_roman"}, "h2": {"format": "lower_alpha", "template": "({path})"},
        "h3": {"format": "decimal_paren", "template": "{path}."}}})
    project.add(text="# Main\n\n## A\n\n### Sub")
    successful(project)
    assert labels(project) == ["I", "(I/a)", "I/a/1."]
    assert all(h["suffix"] == "tab" for h in inspect_heading_numbering(project.output))


def test_continue_between_files_and_restart_parent(project):
    enable(project)
    parent = project.add(text="# Main\n\n## First")
    project.add("chunk", "content", "## Second\n\n### Detail", parent=parent)
    project.add("two", text="# Two\n\n## First")
    successful(project)
    assert labels(project) == ["1", "1.1", "1.2", "1.2.1", "2", "2.1"]


def test_continue_child_counter_on_new_chapter(project):
    enable(project, {"levels": {"h2": {"restart": "continue"}}})
    project.add(text="# Main\n\n## One\n\n## Two")
    project.add("two", text="# Second\n\n## Three")
    successful(project)
    assert labels(project) == ["1", "1.1", "1.2", "2", "2.3"]


def test_start_reset_and_per_file_overrides(project):
    enable(project)
    project.add(text="# One\n\n## A")
    project.add("two", text="# Two\n\n## B", heading_numbering={"levels": {"h2": {"format": "multilevel_dot"}}})
    project.add("three", text="# Three\n\n## C", numbering={"format": "decimal_paren"})
    project.add("four", text="# Four\n\n## D", numbering={"start": 7, "reset": True})
    successful(project)
    assert labels(project) == ["1", "1.1", "2", "2.1.", "3)", "3.1", "7", "7.1"]


def test_hidden_and_excluded_headings_skipped_levels(project):
    enable(project)
    project.add(text='# Main\n\n<!-- md2doc-numbering {"display": false} -->\n## Hidden\n\n### Child\n\n<!-- md2doc-numbering {"enabled": false} -->\n## Excluded\n\n#### Skipped\n\n## Last')
    successful(project, strict=True)
    assert labels(project) == ["1", "", "1.1.1", "", "1.1", "1.2"]
    data = inspect_heading_numbering(project.output)
    assert data[1]["native"] and data[3]["num_id"] == "0"


def test_local_override_and_precedence(project):
    enable(project, {"levels": {"h2": {"template": "{path}."}}})
    project.manifest["defaults"]["heading_numbering"] = {"levels": {"h2": {"template": "{path})"}}}
    project.add(text='# Main\n\n## Element\n\n<!-- md2doc-numbering {"template": "({n})", "start": 5, "reset": true} -->\n## Local\n\n## Next',
                heading_numbering={"levels": {"h2": {"template": "[{path}]"}}})
    successful(project)
    assert labels(project) == ["1", "[1.1]", "(5)", "[1.6]"]


def test_frontmatter_appendices_and_excluded_structural(project):
    enable(project)
    project.add("title", "title_page", "# Title")
    project.add("intro", "frontmatter", "# Intro\n\n## Local intro")
    project.add(text="# Main\n\n## Body", numbering={"enabled": False})
    project.add("numbered", text="# Numbered\n\n## Body")
    project.add("end", "content", "# Conclusion", heading_numbering={"enabled": False})
    appendix = project.add("appendix", "appendix", "# Appendix\n\n## Local appendix")
    project.add("app-section", "section", "## Section", parent=appendix)
    successful(project)
    assert labels(project) == ["", "", "", "", "1", "1", "1.1", "", "Приложение A —", "A.1", "A.2"]


def test_disabled_level_and_transparent_parent(project):
    enable(project, {"levels": {"h2": {"enabled": False}}})
    project.add(text="# Main\n\n## Hidden\n\n### One\n\n### Two")
    successful(project)
    assert labels(project) == ["1", "", "1.1", "1.2"]


def test_lists_unchanged_by_headings(project):
    project.add(text="# Main\n\n## Local\n\n1. A\n2. B\n\n- X\n  - Y")
    successful(project)
    old = xpath(project.output, "//w:abstractNum/w:lvl[w:numFmt[@w:val='bullet']]/w:lvlText/@w:val", "word/numbering.xml")
    enable(project)
    successful(project)
    assert xpath(project.output, "//w:abstractNum/w:lvl[w:numFmt[@w:val='bullet']]/w:lvlText/@w:val", "word/numbering.xml") == old
    assert len(xpath(project.output, "//w:p[not(w:pPr/w:outlineLvl)]/w:pPr/w:numPr")) == 4


@pytest.mark.parametrize("option", [
    {"format": "bad"}, {"template": "{unknown}"}, {"template": "%1"},
    {"start": 0}, {"start": True}, {"restart": "bad"}, {"number_text_separator": "bad"},
    {"levels": {"h7": {}}}, {"levels": {"h2": {"typo": True}}}, {"separator": "%"},
])
def test_invalid_options_strict_rejects(project, option):
    enable(project, option)
    project.add()
    report, code = project.build(strict=True, validate_only=True)
    assert code == 1
    assert report.errors and report.errors[0].code != "E_INTERNAL"


def test_directive_in_code_literal_and_bad_directive_rejected(project):
    enable(project)
    project.add(text='# Main\n\n```text\n<!-- md2doc-numbering {"bad":true} -->\n```')
    successful(project)
    (project.root / "content/one.md").write_text('# Main\n\n<!-- md2doc-numbering {"bad":true} -->\n## Local', encoding="utf-8")
    report, code = project.build()
    assert code == 1 and "E_FIELD" in [d.code for d in report.errors]


def test_old_schema_rejects_extension_and_no_external_validator(project, monkeypatch):
    project.add()
    monkeypatch.setenv("MD2DOC_VALIDATOR", "C:/does-not-exist/validate.py")
    successful(project, strict=True)
    styles = project.config()
    styles["heading_numbering"] = {"enabled": True}
    project.write(styles)
    report, code = project.build()
    assert code == 1 and "E_SCHEMA_EXTENSION" in [d.code for d in report.errors]


def test_element_wide_setting_beats_global_level_setting(project):
    enable(project, {"levels": {"h2": {"format": "decimal", "template": "{path}"}}})
    project.add(text="# Main\n\n## Local", heading_numbering={"template": "({n})"})
    successful(project)
    assert labels(project) == ["(1)", "(1)"]


def test_native_sequence_renumbers_inserted_heading(project):
    from copy import deepcopy
    enable(project)
    project.add(text="# Main\n\n## One\n\n## Two\n\n## Three")
    successful(project)
    doc = Document(project.output)
    copied = deepcopy(doc.paragraphs[1]._p)
    doc.paragraphs[1]._p.addnext(copied)
    doc.save(project.output)
    assert labels(project) == ["1", "1.1", "1.2", "1.3", "1.4"]


def test_central_delivery_and_tampered_definition(project):
    from md2doc.diagnostics.delivery import verify_delivery
    from zipfile import ZipFile
    enable(project)
    project.add(text="# Main\n\n## Local")
    successful(project)
    report, headings, code = verify_delivery(project.root, strict=True)
    assert code == 0 and [h["label"] for h in headings] == ["1", "1.1"]
    with ZipFile(project.output) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/numbering.xml"] = parts["word/numbering.xml"].replace(b'w:val="%1.%2"', b'w:val="%1-%2"')
    with ZipFile(project.output, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    report, _, code = verify_delivery(project.root, strict=True)
    assert code == 1 and report.errors[-1].code == "E_DELIVERY_NUMBERING"


def test_counter_range_and_bad_placement(project):
    enable(project, {"levels": {"h1": {"start": 32767}}})
    project.add()
    project.add("two", text="# Second")
    report, code = project.build(validate_only=True)
    assert code == 1 and report.errors[-1].code == "E_COUNTER_RANGE"


def test_central_verifier_cli_input_only(project, monkeypatch):
    project.add()
    project.save()
    env = {**os.environ, "MD2DOC_VALIDATOR": "C:/missing.py"}
    command = Path(__file__).resolve().parents[1] / "tools/verify_delivery"
    result = subprocess.run([sys.executable, str(command), str(project.root), "--input-only", "--strict"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "validated" in result.stdout


def test_word_letter_rollover_and_inline_code_directive(project):
    enable(project, {"levels": {"h1": {"format": "upper_alpha", "start": 27}}})
    project.add(text='# Main\n\nLiteral `<!-- md2doc-numbering {"bad":true} -->`')
    project.add("two", text="# Next")
    successful(project)
    assert labels(project) == ["AA", "BB"]
