def alpha(value):
    result = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def numbered_siblings(nodes, inherited, prefix="", parent_kind=None):
    """Yield (node, effective settings, number); counters belong to siblings."""
    counters = {"chapter": 0, "section": 0, "appendix": 0}
    for node in nodes:
        if not node.get("enabled", True):
            continue
        settings = {**inherited, **node.get("numbering", {})}
        if parent_kind == "appendix" and "format" not in node.get("numbering", {}):
            settings["format"] = "decimal"
        kind = node["type"]
        number = ""
        if kind in counters and settings["enabled"]:
            counters[kind] += 1
            segment = alpha(counters[kind]) if kind == "appendix" else str(counters[kind])
            number = f"{prefix}.{segment}" if prefix else segment
        yield node, settings, number
