"""Read actual Word numbering definitions, independent from the source planner."""
import re
from zipfile import ZipFile

from lxml import etree

from md2doc.core.heading_numbering import numeral
from md2doc.renderers.integrity import NS

WORD_FORMATS = {"decimal": "decimal", "lowerLetter": "lower_alpha", "upperLetter": "upper_alpha",
                "lowerRoman": "lower_roman", "upperRoman": "upper_roman"}


def inspect_heading_numbering(path):
    with ZipFile(path) as archive:
        doc = etree.fromstring(archive.read("word/document.xml"))
        numbering = etree.fromstring(archive.read("word/numbering.xml"))
        styles = etree.fromstring(archive.read("word/styles.xml"))
    from .numbering_graph import NumberingGraph
    graph = NumberingGraph(doc, numbering, styles)
    abstracts, nums = graph.abstracts, graph.nums
    states = {}
    result = []

    def value(node, expr, default=None):
        return next(iter(node.xpath(expr + "/@w:val", namespaces=NS)), default)

    for p in doc.findall(".//w:p", NS):
        num_id, level, outline, _, native = graph.paragraph(p)
        if outline is None or not 0 <= int(outline) < 6:
            continue
        label = ""
        if num_id == "0":
            level = int(outline)
        suffix = ""
        if num_id != "0":
            num = nums[num_id]
            definition = abstracts[value(num, "./w:abstractNumId")]
            levels = graph.levels(num_id)
            if native and set(levels) not in (set(range(6)), set(range(9))):
                raise ValueError("Heading abstractNum must define levels 0..5 or 0..8")
            if level not in levels:
                raise ValueError("Paragraph references an undefined numbering level")
            overrides = {int(n.get(f"{{{NS['w']}}}ilvl")): n for n in num.xpath("./w:lvlOverride", namespaces=NS)}
            starts = {i: int(value(overrides[i], "./w:startOverride", value(lvl, "./w:start", "1"))) if i in overrides else int(value(lvl, "./w:start", "1")) for i, lvl in levels.items()}
            state = states.setdefault(num_id, {})
            for i, lvl in levels.items():
                restart = int(value(lvl, "./w:lvlRestart", str(i)))
                if i > level and restart and level < restart:
                    state.pop(i, None)
            state[level] = state[level] + 1 if level in state else starts[level]
            template = value(levels[level], "./w:lvlText", "")
            if native:
                for token in re.findall(r"%([1-9])", template):
                    if int(token) - 1 > level or int(token) - 1 not in levels:
                        raise ValueError("Heading lvlText references a deeper/undefined level")
                if any(value(lvl, "./w:numFmt") not in WORD_FORMATS for lvl in levels.values()):
                    raise ValueError("Unsupported heading numFmt")
            label = re.sub(r"%([1-9])", lambda m: numeral(state.get(int(m[1]) - 1, starts[int(m[1]) - 1]), WORD_FORMATS[value(levels[int(m[1]) - 1], "./w:numFmt")]), template)
            suffix = value(levels[level], "./w:suff", "tab")
        result.append({"text": "".join(p.xpath(".//w:t/text()", namespaces=NS)), "label": label,
                       "num_id": num_id, "level": level, "native": native, "suffix": suffix})
    return result
