"""One ordered outline counter for both manifest and Markdown headings."""
from copy import deepcopy
from dataclasses import dataclass

from md2doc.config.heading_numbering import FORMATS, level_options, merge_options
from .numbering import alpha


def numeral(value, format):
    base = FORMATS[format][0]
    if base.endswith("alpha"):
        # Word's upperLetter/lowerLetter uses repeated letters beyond Z:
        # AA, BB, ... ZZ, AAA. Legacy 0.1 alpha() deliberately stays unchanged.
        repeat, letter = divmod(value - 1, 26)
        text = chr(65 + letter) * (repeat + 1)
        return text.lower() if base.startswith("lower") else text
    if base.endswith("roman"):
        text = ""
        remaining = value
        for n, symbol in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
            count, remaining = divmod(remaining, n)
            text += symbol * count
        return text.lower() if base.startswith("lower") else text
    return str(value)


@dataclass
class HeadingNumber:
    level: int  # zero based Word level, independent from number of path segments
    value: int
    path: tuple  # (level, value, canonical format)
    text: str
    levels: list[dict]
    values: tuple[int, ...]
    family: str
    reset: bool = False


def walk_blocks(blocks):
    for block in blocks:
        yield block
        yield from walk_blocks(block.children)


def assign_heading_numbers(model):
    counts = [0] * 6
    active = {}
    family = "document"
    for current in model.walk():
        config = current.heading_config
        protected = current.kind in ("title_page", "frontmatter")
        if current.kind == "appendix" and family != "appendix":
            family, counts, active = "appendix", [0] * 6, {}
        reset_pending = config.get("reset", False)
        for block in walk_blocks(current.blocks):
            if block.kind != "heading" or protected:
                continue
            depth = int(block.attrs["tag"][1:]) - 1
            options = level_options(config, depth + 1)
            options["enabled"] &= config.get("enabled", True)
            if block.structural:
                options = merge_options(options, {k: v for k, v in current.structural_numbering.items() if k != "scope"})
                # Old enabled=false disables the element's own heading, while
                # heading_numbering.enabled=false disables its entire source.
                options["enabled"] &= config.get("enabled", True)
            options = merge_options(options, block.numbering_override)
            levels = [level_options(config, i + 1) for i in range(6)]
            levels[depth] = options
            reset = reset_pending or options.get("reset", False)
            if reset:
                counts[depth:] = [0] * (6 - depth)
                reset_pending = False
            for i in range(depth + 1, 6):
                if levels[i]["restart"] == "parent":
                    counts[i] = 0
            active = {i: entry for i, entry in active.items() if i < depth}
            if not options["enabled"]:
                continue
            counts[depth] = counts[depth] + 1 if counts[depth] else options["start"]
            if counts[depth] > 32767:
                from md2doc.diagnostics.report import BuildError
                raise BuildError("E_COUNTER_RANGE", "Heading counter exceeds Word's supported range 1..32767", current.source)
            active[depth] = (depth, counts[depth], FORMATS[options["format"]][0])
            path = tuple(active.values())
            rendered_path = config.get("separator", ".").join(numeral(value, fmt) for _, value, fmt in path)
            text = options["template"].replace("{path}", rendered_path).replace("{n}", numeral(counts[depth], options["format"]))
            if block.structural and current.kind == "appendix" and "template" not in current.structural_numbering:
                options["template"] = "Приложение {n} —"
                text = "Приложение " + numeral(counts[depth], options["format"]) + " —"
            if not options["display"]:
                text = ""
            # Each level includes number format and literal template, never a
            # pre-rendered numeric prefix. Active ancestors determine compact
            # paths when physical H-levels are skipped or excluded.
            for i, entry in enumerate(levels):
                entry["format"] = FORMATS[entry["format"]][0]
                entry["separator"] = config.get("separator", ".")
                entry["path_levels"] = [j for j in range(i + 1) if levels[j]["enabled"]]
            levels[depth]["path_levels"] = [entry[0] for entry in path]
            # Referenced ancestors retain their actual numeric type, even when
            # the current file overrides a level's future format.
            for i, _, fmt in path:
                levels[i]["format"] = fmt
            block.heading_number = HeadingNumber(depth, counts[depth], path, text, deepcopy(levels), tuple(counts), family, reset)
