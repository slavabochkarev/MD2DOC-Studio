import os
from pathlib import Path
import tempfile

from md2doc.diagnostics.report import BuildError, BuildReport, Diagnostic
from md2doc.renderers.docx_renderer import DocxRenderer
from md2doc.renderers.integrity import verify_docx
from .project_loader import load_project
from .structure_builder import build_structure


def protected_output(path, root, model=None):
    path = Path(path).resolve()
    if path.suffix.lower() != ".docx":
        raise BuildError("E_OUTPUT", "Output must have the .docx extension", path, 2)
    if path.name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise BuildError("E_OUTPUT", "Reserved Windows output filename", path, 2)
    try:
        path.relative_to(root)
    except ValueError:
        return path
    # CLI overrides must never turn source directories into output locations.
    allowed = (root / model.manifest["build"]["output_dir"]).resolve() if model else root / "output"
    try:
        path.relative_to(allowed)
    except ValueError as exc:
        raise BuildError("E_OUTPUT", "Writing inside the project is allowed only in its build output directory", path, 2) from exc
    return path


def build_project(project, output=None, strict=False, validate_only=False):
    root = Path(project).resolve()
    report = BuildReport(str(root))
    # Even invalid configs get diagnostics in the conventional output directory.
    report_path = root / "output/build-report.json"
    temporary = None
    exit_code = 0
    try:
        loaded = load_project(root, report)
        model = build_structure(loaded, report)
        target = protected_output(output or root / model.manifest["build"]["output_dir"] / model.manifest["build"]["output_name"], root, model)
        report.output = str(target)
        report_path = target.parent / "build-report.json"
        if any(d.code == "W_EXCLUDED_LINK" for d in report.warnings):
            raise BuildError("E_EXCLUDED_LINK", "An enabled source links to an excluded element; fix the link before building", root)
        if validate_only:
            if strict and report.warnings:
                raise BuildError("E_STRICT", "Strict validation rejects warnings", root)
            report.status = "validated"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".md2doc-", suffix=".docx", dir=target.parent)
            os.close(fd)
            temporary = Path(name)
            DocxRenderer(model, report).render(temporary)
            verify_docx(temporary)
            if strict and report.warnings:
                raise BuildError("E_STRICT", "Strict build rejects warnings; previous DOCX retained", root)
            os.replace(temporary, target)
            report.status = "success"
    except BuildError as exc:
        if exc.diagnostic.code != "E_VALIDATION":
            report.errors.append(exc.diagnostic)
        report.status = "failed"
        exit_code = exc.exit_code
    except (OSError, ValueError, RecursionError) as exc:
        report.errors.append(Diagnostic("E_BUILD", str(exc), str(root)))
        report.status, exit_code = "failed", 2
    except Exception as exc:
        report.errors.append(Diagnostic("E_INTERNAL", f"{type(exc).__name__}: {exc}", str(root)))
        report.status, exit_code = "failed", 2
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
        # Never follow an output junction outside the input root on config errors.
        if root.is_dir():
            try:
                if report.output is None:
                    report_path.resolve().relative_to(root)
                report.write(report_path)
            except (OSError, ValueError) as exc:
                report.errors.append(Diagnostic("E_REPORT", str(exc), str(report_path)))
                report.status, exit_code = "failed", 2
    return report, exit_code
