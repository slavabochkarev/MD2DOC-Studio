from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_UNDERLINE
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Mm, Pt, RGBColor

from .ooxml_extensions import property_node

ALIGN = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
         "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}


def length(value):
    return {"mm": Mm, "cm": Cm, "pt": Pt, "in": Inches}[value[-2:]](float(value[:-2]))


def width(value, available):
    return int(available * float(value[:-1]) / 100) if value.endswith("%") else int(length(value))


def apply_font(target, settings, language):
    font = target.font
    font.name = settings["family"]
    font.size = Pt(settings["size"])
    font.color.rgb = RGBColor.from_string(settings["color"][1:])
    font.bold, font.italic, font.strike = settings["bold"], settings["italic"], settings["strike"]
    font.underline = {"none": False, "single": WD_UNDERLINE.SINGLE, "double": WD_UNDERLINE.DOUBLE}[settings["underline"]]
    font.all_caps = settings["case"] == "uppercase"
    font.small_caps = settings["case"] == "small_caps"
    rpr = target._element.get_or_add_rPr()
    fonts = rpr.get_or_add_rFonts()
    for name in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn("w:" + name), settings["family"])
        fonts.attrib.pop(qn("w:" + name + "Theme"), None)
    fonts.attrib.pop(qn("w:cstheme"), None)
    property_node(rpr, "w:spacing", w_val=round(settings["character_spacing"] * 20))
    property_node(rpr, "w:lang", w_val=language, w_eastAsia=language)


def apply_paragraph(target, settings):
    fmt = target.paragraph_format
    fmt.alignment = ALIGN[settings["alignment"]]
    fmt.left_indent, fmt.right_indent = length(settings["indent_left"]), length(settings["indent_right"])
    fmt.first_line_indent = length(settings["first_line"])
    fmt.space_before, fmt.space_after = Pt(settings["space_before"]), Pt(settings["space_after"])
    spacing = settings["line_spacing"]
    if spacing["mode"] == "multiple":
        fmt.line_spacing = float(spacing["value"])
    else:
        fmt.line_spacing = Pt(spacing["value"])
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY if spacing["mode"] == "exact" else WD_LINE_SPACING.AT_LEAST
    for key in ("widow_control", "keep_with_next", "keep_together", "page_break_before"):
        setattr(fmt, key, settings[key])
