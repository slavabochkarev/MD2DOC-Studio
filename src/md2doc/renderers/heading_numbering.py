"""Compile outline plans into native, editable Word numbering streams.

An unchanged outline policy uses one numId across files. Word cannot vary a
level's format/template per paragraph within one numId: exceptional policies
open a seeded native stream. No numeric value is baked into lvlText or runs.
"""
import hashlib
import json

from docx.oxml.ns import qn

from .ooxml_extensions import apply_number, element

WORD_FORMAT = {"decimal": "decimal", "lower_alpha": "lowerLetter", "upper_alpha": "upperLetter",
               "lower_roman": "lowerRoman", "upper_roman": "upperRoman"}

# Geometry of the native multilevel list supplied by the user after applying
# Numbering in Microsoft Word. Units are twips, not Markdown heading depths.
WORD_INDENTS = ((360, 360), (792, 432), (1224, 504), (1728, 648),
                (2232, 792), (2736, 936), (3240, 1080), (3744, 1224), (4320, 1440))


def level_text(options, level):
    if not options["display"]:
        return ""
    path = options["separator"].join(f"%{i + 1}" for i in options["path_levels"])
    return options["template"].replace("{path}", path).replace("{n}", f"%{level + 1}")


class HeadingNumbering:
    def __init__(self, document):
        self.doc = document
        self.root = document.part.numbering_part.element
        self.definitions = {}
        self.key = None
        self.num_id = None
        self.counts = [None] * 6
        self.starts = [1] * 6

    def next_id(self, tag, attr):
        return max((int(n.get(qn(attr))) for n in self.root.findall(qn(tag))), default=0) + 1

    def abstract(self, key, plan):
        if key in self.definitions:
            return self.definitions[key]
        identity = self.next_id("w:abstractNum", "w:abstractNumId")
        node = element("w:abstractNum", w_abstractNumId=identity)
        digest = hashlib.sha256(key.encode()).hexdigest()
        node.append(element("w:nsid", w_val=digest[:8].upper()))
        node.append(element("w:multiLevelType", w_val="multilevel"))
        node.append(element("w:tmpl", w_val=digest[8:16].upper()))
        node.append(element("w:name", w_val="MD2DOC Headings direct " + digest[:12]))
        # Word's working list has all nine levels. Markdown exposes H1-H6;
        # the last three are reserved and never consume model counters.
        options_list = plan.levels + [dict(plan.levels[-1], format="decimal", start=1,
                                         restart="parent", path_levels=list(range(i + 1)))
                                    for i in range(6, 9)]
        for index, options in enumerate(options_list):
            level = element("w:lvl", w_ilvl=index)
            level.append(element("w:start", w_val=options["start"]))
            level.append(element("w:numFmt", w_val=WORD_FORMAT[options["format"]]))
            # Word's normal parent/higher-level reset is the default when
            # lvlRestart is absent. Explicit positive values in our old
            # profile were read back by Word as numFmt=none/empty lvlText
            # for the nested levels (user-supplied Report3.docx).
            # Only the exceptional never-restart policy needs an element.
            if index and options["restart"] == "continue":
                level.append(element("w:lvlRestart", w_val=0))
            level.append(element("w:suff", w_val=options["number_text_separator"] if options["display"] else "nothing"))
            if options["number_text_separator"] == "none":
                level[-1].set(qn("w:val"), "nothing")
            level.append(element("w:lvlText", w_val=level_text(options, index)))
            level.append(element("w:lvlJc", w_val="left"))
            ppr = element("w:pPr")
            left, hanging = WORD_INDENTS[index]
            ppr.append(element("w:ind", w_left=left, w_hanging=hanging))
            level.append(ppr)
            node.append(level)
        first = self.root.find(qn("w:num"))
        first.addprevious(node) if first is not None else self.root.append(node)
        self.definitions[key] = identity
        return identity

    def apply(self, paragraph, plan):
        key = json.dumps([plan.family, [(o["format"], o["start"], o["restart"], o["number_text_separator"] if o["display"] else "none", level_text(o, i))
                                        for i, o in enumerate(plan.levels)]], ensure_ascii=False)
        predicted = self.counts.copy()
        for i in range(plan.level + 1, 6):
            if plan.levels[i]["restart"] == "parent":
                predicted[i] = None
        predicted[plan.level] = predicted[plan.level] + 1 if predicted[plan.level] is not None else self.starts[plan.level]
        matches = predicted[plan.level] == plan.value and all((predicted[i] if predicted[i] is not None else self.starts[i]) == n for i, n, _ in plan.path if i != plan.level)
        if key != self.key or plan.reset or not matches:
            identity = self.abstract(key, plan)
            self.num_id = self.next_id("w:num", "w:numId")
            node = element("w:num", w_numId=self.num_id)
            node.append(element("w:abstractNumId", w_val=identity))
            for index, value in enumerate(plan.values):
                if not value or value == plan.levels[index]["start"]:
                    continue
                override = element("w:lvlOverride", w_ilvl=index)
                override.append(element("w:startOverride", w_val=value or plan.levels[index]["start"]))
                node.append(override)
            self.root.append(node)
            self.key = key
            self.starts = [value or plan.levels[i]["start"] for i, value in enumerate(plan.values)]
            predicted = [None] * 6
            predicted[plan.level] = plan.value
        self.counts = predicted
        apply_number(paragraph, self.num_id, plan.level)
        # As in the user's working Word list, numPr belongs to paragraphs.
        # Heading styles retain semantic outline levels, but do not select
        # another numbering route through style numPr and lvl/pStyle.
