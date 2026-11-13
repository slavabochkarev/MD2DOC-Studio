import json
import subprocess
import sys

import pytest
import yaml

from md2doc.core.project_loader import load_project
from md2doc.diagnostics.report import BuildReport
from conftest import successful


def test_yaml_loading_and_bom(project):
    project.add()
    project.save()
    (project.root / "document.yaml").write_text("\ufeff" + yaml.safe_dump(project.manifest), encoding="utf-8")
    loaded = load_project(project.root, BuildReport(str(project.root)))
    assert loaded[3]["elements"][0]["id"] == "one"


@pytest.mark.parametrize("change,code", [
    (lambda p: p.manifest.update(schema_version="0.3"), "E_VALUE"),
    (lambda p: p.manifest.update(unknown=True), "E_FIELD"),
    (lambda p: p.manifest["elements"][0].update(source="../escape.md"), "E_PATH"),
    (lambda p: p.manifest["elements"][0].update(source="content/missing.md"), "E_MISSING"),
    (lambda p: p.manifest["elements"][0].update(type="new"), "E_VALUE"),
])
def test_invalid_config(project, change, code):
    project.add()
    change(project)
    report, result = project.build()
    assert result == 1
    assert code in [d.code for d in report.errors]
    assert not project.output.exists()
    assert json.loads((project.root / "output/build-report.json").read_text(encoding="utf-8"))["status"] == "failed"


def test_duplicate_yaml_key_exit_two(project):
    project.add()
    project.save()
    (project.root / "document.yaml").write_text('id: first\nid: second\n', encoding="utf-8")
    from md2doc.core.builder import build_project
    report, code = build_project(project.root)
    assert code == 2
    assert "Duplicate key" in report.errors[-1].message


def test_strict_and_atomic_failure(project):
    project.add()
    successful(project)
    previous = project.output.read_bytes()
    project.manifest["x-example"] = {"anything": True}
    report, code = project.build(strict=True)
    assert code == 1
    assert report.warnings[0].code == "W_EXTENSION"
    assert project.output.read_bytes() == previous
    assert not list(project.output.parent.glob(".md2doc-*"))


def test_validate_only_and_cli(project):
    project.add()
    project.save()
    result = subprocess.run([sys.executable, "-m", "md2doc", "build", str(project.root), "--validate-only", "--verbose"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "validated" in result.stdout
    assert not project.output.exists()


def test_output_protection(project):
    project.add()
    path = project.root / "content/bad.docx"
    report, code = project.build(output=path)
    assert code == 2
    assert report.errors[-1].code == "E_OUTPUT"
    assert not path.exists()


def test_project_cannot_execute_validator(project):
    project.add()
    (project.root / "tools").mkdir()
    (project.root / "tools/validate.py").write_text("raise RuntimeError('UNTRUSTED')", encoding="utf-8")
    successful(project)
