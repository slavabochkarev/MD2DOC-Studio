"""Real nine-file reference, always copied outside doc1 before modifications."""
import hashlib
import json
import os
from pathlib import Path
import shutil

from docx import Document
from docx.shared import Mm
import pytest

from md2doc.core.builder import build_project
from md2doc.renderers.integrity import verify_docx
from conftest import xpath


REFERENCE = Path(os.environ.get('MD2DOC_DOC1_PROJECT', ''))


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and "output" not in p.relative_to(root).parts and "__pycache__" not in p.parts}


@pytest.mark.skipif(not os.environ.get('MD2DOC_DOC1_PROJECT') or not (REFERENCE / "document.yaml").is_file(), reason="Optional MD2DOC_DOC1_PROJECT is not configured")
def test_reference_and_changed_yaml_outside_source(tmp_path):
    original = hashes(REFERENCE)
    project = tmp_path / "reference-copy"
    shutil.copytree(REFERENCE, project, ignore=shutil.ignore_patterns("output", ".git", "__pycache__"))
    (project / "output").mkdir()
    output = project / "output/doc1.docx"
    report, code = build_project(project, output=output, strict=True)
    assert code == 0, report.errors
    assert (report.processed_files, report.sections, report.tables, report.images) == (9, 8, 1, 1)
    verify_docx(output)
    doc = Document(output)
    headings = [p.text for p in doc.paragraphs if p._p.xpath("./w:pPr/w:outlineLvl")]
    assert headings == ["Демонстрационный документ MD2DOC", "Аннотация", "Введение", "1 Обзор формата", "1.1 Детали представления", "Табличные данные", "Исходный код", "2 Архитектура проекта", "Поток обработки", "Заключение", "Приложение A — Пример состава поставки", "Приложение B — Контрольный список"]
    assert len(doc.tables) == 1 and len(doc.inline_shapes) == 1
    assert len(xpath(output, "//w:hyperlink[@w:anchor]")) == 7
    baseline_size = xpath(output, "//w:style[@w:styleId='Normal']/w:rPr/w:sz/@w:val", "word/styles.xml")
    styles = json.loads((project / "styles.yaml").read_text(encoding="utf-8"))
    styles["font"]["size"] = 12
    styles["page"]["margins"]["left"] = "40mm"
    styles["paragraph"]["space_after"] = 7
    (project / "styles.yaml").write_text(json.dumps(styles, ensure_ascii=False), encoding="utf-8")
    report, code = build_project(project, output=output, strict=True)
    assert code == 0, report.errors
    assert xpath(output, "//w:style[@w:styleId='Normal']/w:rPr/w:sz/@w:val", "word/styles.xml") == ["24"] != baseline_size
    assert xpath(output, "//w:pgMar/@w:left") == [str(Mm(40).twips)]
    assert xpath(output, "//w:style[@w:styleId='Normal']/w:pPr/w:spacing/@w:after", "word/styles.xml") == ["140"]
    assert hashes(REFERENCE) == original
