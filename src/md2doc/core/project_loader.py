from pathlib import Path

from md2doc.config.loader import clean_extensions, validate


def load_project(project, report):
    root = Path(project).resolve()
    module, validator, manifest = validate(root, report)
    return root, module, validator, manifest, clean_extensions(validator.metadata), clean_extensions(validator.styles)
