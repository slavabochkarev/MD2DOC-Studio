"""Compatibility filename for the centralized tools/verify_delivery CLI."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_suffix("") / "__main__.py"), run_name="__main__")
