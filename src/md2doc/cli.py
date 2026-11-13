import argparse
from pathlib import Path
import sys

from . import __version__
from .core.builder import build_project


def main(argv=None):
    parser = argparse.ArgumentParser(prog="md2doc", description="Build editable DOCX from an MD2DOC Format 0.1 project")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Validate and build a document project")
    build.add_argument("project", type=Path)
    build.add_argument("--output", type=Path, help="Override manifest DOCX output path")
    build.add_argument("--verbose", action="store_true")
    build.add_argument("--strict", action="store_true", help="Fail on any warning")
    build.add_argument("--validate-only", action="store_true", help="Validate without creating or replacing DOCX")
    args = parser.parse_args(argv)
    report, code = build_project(args.project, args.output, args.strict, args.validate_only)
    for severity, items in (("WARNING", report.warnings), ("ERROR", report.errors)):
        for item in items:
            print(f"{severity} {item.code} {item.source or ''}{' [' + item.context + ']' if item.context else ''}: {item.message}", file=sys.stderr)
    print(f"MD2DOC {__version__}: {report.status}; files={report.processed_files}, sections={report.sections}, tables={report.tables}, images={report.images}, warnings={len(report.warnings)}, errors={len(report.errors)}")
    if args.verbose:
        print(f"Project: {report.project}\nOutput: {report.output}\nDuration: {report.duration_seconds:.3f}s")
    return code
