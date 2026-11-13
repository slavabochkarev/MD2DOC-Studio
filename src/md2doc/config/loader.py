"""Diagnostics adapter to the single in-package input validator (0.1/0.2)."""
from pathlib import Path

from md2doc.diagnostics.report import BuildError, Diagnostic


def validator_module():
    # MD2DOC_VALIDATOR is intentionally ignored: no project or environment can
    # inject executable validator code or introduce a cross-project dependency.
    from . import validation as module
    return module


def clean_extensions(value):
    if isinstance(value, dict):
        return {k: clean_extensions(v) for k, v in value.items() if not k.startswith("x-")}
    if isinstance(value, list):
        return [clean_extensions(v) for v in value]
    return value


def validate(root, report):
    module = validator_module()

    class Adapter(module.Validator):
        def record(self, target, code, where, message):
            node = next((n for n in reversed(self.nodes) if where.startswith(n["where"])), None)
            source = str(node.get("path") or root / node["node"].get("source", "")) if node else None
            if not source:
                prefix = where.split(".")[0]
                source = str(root / {"metadata": "metadata.yaml", "styles": "styles.yaml"}.get(prefix, "document.yaml"))
            target.append(Diagnostic(code, message, source, where))

        def error(self, code, where, message):
            self.record(report.errors, code, where, message)
            super().error(code, where, message)

        def warn(self, code, where, message):
            self.record(report.warnings, code, where, message)
            super().warn(code, where, message)

    validator = Adapter(root)
    try:
        validator.run()
    except (module.ConfigError, OSError, UnicodeError, RecursionError) as exc:
        raise BuildError("E_CONFIG", str(exc), root / "document.yaml", 2) from exc
    if report.errors:
        raise BuildError("E_VALIDATION", "Project does not conform to MD2DOC Format 0.1", root)
    manifest = clean_extensions(module.load_config(root / "document.yaml"))
    return module, validator, manifest
