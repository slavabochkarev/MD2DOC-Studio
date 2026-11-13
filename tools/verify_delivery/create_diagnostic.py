"""Create a small, reproducible native H1-H4 DOCX for manual Word checking.

Uses the repository's existing baseline profile; never launches Word.
python tools/verify_delivery/create_diagnostic.py [OUTPUT_DIRECTORY]
"""
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from md2doc.core.builder import build_project
from md2doc.diagnostics.delivery import verify_delivery


def create_diagnostic(destination):
    destination = Path(destination).resolve()
    project = destination / "diagnostic-project"
    (project / "content").mkdir(parents=True, exist_ok=True)
    (project / "output").mkdir(exist_ok=True)

    def write(name, value):
        (project / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name in ("styles.yaml", "metadata.yaml"):
        value = json.loads((REPO / "tests/fixtures" / name).read_text(encoding="utf-8"))
        value["schema_version"] = "0.2"
        if name == "styles.yaml":
            value["heading_numbering"] = {"enabled": True, "separator": ".", "number_text_separator": "space",
                "levels": {f"h{i}": {"enabled": i <= 4, "format": "decimal", "template": "{path}"} for i in range(1, 7)}}
        else:
            value["title"] = "Диагностика нумерации Word H1–H4"
        write(name, value)
    elements = []
    for index in (1, 2):
        text = (f"# Глава {index}\n\n## Раздел\n\n### Подраздел\n\n#### Первый пункт\n\n"
                "Проверьте номер четвёртого уровня над этим абзацем.\n\n"
                "#### Второй пункт\n\n## Следующий раздел\n\n### Следующий подраздел\n\n#### Пункт\n")
        if index == 2:
            text += "\nОбычные списки используют отдельные определения:\n\n1. Первый элемент.\n2. Второй элемент.\n\n- Первый маркер.\n- Второй маркер.\n"
        source = f"content/chapter-{index}.md"
        (project / source).write_text(text, encoding="utf-8")
        elements.append({"id": f"chapter-{index}", "type": "chapter", "source": source,
                         "heading": {"from": "markdown", "level": 1}, "page_break": {"before": index == 2}})
    write("document.yaml", {"schema_version": "0.2", "id": "word-numbering-diagnostic", "language": "ru-RU",
          "metadata": "metadata.yaml", "styles": "styles.yaml", "build": {"output_dir": "output", "output_name": "diagnostic.docx"},
          "defaults": {"numbering": {"enabled": True, "format": "decimal", "scope": "siblings"}, "style": {"body": "body"}},
          "elements": elements})
    output = destination / "heading-numbering-H1-H4.docx"
    report, code = build_project(project, output=output, strict=True)
    if code:
        raise RuntimeError(report.errors)
    report, headings, code = verify_delivery(project, output=output, strict=True)
    if code:
        raise RuntimeError(report.errors)
    (destination / "diagnostic-expected.json").write_text(json.dumps({
        "output": str(output), "headings": headings,
        "word_visual_status": "not_run; open manually and confirm numbering/renumbering"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return output


if __name__ == "__main__":
    create_diagnostic(sys.argv[1] if len(sys.argv) > 1 else REPO / "qa/numbering-fix")
