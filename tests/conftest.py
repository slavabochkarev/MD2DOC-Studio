import json
from pathlib import Path
import shutil
from zipfile import ZipFile

from lxml import etree
import pytest

from md2doc.core.builder import build_project
from md2doc.renderers.integrity import NS


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "content").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "output").mkdir()
    fixtures = Path(__file__).parent / "fixtures"
    for name in ("metadata.yaml", "styles.yaml"):
        shutil.copyfile(fixtures / name, root / name)
    manifest = {"schema_version": "0.1", "id": "test", "language": "ru-RU",
                "metadata": "metadata.yaml", "styles": "styles.yaml",
                "build": {"output_dir": "output", "output_name": "test.docx"},
                "defaults": {"numbering": {"enabled": True, "format": "decimal", "scope": "siblings"}, "style": {"body": "body"}},
                "elements": []}
    return Project(root, manifest)


class Project:
    def __init__(self, root, manifest):
        self.root, self.manifest = root, manifest

    def add(self, identity="one", kind="chapter", text="# First\n\nBody", parent=None, **fields):
        node = {"id": identity, "type": kind, "source": f"content/{identity}.md"}
        if kind != "content":
            level = parent["heading"]["level"] + 1 if parent else 1
            node["heading"] = {"from": "markdown", "level": level}
        if kind == "appendix":
            node["numbering"] = {"format": "upper_alpha"}
        node.update(fields)
        (self.root / node["source"]).write_text(text, encoding="utf-8")
        (self.manifest["elements"] if parent is None else parent.setdefault("children", [])).append(node)
        return node

    def config(self, name="styles.yaml"):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def write(self, data, name="styles.yaml"):
        (self.root / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def save(self):
        self.write(self.manifest, "document.yaml")

    def build(self, **kwargs):
        self.save()
        report, code = build_project(self.root, **kwargs)
        return report, code

    @property
    def output(self):
        return self.root / "output/test.docx"


def xml(path, member="word/document.xml"):
    with ZipFile(path) as archive:
        return etree.fromstring(archive.read(member))


def xpath(path, expression, member="word/document.xml"):
    return xml(path, member).xpath(expression, namespaces=NS)


def paragraphs(path):
    return ["".join(p.itertext()) for p in xpath(path, "//w:body/w:p")]


def successful(project, **kwargs):
    report, code = project.build(**kwargs)
    assert code == 0, report.errors
    assert not report.errors
    return report
