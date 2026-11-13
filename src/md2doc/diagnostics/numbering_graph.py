"""Cross-part checks for direct Word numbering and older style-linked files.

This is a structural compatibility check, not visual rendering validation.
"""
import re

from md2doc.renderers.integrity import NS


def value(node, path, default=None):
    return next(iter(node.xpath(path + "/@w:val", namespaces=NS)), default)


def attribute(node, name):
    return node.get("{" + NS["w"] + "}" + name)


def indexed(nodes, name):
    result = {}
    for node in nodes:
        key = attribute(node, name)
        if key is None or key in result:
            raise ValueError(f"Missing or duplicate {name}: {key}")
        result[key] = node
    return result


class NumberingGraph:
    def __init__(self, document, numbering, styles):
        self.document = document
        self.abstracts = indexed(numbering.findall("w:abstractNum", NS), "abstractNumId")
        self.nums = indexed(numbering.findall("w:num", NS), "numId")
        self.styles = indexed(styles.findall("w:style", NS), "styleId")
        self.heading_abstracts = {identity for identity, node in self.abstracts.items()
                                  if value(node, "./w:name", "").startswith("MD2DOC Headings ")}
        self._effective = {}
        self.validate()

    def chain(self, identity):
        seen = set()
        while identity:
            if identity in seen or identity not in self.styles:
                raise ValueError(f"Invalid style inheritance: {identity}")
            seen.add(identity)
            node = self.styles[identity]
            yield identity, node
            identity = value(node, "./w:basedOn")

    def style_value(self, identity, path):
        if not identity:
            return None
        for _, node in self.chain(identity):
            result = value(node, path)
            if result is not None:
                return result
        return None

    def abstract_id(self, num_id):
        if num_id not in self.nums:
            raise ValueError(f"Undefined numId: {num_id}")
        result = value(self.nums[num_id], "./w:abstractNumId")
        if result not in self.abstracts:
            raise ValueError(f"numId {num_id} references undefined abstractNumId {result}")
        return result

    def is_heading(self, num_id):
        return num_id != "0" and self.abstract_id(num_id) in self.heading_abstracts

    def levels(self, num_id):
        if num_id not in self._effective:
            base = self.abstracts[self.abstract_id(num_id)]
            levels = {int(k): n for k, n in indexed(base.findall("w:lvl", NS), "ilvl").items()}
            overrides = indexed(self.nums[num_id].findall("w:lvlOverride", NS), "ilvl")
            for key, node in overrides.items():
                index = int(key)
                if index not in levels:
                    raise ValueError(f"Override references undefined level {index} in numId {num_id}")
                replacement = node.find("w:lvl", NS)
                if replacement is not None:
                    if attribute(replacement, "ilvl") != key:
                        raise ValueError("lvlOverride and nested lvl have different ilvl")
                    levels[index] = replacement
                start = value(node, "./w:startOverride")
                if start is not None and int(start) < 1:
                    raise ValueError("Numbering startOverride must be positive")
            self._effective[num_id] = levels
        return self._effective[num_id]

    def associated_level(self, style_id, num_id):
        mapping = {value(level, "./w:pStyle"): i for i, level in self.levels(num_id).items()}
        for identity, _ in self.chain(style_id):
            if identity in mapping:
                return mapping[identity]
        return None

    def validate_heading_levels(self, levels, direct=False):
        expected = set(range(9 if direct else 6))
        if set(levels) != expected:
            raise ValueError("Heading abstractNum must define exactly levels " + ("0..8" if direct else "0..5"))
        for index, level in levels.items():
            sid = value(level, "./w:pStyle")
            if direct and sid is not None:
                raise ValueError("Direct heading numbering must not link levels with pStyle")
            if not direct and (sid != f"Heading{index + 1}" or sid not in self.styles):
                raise ValueError(f"Heading level {index} must link to existing paragraph style Heading{index + 1}")
            if not direct and attribute(self.styles[sid], "type") != "paragraph":
                raise ValueError(f"Heading style {sid} is not a paragraph style")
            if not direct and self.style_value(sid, "./w:pPr/w:outlineLvl") != str(index):
                raise ValueError(f"Heading style {sid} has an inconsistent outlineLvl")
            if direct:
                indent = level.find("w:pPr/w:ind", NS)
                if indent is None or any(attribute(indent, a) is None or int(attribute(indent, a)) < 0 for a in ("left", "hanging")):
                    raise ValueError("Direct heading level must define left/hanging indentation")
            if value(level, "./w:numFmt") not in ("decimal", "lowerLetter", "upperLetter", "lowerRoman", "upperRoman"):
                raise ValueError("Unsupported or missing heading numFmt")
            if int(value(level, "./w:start", "0")) < 1:
                raise ValueError("Heading start must be positive")
            restart = int(value(level, "./w:lvlRestart", str(index)))
            if not 0 <= restart <= index:
                raise ValueError(f"Invalid lvlRestart at heading level {index}")
            explicit_restart = value(level, "./w:lvlRestart")
            if explicit_restart is not None and not 0 <= int(explicit_restart) <= 7:
                raise ValueError("Word only supports explicit lvlRestart values 0..7")
            if direct and explicit_restart not in (None, "0"):
                raise ValueError("Direct heading profile must omit parent lvlRestart; only explicit 0 is supported for continue")
            template = value(level, "./w:lvlText")
            if template is None or "%" in re.sub(r"%[1-9]", "", template):
                raise ValueError("Missing or malformed heading lvlText")
            if any(int(n) - 1 > index for n in re.findall(r"%([1-9])", template)):
                raise ValueError("Heading lvlText references a deeper/undefined level")
            if value(level, "./w:suff", "tab") not in ("tab", "space", "nothing"):
                raise ValueError("Invalid heading numbering suffix")

    def validate(self):
        for identity in self.nums:
            aid = self.abstract_id(identity)
            levels = self.levels(identity)
            if aid in self.heading_abstracts:
                kind = value(self.abstracts[aid], "./w:multiLevelType")
                if kind not in ("multilevel", "hybridMultilevel"):
                    raise ValueError("Heading definition is not a multilevel list")
                direct = value(self.abstracts[aid], "./w:name", "").startswith("MD2DOC Headings direct ")
                if direct:
                    abstract = self.abstracts[aid]
                    if abstract.find("w:numStyleLink", NS) is not None or abstract.find("w:styleLink", NS) is not None:
                        raise ValueError("Direct heading numbering must not contain styleLink or numStyleLink")
                    for tag in ("nsid", "tmpl"):
                        if re.fullmatch(r"[0-9A-Fa-f]{8}", value(abstract, "./w:" + tag, "")) is None:
                            raise ValueError("Direct heading numbering requires an eight-digit hexadecimal " + tag)
                self.validate_heading_levels(levels, direct)
        for identity, node in self.styles.items():
            props = node.findall("w:pPr/w:numPr", NS)
            if len(props) > 1:
                raise ValueError(f"Duplicate numPr in style {identity}")
            num_id = value(node, "./w:pPr/w:numPr/w:numId")
            if num_id not in (None, "0"):
                self.abstract_id(num_id)
                if self.is_heading(num_id):
                    if value(self.abstracts[self.abstract_id(num_id)], "./w:name", "").startswith("MD2DOC Headings direct "):
                        raise ValueError("Direct heading numbering must not appear in style numPr")
                    if self.style_value(identity, "./w:pPr/w:numPr/w:ilvl") is not None:
                        raise ValueError(f"Word-incompatible style {identity}: ilvl inside style numPr (MS-OI29500 2.1.50); use lvl/pStyle for the style level")
                    if self.associated_level(identity, num_id) is None:
                        raise ValueError(f"Style {identity} has no associated numbering level")
        for paragraph in self.document.findall(".//w:p", NS):
            if len(paragraph.findall("w:pPr/w:numPr", NS)) > 1:
                raise ValueError("Duplicate paragraph numPr")
            num_id, level, _, _, _ = self.paragraph(paragraph)
            if num_id != "0" and level not in self.levels(num_id):
                raise ValueError("Paragraph references an undefined numbering level")

    def paragraph(self, paragraph):
        style_id = value(paragraph, "./w:pPr/w:pStyle", "Normal")
        num_id = value(paragraph, "./w:pPr/w:numPr/w:numId")
        inherited_id = self.style_value(style_id, "./w:pPr/w:numPr/w:numId")
        num_id = num_id if num_id is not None else inherited_id or "0"
        outline = value(paragraph, "./w:pPr/w:outlineLvl", self.style_value(style_id, "./w:pPr/w:outlineLvl"))
        direct = value(paragraph, "./w:pPr/w:numPr/w:ilvl")
        level = int(direct) if direct is not None else 0
        if num_id != "0":
            self.abstract_id(num_id)
            native = self.is_heading(num_id)
            if native and (outline is None or not 0 <= int(outline) < 6):
                raise ValueError("Heading numbering assigned to a paragraph without heading outlineLvl")
            associated = self.associated_level(style_id, num_id) if native else None
            if associated is not None and inherited_id not in (None, "0"):
                if direct is not None and int(direct) != associated:
                    raise ValueError(f"Paragraph ilvl conflicts with style {style_id}'s associated numbering level")
                level = associated
            if native and outline is not None and int(outline) != level:
                raise ValueError(f"Heading outlineLvl {outline} conflicts with numbering ilvl {level}")
            if native and value(self.abstracts[self.abstract_id(num_id)], "./w:name", "").startswith("MD2DOC Headings direct "):
                if direct is None or value(paragraph, "./w:pPr/w:numPr/w:numId") is None:
                    raise ValueError("Direct heading paragraph must explicitly define ilvl and numId")
                style_outline = self.style_value(style_id, "./w:pPr/w:outlineLvl")
                if style_outline is not None and style_outline != str(level):
                    raise ValueError("Heading style outlineLvl conflicts with direct numbering level")
        return num_id, level, outline, style_id, num_id != "0" and self.is_heading(num_id)
