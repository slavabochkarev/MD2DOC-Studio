"""python tools/verify_delivery PROJECT [--output DOCX] [--strict]."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from md2doc.diagnostics.delivery import verify_delivery


def main(argv=None):
    parser = argparse.ArgumentParser(description="Central MD2DOC delivery verifier (same packaged input validator)")
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--input-only", action="store_true")
    parser.add_argument("--json", type=Path, help="Optional verification evidence destination")
    args = parser.parse_args(argv)
    report, headings, code = verify_delivery(args.project, args.output, args.strict, args.input_only)
    for item in report.errors + report.warnings:
        print(f"{item.code} {item.source or ''}: {item.message}", file=sys.stderr)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(report)
        data.pop("_started")
        data["headings"] = headings
        data["verification_scope"] = "static OPC, OOXML and numbering/style graph"
        data["word_visual_status"] = "not_run; user confirmation required"
        args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MD2DOC delivery: {report.status}; files={report.processed_files}, headings={len(headings)}, errors={len(report.errors)}, warnings={len(report.warnings)}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
