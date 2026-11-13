import io
import os
from pathlib import Path
import re
import sys

from defusedxml import ElementTree
from PIL import Image

from md2doc.diagnostics.report import BuildError

_dll_handles = []
_cairo_directories = set()


def prepare_cairo():
    """Use an explicitly configured DLL directory or the selected runtime's Cairo.

    No downloads, install attempts, shell commands, or arbitrary DLL search paths.
    """
    if os.name != "nt":
        return
    configured = os.environ.get("MD2DOC_CAIRO_DLL_DIR")
    directory = Path(configured) if configured else Path(sys.base_prefix).parent / "native/poppler/Library/bin"
    if directory in _cairo_directories:
        return
    if (directory / "cairo.dll").is_file():
        _dll_handles.append(os.add_dll_directory(str(directory)))
        _cairo_directories.add(directory)
        # cairocffi's ctypes.find_library searches PATH on Windows.
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")


def image_data(path):
    try:
        raw = path.read_bytes()
        if path.suffix.lower() == ".svg":
            tree = ElementTree.fromstring(raw)
            for node in tree.iter():
                tag = node.tag.rsplit("}", 1)[-1].lower()
                if tag in ("script", "foreignobject") or any(k.lower().startswith("on") for k in node.attrib):
                    raise ValueError("Active SVG content is forbidden")
                for key, value in node.attrib.items():
                    if key.rsplit("}", 1)[-1] in ("href", "src") and value and not value.startswith("#"):
                        raise ValueError("SVG external or embedded resources are forbidden")
            if re.search(rb"@import|url\(\s*['\"]?(?!#)", raw, re.I):
                raise ValueError("External SVG CSS resources are forbidden")

            def deny_fetch(url, resource_type):
                raise ValueError("SVG resource fetching is disabled")

            prepare_cairo()
            from cairosvg.surface import PNGSurface
            raw = PNGSurface.convert(bytestring=raw, url_fetcher=deny_fetch, unsafe=False)
        with Image.open(io.BytesIO(raw)) as image:
            image.load()  # Reject invalid binary image content before publishing.
            dpi = image.info.get("dpi", (96, 96))
            natural_width_pt = image.width / max(float(dpi[0]), 1) * 72
            if image.format not in ("PNG", "JPEG"):
                output = io.BytesIO()
                image.convert("RGBA").save(output, format="PNG")
                raw = output.getvalue()
        return io.BytesIO(raw), natural_width_pt
    except Exception as exc:
        raise BuildError("E_IMAGE", f"Cannot embed image: {exc}. SVG requires CairoSVG and a local Cairo library.", path) from exc
