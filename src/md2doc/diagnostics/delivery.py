"""Central delivery verification using the same packaged input validator/model."""
from pathlib import Path

from md2doc.core.project_loader import load_project
from md2doc.core.structure_builder import build_structure
from md2doc.core.heading_numbering import walk_blocks
from md2doc.diagnostics.report import BuildError, BuildReport, Diagnostic
from md2doc.renderers.integrity import verify_docx
from .numbering_inspector import inspect_heading_numbering


def verify_delivery(project, output=None, strict=False, input_only=False):
    root = Path(project).resolve()
    report = BuildReport(str(root))
    headings = []
    try:
        model = build_structure(load_project(root, report), report)
        target = Path(output).resolve() if output else root / model.manifest["build"]["output_dir"] / model.manifest["build"]["output_name"]
        report.output = str(target)
        if not input_only:
            verify_docx(target)
            headings = inspect_heading_numbering(target)
            expected = []
            for current in model.walk():
                for block in walk_blocks(current.blocks):
                    if block.kind != "heading":
                        continue
                    text = "".join(i.text if i.kind not in ("softbreak", "hardbreak") else " " if i.kind == "softbreak" and model.styles["breaks"]["soft_line_break"] == "space" else "\n" for i in block.inlines)
                    native = model.manifest["schema_version"] == "0.2"
                    label = block.heading_number.text if block.heading_number else ""
                    if not native and block.structural and current.number:
                        text = (f"Приложение {current.number} — " if current.kind == "appendix" else current.number + " ") + text
                    expected.append((text, label, native and block.heading_number is not None))
            if len(headings) != len(expected):
                raise BuildError("E_DELIVERY_HEADINGS", "Heading count differs from the project model", target)
            for actual, (text, label, native) in zip(headings, expected):
                if (actual["text"], actual["label"], actual["native"]) != (text, label, native):
                    raise BuildError("E_DELIVERY_NUMBERING", f"Heading/number differs: expected {label!r} {text!r}, got {actual['label']!r} {actual['text']!r}", target)
        if strict and report.warnings:
            raise BuildError("E_STRICT", "Strict delivery verification rejects warnings", root)
        report.status = "validated" if input_only else "verified"
        return report, headings, 0
    except BuildError as exc:
        if exc.diagnostic.code != "E_VALIDATION":
            report.errors.append(exc.diagnostic)
        report.status = "failed"
        return report, headings, exc.exit_code
    except (OSError, ValueError, KeyError) as exc:
        report.errors.append(Diagnostic("E_DELIVERY", str(exc), str(root)))
        report.status = "failed"
        return report, headings, 1
