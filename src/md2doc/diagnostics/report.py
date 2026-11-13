from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter

from md2doc import __version__


@dataclass
class Diagnostic:
    code: str
    message: str
    source: str | None = None
    context: str | None = None


class BuildError(Exception):
    def __init__(self, code, message, source=None, exit_code=1):
        super().__init__(message)
        self.diagnostic = Diagnostic(code, message, str(source) if source else None)
        self.exit_code = exit_code


@dataclass
class BuildReport:
    project: str
    output: str | None = None
    converter_version: str = __version__
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    processed_files: int = 0
    sections: int = 0
    tables: int = 0
    images: int = 0
    warnings: list[Diagnostic] = field(default_factory=list)
    errors: list[Diagnostic] = field(default_factory=list)
    status: str = "pending"
    duration_seconds: float = 0
    _started: float = field(default_factory=perf_counter, repr=False)

    def warn(self, code, message, source=None):
        item = Diagnostic(code, message, str(source) if source else None)
        if item not in self.warnings:
            self.warnings.append(item)

    def write(self, path: Path):
        self.duration_seconds = round(perf_counter() - self._started, 4)
        data = asdict(self)
        data.pop("_started")
        data.update(warning_count=len(self.warnings), error_count=len(self.errors))
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".report-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
