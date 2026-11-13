import hashlib
import os
from pathlib import Path
import shutil

import pytest

from md2doc.core.builder import build_project
from md2doc.diagnostics.delivery import verify_delivery

ECO = Path(os.environ.get('MD2DOC_ECOBURO_PROJECT', ''))


@pytest.mark.skipif(not os.environ.get('MD2DOC_ECOBURO_PROJECT') or not (ECO / "document.yaml").is_file(), reason="Optional MD2DOC_ECOBURO_PROJECT is not configured")
def test_real_ecoburo_on_disposable_copy(tmp_path, monkeypatch):
    original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ECO / "daily").glob("*.md")}
    root = tmp_path / "reports"
    shutil.copytree(ECO, root, ignore=shutil.ignore_patterns("output", ".git", "__pycache__"))
    (root / "output").mkdir()
    monkeypatch.setenv("MD2DOC_VALIDATOR", "C:/missing-validator.py")
    report, code = build_project(root, strict=True)
    assert code == 0 and (report.processed_files, report.tables) == (5, 1), report.errors
    report, headings, code = verify_delivery(root, strict=True)
    assert code == 0, report.errors
    numbered = [h for h in headings if h["native"]]
    assert numbered[0]["label"] == "1"
    assert numbered[1]["label"] == "1.1"
    assert numbered[2]["label"] == "1.1.1"
    assert any(h["label"] == "2.1.1" for h in numbered)
    assert headings[0]["label"] == headings[-1]["label"] == ""
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ECO / "daily").glob("*.md")} == original
