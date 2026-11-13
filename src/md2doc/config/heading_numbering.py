"""Schema and normalization of the opt-in Format 0.2 numbering extension."""
from copy import deepcopy
import json
import re

FORMATS = {
    "decimal": ("decimal", "{n}"), "decimal_dot": ("decimal", "{n}."),
    "decimal_paren": ("decimal", "{n})"), "decimal_both_parens": ("decimal", "({n})"),
    "multilevel": ("decimal", "{path}"), "multilevel_dot": ("decimal", "{path}."),
    "lower_alpha": ("lower_alpha", "{n}"), "upper_alpha": ("upper_alpha", "{n}"),
    "lower_roman": ("lower_roman", "{n}"), "upper_roman": ("upper_roman", "{n}"),
}
COMMON = {"enabled", "display", "format", "template", "start", "restart", "number_text_separator"}
DIRECTIVE = re.compile(r'^\s*<!-- md2doc-numbering (.*?) -->\s*$')


def check_options(v, data, where, full=True):
    if not isinstance(data, dict):
        v.error("E_TYPE", where, "expected a numbering object")
        return
    allowed = COMMON | ({"separator", "levels", "reset"} if full else {"reset"})
    for key, value in data.items():
        pos = f"{where}.{key}"
        if key.startswith("x-"):
            v.warn("W_EXTENSION", pos, "extension ignored")
        elif key not in allowed:
            v.error("E_FIELD", pos, "unknown numbering setting")
        elif key in ("enabled", "display", "reset") and type(value) is not bool:
            v.error("E_TYPE", pos, "expected boolean")
        elif key == "format" and (not isinstance(value, str) or value not in FORMATS):
            v.error("E_NUMBER_FORMAT", pos, "unknown number format")
        elif key == "start" and (type(value) is not int or not 1 <= value <= 32767):
            v.error("E_NUMBER_START", pos, "expected integer in 1..32767")
        elif key == "restart" and value not in ("parent", "continue"):
            v.error("E_NUMBER_RESTART", pos, "expected parent or continue")
        elif key == "number_text_separator" and value not in ("space", "tab", "none"):
            v.error("E_NUMBER_SEPARATOR", pos, "expected space, tab or none")
        elif key == "separator" and (not isinstance(value, str) or not 1 <= len(value) <= 8 or any(c in value for c in "%{}\t\r\n") or any(ord(c) < 32 for c in value)):
            v.error("E_NUMBER_SEPARATOR", pos, "expected 1..8 literal characters, without %, braces or control characters")
        elif key == "template":
            if (not isinstance(value, str) or not value or len(value) > 120
                    or not ("{n}" in value or "{path}" in value)
                    or any(c in value.replace("{n}", "").replace("{path}", "") for c in "{}%\r\n\t")):
                v.error("E_NUMBER_TEMPLATE", pos, "use a nonempty literal template containing {n} or {path}; other tokens and % are forbidden")
        elif key == "levels":
            if not isinstance(value, dict):
                v.error("E_TYPE", pos, "expected h1..h6 mapping")
            else:
                for level, options in value.items():
                    if level not in [f"h{i}" for i in range(1, 7)]:
                        v.error("E_NUMBER_LEVEL", f"{pos}.{level}", "expected h1..h6")
                    else:
                        check_options(v, options, f"{pos}.{level}", False)


def directive_options(line):
    match = DIRECTIVE.fullmatch(line)
    if not match:
        return None

    def pairs(items):
        result = {}
        for k, value in items:
            if k in result:
                raise ValueError(f"Duplicate numbering key: {k}")
            result[k] = value
        return result
    return json.loads(match[1], object_pairs_hook=pairs)


def validate_directives(validator, text, where):
    lines = text.splitlines()
    fence = None
    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if fence or not line.lstrip().startswith("<!-- md2doc-numbering"):
            continue
        context = f"{where}:{index + 1}"
        if validator.schema_version != "0.2":
            validator.error("E_SCHEMA_EXTENSION", context, "numbering directives require schema_version 0.2")
        try:
            data = directive_options(line)
            if data is None:
                raise ValueError("expected <!-- md2doc-numbering {JSON object} -->")
            check_options(validator, data, context, False)
        except (ValueError, TypeError) as exc:
            validator.error("E_NUMBER_DIRECTIVE", context, str(exc))
        following = next((s for s in lines[index + 1:] if s.strip()), "")
        if not re.match(r"^ {0,3}#{1,6}\s+", following):
            validator.error("E_NUMBER_DIRECTIVE", context, "directive must immediately precede an ATX heading (blank lines allowed)")
        lines[index] = ""  # Same line count, same slugs and source positions.
    return "\n".join(lines)


def merge_options(base, extra):
    result = deepcopy(base)
    # Layer priority precedes level specificity: an element-wide override must
    # beat level settings inherited from styles/defaults. Its own levels still
    # apply last within the same layer.
    common = {k: v for k, v in extra.items() if k in COMMON}
    if common and "levels" in result:
        result["levels"] = {level: merge_options(values, common) for level, values in result["levels"].items()}
    for key, value in extra.items():
        if key == "levels":
            for level, values in value.items():
                result.setdefault("levels", {})[level] = merge_options(result.get("levels", {}).get(level, {}), values)
        else:
            result[key] = deepcopy(value)
    # Format aliases supply their template only at the layer that declares them.
    if "format" in extra and "template" not in extra:
        result["template"] = FORMATS[extra["format"]][1]
    return result


def level_options(config, level):
    base = {"enabled": True, "display": True, "format": "decimal", "template": "{path}",
            "start": 1, "restart": "parent", "number_text_separator": "space"}
    base = merge_options(base, {k: v for k, v in config.items() if k in COMMON})
    return merge_options(base, config.get("levels", {}).get(f"h{level}", {}))


def native_enabled(manifest, styles):
    return manifest["schema_version"] == "0.2"  # Explicit opt-in, including legacy structural settings.
