"""All low-level WordprocessingML operations live here."""
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT

# Successors for properties absent from python-docx's public/schema descriptors.
# WordprocessingML sequence order matters, even when a tolerant reader opens it.
SUCCESSORS = {
    "w:spacing": ("w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:vertAlign", "w:lang"),
    "w:lang": ("w:eastAsianLayout", "w:specVanish", "w:oMath"),
    "w:pBdr": ("w:shd", "w:tabs", "w:suppressAutoHyphens", "w:spacing", "w:ind", "w:jc", "w:outlineLvl", "w:rPr", "w:sectPr"),
    "w:suppressAutoHyphens": ("w:kinsoku", "w:wordWrap", "w:spacing", "w:ind", "w:jc", "w:outlineLvl", "w:rPr", "w:sectPr"),
    "w:wordWrap": ("w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:spacing", "w:ind", "w:jc", "w:outlineLvl", "w:rPr", "w:sectPr"),
    "w:pgNumType": ("w:cols", "w:formProt", "w:vAlign", "w:noEndnote", "w:titlePg", "w:textDirection", "w:docGrid", "w:sectPrChange"),
    "w:mirrorMargins": ("w:proofState", "w:defaultTabStop", "w:autoHyphenation", "w:consecutiveHyphenLimit", "w:updateFields", "w:compat", "w:rsids", "m:mathPr", "w:themeFontLang", "w:clrSchemeMapping"),
    "w:autoHyphenation": ("w:consecutiveHyphenLimit", "w:hyphenationZone", "w:doNotHyphenateCaps", "w:evenAndOddHeaders", "w:updateFields", "w:compat", "w:rsids", "m:mathPr", "w:themeFontLang", "w:clrSchemeMapping"),
    "w:consecutiveHyphenLimit": ("w:hyphenationZone", "w:doNotHyphenateCaps", "w:evenAndOddHeaders", "w:updateFields", "w:compat", "w:rsids", "m:mathPr", "w:themeFontLang", "w:clrSchemeMapping"),
    "w:updateFields": ("w:hdrShapeDefaults", "w:footnotePr", "w:endnotePr", "w:compat", "w:docVars", "w:rsids", "m:mathPr", "w:themeFontLang", "w:clrSchemeMapping"),
    "w:tblBorders": ("w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange"),
    "w:tblW": ("w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange"),
    "w:tblCellMar": ("w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange"),
    "w:shd": ("w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark", "w:tcPrChange"),
    "w:cantSplit": ("w:trHeight", "w:tblHeader", "w:tblCellSpacing", "w:jc", "w:hidden", "w:ins", "w:del", "w:trPrChange"),
}

# Settings preceding these must also precede *all* intervening settings, not
# merely compat/rsids. The default template contains characterSpacingControl.
_HYPHENATION_SUCCESSORS = (
    "w:hyphenationZone", "w:doNotHyphenateCaps", "w:showEnvelope", "w:summaryLength",
    "w:clickAndTypeStyle", "w:defaultTableStyle", "w:evenAndOddHeaders", "w:bookFoldRevPrinting",
    "w:bookFoldPrinting", "w:bookFoldPrintingSheets", "w:drawingGridHorizontalSpacing",
    "w:drawingGridVerticalSpacing", "w:displayHorizontalDrawingGridEvery", "w:displayVerticalDrawingGridEvery",
    "w:doNotUseMarginsForDrawingGridOrigin", "w:drawingGridHorizontalOrigin", "w:drawingGridVerticalOrigin",
    "w:doNotShadeFormData", "w:noPunctuationKerning", "w:characterSpacingControl", "w:printTwoOnOne",
    "w:strictFirstAndLastChars", "w:noLineBreaksAfter", "w:noLineBreaksBefore", "w:savePreviewPicture",
    "w:doNotValidateAgainstSchema", "w:saveInvalidXml", "w:ignoreMixedContent", "w:alwaysShowPlaceholderText",
    "w:doNotDemarcateInvalidXml", "w:saveXmlDataOnly", "w:useXSLTWhenSaving", "w:saveThroughXslt",
    "w:showXMLTags", "w:alwaysMergeEmptyNamespace", "w:updateFields", "w:hdrShapeDefaults",
    "w:footnotePr", "w:endnotePr", "w:compat", "w:docVars", "w:rsids", "m:mathPr", "w:attachedSchema",
    "w:themeFontLang", "w:clrSchemeMapping", "w:doNotIncludeSubdocsInStats", "w:doNotAutoCompressPictures",
    "w:forceUpgrade", "w:captions", "w:readModeInkLockDown", "w:smartTagType", "sl:schemaLibrary",
    "w:shapeDefaults", "w:doNotEmbedSmartTags", "w:decimalSymbol", "w:listSeparator",
)
SUCCESSORS["w:autoHyphenation"] = ("w:consecutiveHyphenLimit",) + _HYPHENATION_SUCCESSORS
SUCCESSORS["w:consecutiveHyphenLimit"] = _HYPHENATION_SUCCESSORS

def element(tag, **attrs):
    node = OxmlElement(tag)
    for key, value in attrs.items():
        node.set(qn(key.replace("_", ":", 1)), str(value))
    return node


def property_node(parent, tag, **attrs):
    existing = parent.find(qn(tag))
    if existing is not None:
        parent.remove(existing)
    node = element(tag, **attrs)
    # python-docx's schema-aware insertion preserves CT_* child ordering.
    insert = getattr(parent, "_insert_" + tag.split(":")[-1], None)
    if insert:
        insert(node)
    else:
        successors = {qn(t) for t in SUCCESSORS.get(tag, ())}
        following = next((child for child in parent if child.tag in successors), None)
        if following is not None:
            following.addprevious(node)
        else:
            parent.append(node)
    return node


def add_bookmark(paragraph, name, identity):
    paragraph._p.append(element("w:bookmarkStart", w_id=identity, w_name=name))
    paragraph._p.append(element("w:bookmarkEnd", w_id=identity))


def hyperlink(paragraph, target=None, anchor=None):
    link = element("w:hyperlink", w_history="1")
    if anchor:
        link.set(qn("w:anchor"), anchor)
    else:
        rel = paragraph.part.relate_to(target, RT.HYPERLINK, is_external=True)
        link.set(qn("r:id"), rel)
    paragraph._p.append(link)
    return link


def page_field(paragraph):
    run = paragraph.add_run()
    run._r.append(element("w:fldChar", w_fldCharType="begin"))
    instruction = element("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    run._r.append(instruction)
    run._r.append(element("w:fldChar", w_fldCharType="separate"))
    run._r.append(element("w:t"))
    run._r[-1].text = "1"
    run._r.append(element("w:fldChar", w_fldCharType="end"))


def num_definition(document, settings, ordered, depth, start):
    numbering = document.part.numbering_part.element
    existing_abs = [int(n.get(qn("w:abstractNumId"))) for n in numbering.findall(qn("w:abstractNum"))]
    existing_num = [int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))]
    abstract_id, num_id = max(existing_abs, default=-1) + 1, max(existing_num, default=0) + 1
    abstract = element("w:abstractNum", w_abstractNumId=abstract_id)
    abstract.append(element("w:multiLevelType", w_val="multilevel"))
    formats = {"lower_alpha": "lowerLetter", "upper_alpha": "upperLetter", "lower_roman": "lowerRoman", "upper_roman": "upperRoman", "decimal": "decimal"}
    choices = settings["ordered_formats"] if ordered else settings["bullet_markers"]
    for level in range(settings["max_depth"]):
        choice = choices[min(level, len(choices) - 1)]
        lvl = element("w:lvl", w_ilvl=level)
        lvl.append(element("w:start", w_val=start if level == depth else 1))
        lvl.append(element("w:numFmt", w_val=formats[choice] if ordered else "bullet"))
        lvl.append(element("w:lvlText", w_val=f"%{level + 1}." if ordered else choice))
        lvl.append(element("w:lvlJc", w_val="left"))
        ppr = element("w:pPr")
        # Dimensions are also applied directly to paragraphs; definitions make
        # the list remain editable with correct indents in Word.
        from .paragraphs import length
        ppr.append(element("w:ind", w_left=round(length(settings["indent_per_level"]).twips * (level + 1)), w_hanging=round(length(settings["hanging"]).twips)))
        lvl.append(ppr)
        abstract.append(lvl)
    first_num = numbering.find(qn("w:num"))
    if first_num is not None:
        first_num.addprevious(abstract)
    else:
        numbering.append(abstract)
    num = element("w:num", w_numId=num_id)
    num.append(element("w:abstractNumId", w_val=abstract_id))
    override = element("w:lvlOverride", w_ilvl=depth)
    override.append(element("w:startOverride", w_val=start))
    num.append(override)
    numbering.append(num)
    return num_id


def apply_number(paragraph, num_id, depth):
    ppr = paragraph._p.get_or_add_pPr()
    num = property_node(ppr, "w:numPr")
    num.append(element("w:ilvl", w_val=depth))
    num.append(element("w:numId", w_val=num_id))
