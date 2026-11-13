from datetime import datetime, timezone
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Mm, Pt
from PIL import ImageFont

from md2doc.core.document_model import Block
from md2doc.core.style_resolver import StyleResolver
from md2doc.diagnostics.report import BuildError
from .images import image_data
from .ooxml_extensions import (add_bookmark, apply_number, element, hyperlink,
                               num_definition, page_field, property_node)
from .paragraphs import ALIGN, apply_font, apply_paragraph, length, width


class DocxRenderer:
    def __init__(self, model, report):
        self.model, self.report = model, report
        self.styles = model.styles
        self.resolver = StyleResolver(self.styles)
        self.doc = Document()
        self.cache = {}
        self.pending_break = False
        self.has_content = False
        self.bookmark_index = 0
        self.pending_anchors = []
        self.image_number = self.styles["images"]["numbering"]["start"]
        self.source = None
        self.configure()
        from md2doc.config.heading_numbering import native_enabled
        from .heading_numbering import HeadingNumbering
        self.heading_numbers = HeadingNumbering(self.doc) if native_enabled(model.manifest, model.styles) else None

    def configure(self):
        s, config = self.doc.sections[0], self.styles["page"]
        dimensions = {"A4": (210, 297), "A5": (148, 210), "Letter": (215.9, 279.4)}[config["paper"]]
        if config["orientation"] == "landscape":
            dimensions = dimensions[::-1]
            s.orientation = WD_ORIENT.LANDSCAPE
        s.page_width, s.page_height = map(Mm, dimensions)
        for side, value in config["margins"].items():
            setattr(s, side + "_margin", length(value))
        s.header_distance, s.footer_distance = length(config["header_distance"]), length(config["footer_distance"])
        self.available = s.page_width - s.left_margin - s.right_margin
        self.height = s.page_height - s.top_margin - s.bottom_margin
        if self.available <= 0 or self.height <= 0:
            raise BuildError("E_PAGE_GEOMETRY", "Margins leave no text area", self.model.root / self.model.manifest["styles"])
        settings = self.doc.settings.element
        if config["mirror_margins"]:
            property_node(settings, "w:mirrorMargins")
        hyp = self.styles["breaks"]["hyphenation"]
        property_node(settings, "w:autoHyphenation", w_val=int(hyp["enabled"]))
        property_node(settings, "w:consecutiveHyphenLimit", w_val=hyp["consecutive_limit"])
        # PAGE recalculates during Word pagination. updateFields=true instead
        # causes a generic external-field prompt even with local PAGE fields.
        old_update = settings.find(qn("w:updateFields"))
        if old_update is not None:
            settings.remove(old_update)
        self.language = hyp["language"]
        base = self.resolver.resolve()
        self.clear_style_format(self.doc.styles["Normal"])
        apply_font(self.doc.styles["Normal"], base["font"], self.language)
        apply_paragraph(self.doc.styles["Normal"], base["paragraph"])
        for name in [*(f"h{i}" for i in range(1, 7)), *self.styles["blocks"], *self.styles["named_styles"]]:
            self.word_style("body", name)
        inline = self.doc.styles.add_style("MD2DOC Inline Code", WD_STYLE_TYPE.CHARACTER)
        apply_font(inline, self.resolver.resolve("body", "code")["font"], self.language)
        core, metadata = self.doc.core_properties, self.model.metadata
        core.title, core.subject, core.author = metadata["title"], metadata["subtitle"], metadata["author"]
        core.comments, core.keywords = metadata["description"], ", ".join(metadata["keywords"])
        core.language, core.version, core.content_status = metadata["language"], metadata["version"], metadata["status"]
        core.created = datetime.fromisoformat(metadata["date"]).replace(tzinfo=timezone.utc)
        core.last_modified_by = "MD2DOC Studio"
        self.configure_headers(s)

    def word_style(self, body, functional=None):
        key = body, functional
        if key in self.cache:
            return self.cache[key]
        name = functional or body
        if body == "body":
            word_name = {"body": "Normal", "title": "Title", "subtitle": "Subtitle", "quote": "Quote", "caption": "Caption",
                         **{f"h{i}": f"Heading {i}" for i in range(1, 7)}}.get(name, "MD2DOC " + name)
        else:
            word_name = "MD2DOC " + body + (" / " + functional if functional else "")
        style = self.doc.styles[word_name] if word_name in self.doc.styles else self.doc.styles.add_style(word_name, WD_STYLE_TYPE.PARAGRAPH)
        self.clear_style_format(style)
        if word_name != "Normal":
            style.base_style = self.doc.styles["Normal"]
        computed = self.resolver.resolve(body, functional)
        apply_font(style, computed["font"], self.language)
        apply_paragraph(style, computed["paragraph"])
        # Remove template theme residues that could replace configured colors.
        color = style.element.get_or_add_rPr().find(qn("w:color"))
        if color is not None:
            for attr in ("themeColor", "themeTint", "themeShade"):
                color.attrib.pop(qn("w:" + attr), None)
        if name.startswith("h") and len(name) == 2 and name[1].isdigit():
            property_node(style.element.get_or_add_pPr(), "w:outlineLvl", w_val=int(name[1]) - 1)
        if computed["font"]["case"] == "lowercase":
            self.report.warn("W_LOWERCASE_DISPLAY", "Word has no lowercase display property; output run text is lowercased. Source text is preserved.", self.model.root / self.model.manifest["styles"])
        self.cache[key] = style
        return style

    @staticmethod
    def clear_style_format(style):
        # The library template contains borders/numbering/theme residues not
        # present in MD2DOC's contract. Fully resolved styles replace them.
        for tag in ("w:pPr", "w:rPr"):
            node = style.element.find(qn(tag))
            if node is not None:
                style.element.remove(node)

    def configure_headers(self, section):
        config = self.styles["headers_footers"]
        number = config["page_number"]
        section.different_first_page_header_footer = config["different_first_page"]
        property_node(section._sectPr, "w:pgNumType", w_start=number["start"],
                      w_fmt={"decimal": "decimal", "lower_roman": "lowerRoman", "upper_roman": "upperRoman"}[number["format"]])

        def fill(area, text, show, position):
            p = area.paragraphs[0]
            p.style = self.word_style("body")
            p.paragraph_format.first_line_indent = 0
            p.paragraph_format.alignment = ALIGN["left"]
            p.paragraph_format.page_break_before = False
            p.paragraph_format.keep_with_next = False
            p.add_run(text)
            if show:
                if position == "left":
                    if text:
                        p.add_run(" ")
                else:
                    target = self.available / 2 if position == "center" else self.available
                    p.paragraph_format.tab_stops.add_tab_stop(int(target), WD_TAB_ALIGNMENT.CENTER if position == "center" else WD_TAB_ALIGNMENT.RIGHT)
                    p.add_run("\t")
                page_field(p)
        area, position = number["position"].split("_")
        for name in ("header", "footer"):
            fill(getattr(section, name), config[name + "_text"], number["visible"] and area == name, position)
            if config["different_first_page"]:
                first = config["first_page"]
                fill(getattr(section, "first_page_" + name), first[name + "_text"], number["visible"] and first["show_page_number"] and area == name, position)

    def anchor(self, paragraph, name):
        self.bookmark_index += 1
        add_bookmark(paragraph, name, self.bookmark_index)

    def paragraph(self, container, body, functional=None, existing=None, main=True):
        p = existing if existing is not None else container.add_paragraph()
        p.style = self.word_style(body, functional)
        if main:
            requested = self.pending_break or bool(p.style.paragraph_format.page_break_before)
            p.paragraph_format.page_break_before = requested and self.has_content
            self.pending_break = False
            self.has_content = True
            for name in self.pending_anchors:
                self.anchor(p, name)
            self.pending_anchors.clear()
        return p

    def render(self, output):
        def visit(elements):
            for current in elements:
                self.source = current.source
                if current.kind in ("chapter", "appendix") and self.styles["images"]["numbering"]["scope"] == "chapter":
                    self.image_number = self.styles["images"]["numbering"]["start"]
                self.pending_break |= current.before
                self.pending_anchors.append(self.model.targets[current.id])
                self.blocks(current.blocks, self.doc, current)
                visit(current.children)
                self.pending_break |= current.after
        visit(self.model.elements)
        if self.pending_anchors:
            p = self.paragraph(self.doc, "body")
        self.doc.save(output)

    def blocks(self, blocks, container, current, functional=None, depth=0, list_context=None, main=True):
        for block in blocks:
            kind = block.kind
            if kind == "pagebreak":
                self.pending_break = True
            elif kind in ("note", "warning", "subtitle", "blockquote"):
                self.blocks(block.children, container, current, "quote" if kind == "blockquote" else kind, depth, list_context, main)
            elif kind in ("bullet_list", "ordered_list"):
                self.render_list(block, container, current, functional, depth, main)
            elif kind == "table":
                self.render_table(block, container, current, main)
            elif kind in ("fence", "code_block"):
                self.code(block, container, current, main)
            elif kind in ("paragraph", "heading"):
                func = current.heading_style if block.structural else f"h{block.attrs['tag'][1:]}" if kind == "heading" else functional
                # Standalone images are Word drawing paragraphs with adjacent captions.
                if kind == "paragraph" and any(i.kind == "image" for i in block.inlines):
                    if len(block.inlines) != 1:
                        self.report.warn("W_INLINE_IMAGE", "Inline image promoted to an image paragraph to preserve configured caption and alignment.", self.source)
                    chunk = []
                    for inline in block.inlines:
                        if inline.kind == "image":
                            if chunk:
                                p = self.paragraph(container, current.body_style, func, main=main)
                                self.inlines(p, chunk, current, func)
                                chunk = []
                            self.image(inline, container, current, main)
                        else:
                            chunk.append(inline)
                    if chunk:
                        p = self.paragraph(container, current.body_style, func, main=main)
                        self.inlines(p, chunk, current, func)
                    continue
                p = self.paragraph(container, current.body_style, func, main=main)
                if kind == "heading":
                    property_node(p._p.get_or_add_pPr(), "w:outlineLvl", w_val=int(block.attrs["tag"][1:]) - 1)
                    if block.bookmark:
                        self.anchor(p, block.bookmark)
                    if self.heading_numbers:
                        if block.heading_number:
                            self.heading_numbers.apply(p, block.heading_number)
                        else:
                            # Explicitly cancel inherited Heading style numbering,
                            # including title/frontmatter and excluded headings.
                            apply_number(p, 0, int(block.attrs["tag"][1:]) - 1)
                    elif block.structural and current.number:
                        prefix = f"Приложение {current.number} — " if current.kind == "appendix" else current.number + " "
                        p.add_run(prefix)
                if list_context:
                    num_id, list_depth, first = list_context
                    self.list_indent(p, list_depth)
                    if first[0]:
                        apply_number(p, num_id, list_depth)
                        first[0] = False
                self.inlines(p, block.inlines, current, func)
                self.check_paragraph_height(p, current.body_style, func)
            elif kind == "hr":
                p = self.paragraph(container, current.body_style, main=main)
                border = property_node(p._p.get_or_add_pPr(), "w:pBdr")
                border.append(element("w:bottom", w_val="single", w_sz="4", w_color="808080"))
            else:
                self.report.warn("W_MARKDOWN_UNSUPPORTED", f"Unsupported Markdown node {kind}; visible content retained.", self.source)
                if block.inlines or block.text:
                    p = self.paragraph(container, current.body_style, functional, main=main)
                    self.inlines(p, block.inlines, current, functional)
                    if block.text:
                        p.add_run(block.text)
                self.blocks(block.children, container, current, functional, depth, list_context, main)

    def inlines(self, paragraph, inlines, current, functional=None):
        emphasis = {"strong": 0, "em": 0, "s": 0}
        link = None
        computed = self.resolver.resolve(current.body_style, functional)
        for item in inlines:
            kind = item.kind
            if kind.endswith(("_open", "_close")) and kind.rsplit("_", 1)[0] in emphasis:
                key = kind.rsplit("_", 1)[0]
                emphasis[key] += 1 if kind.endswith("_open") else -1
                continue
            if kind == "link_open":
                address = item.attrs["href"]
                parsed = urlsplit(address)
                target = None
                if address.startswith("md2doc:"):
                    target = self.model.targets.get(address[7:])
                elif not parsed.scheme:
                    path = (self.source.parent / unquote(parsed.path)).resolve() if parsed.path else self.source
                    target = self.model.targets.get((str(path), unquote(parsed.fragment)))
                if target:
                    link = hyperlink(paragraph, anchor=target)
                elif parsed.scheme in ("http", "https", "mailto"):
                    link = hyperlink(paragraph, target=address)
                else:
                    self.report.warn("W_LINK_UNASSEMBLED", f"Link target is not in assembled document; text retained: {address}", self.source)
                continue
            if kind == "link_close":
                link = None
                continue
            if kind in ("softbreak", "hardbreak"):
                run = paragraph.add_run(" " if kind == "softbreak" and self.styles["breaks"]["soft_line_break"] == "space" else "\n")
            else:
                text = item.text
                if computed["font"]["case"] == "lowercase":
                    text = text.lower()
                run = paragraph.add_run(text)
                if kind == "code_inline":
                    run.style = self.doc.styles["MD2DOC Inline Code"]
                    font = {**computed["font"], **self.resolver.overrides("code").get("font", {})}
                    apply_font(run, font, self.language)
                elif kind != "text":
                    self.report.warn("W_INLINE_UNSUPPORTED", f"Unsupported inline {kind}; text retained.", self.source)
                if emphasis["strong"]:
                    run.bold = True
                if emphasis["em"]:
                    run.italic = True
                if emphasis["s"]:
                    run.font.strike = True
            if link is not None:
                # Move the native run, retaining emphasis/code formatting.
                link.append(run._r)

    def list_indent(self, paragraph, depth):
        settings = self.styles["lists"]
        fmt = paragraph.paragraph_format
        fmt.left_indent = int(length(settings["indent_per_level"]) * (depth + 1))
        fmt.first_line_indent = -length(settings["hanging"])
        fmt.space_before, fmt.space_after = Pt(settings["space_before"]), Pt(settings["space_after"])

    def render_list(self, block, container, current, functional, depth, main):
        settings = self.styles["lists"]
        if depth >= settings["max_depth"]:
            raise BuildError("E_LIST_DEPTH", f"List depth {depth + 1} exceeds max_depth={settings['max_depth']}", self.source)
        start = int(block.attrs.get("start", settings["ordered_start"]))
        num_id = num_definition(self.doc, settings, block.kind == "ordered_list", depth, start)
        for item in block.children:
            context = (num_id, depth, [True])
            # A nested sequence has its own numId and retains the outer indent.
            for child in item.children:
                if child.kind in ("bullet_list", "ordered_list"):
                    self.render_list(child, container, current, functional, depth + 1, main)
                else:
                    self.blocks([child], container, current, functional, depth, context, main)

    def measure(self, text, font):
        filenames = {"Consolas": "consola.ttf", "Times New Roman": "times.ttf", "Arial": "arial.ttf", "Calibri": "calibri.ttf"}
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filenames.get(font["family"], font["family"] + ".ttf")
        try:
            face = ImageFont.truetype(str(path), round(font["size"] * 4))
            return face.getlength(text) / 4
        except OSError:
            self.report.warn("W_FONT_METRICS", f"Font metrics unavailable for {font['family']}; layout overflow checks use an estimate.", self.source)
            return len(text) * font["size"] * .6

    def code(self, block, container, current, main):
        computed = self.resolver.resolve(current.body_style, "code")
        usable = self.available / 12700 - length(computed["paragraph"]["indent_left"]).pt - length(computed["paragraph"]["indent_right"]).pt
        mode = self.styles["breaks"]["code_long_lines"]
        too_long = any(self.measure(line.expandtabs(4), computed["font"]) > usable for line in block.text.splitlines())
        if too_long and mode == "error":
            raise BuildError("E_CODE_WIDTH", "Code line exceeds text area", self.source)
        if too_long and mode == "overflow":
            self.report.warn("W_CODE_OVERFLOW", "Code line exceeds text area (overflow policy).", self.source)
        p = self.paragraph(container, current.body_style, "code", main=main)
        property_node(p._p.get_or_add_pPr(), "w:suppressAutoHyphens", w_val="1")
        if mode == "overflow":
            property_node(p._p.get_or_add_pPr(), "w:wordWrap", w_val="0")
            self.report.warn("W_CODE_OVERFLOW_LAYOUT", "Word may still wrap long code lines; overflow is best effort.", self.source)
        else:
            property_node(p._p.get_or_add_pPr(), "w:wordWrap", w_val="1")
        p.add_run(block.text.removesuffix("\n"))
        if computed["paragraph"]["keep_together"]:
            line_count = sum(max(1, int(self.measure(line, computed["font"]) / max(usable, 1)) + 1) for line in block.text.splitlines())
            if line_count * computed["font"]["size"] * 1.2 > self.height / 12700:
                p.paragraph_format.keep_together = False
                self.report.warn("W_PARAGRAPH_TOO_TALL", "Code paragraph exceeds page height; keep_together relaxed.", self.source)

    def line_height(self, settings):
        spacing = settings["paragraph"]["line_spacing"]
        natural = settings["font"]["size"] * 1.2
        if spacing["mode"] == "multiple":
            return natural * spacing["value"]
        if spacing["mode"] == "exact":
            return spacing["value"]
        return max(natural, spacing["value"])

    def check_paragraph_height(self, paragraph, body, functional):
        computed = self.resolver.resolve(body, functional)
        if not computed["paragraph"]["keep_together"]:
            return
        usable = max(1, self.available / 12700 - length(computed["paragraph"]["indent_left"]).pt - length(computed["paragraph"]["indent_right"]).pt)
        count = sum(max(1, int(self.measure(line, computed["font"]) / usable) + 1) for line in paragraph.text.splitlines())
        if count * self.line_height(computed) > self.height / 12700:
            paragraph.paragraph_format.keep_together = False
            self.report.warn("W_PARAGRAPH_TOO_TALL", "Estimated paragraph height exceeds a page; keep_together relaxed.", self.source)

    def image(self, inline, container, current, main):
        parsed = urlsplit(inline.attrs["src"])
        path = (self.source.parent / unquote(parsed.path)).resolve()
        try:
            path.relative_to(self.model.root)
        except ValueError as exc:
            raise BuildError("E_IMAGE_PATH", "Image path escapes project", self.source) from exc
        data, natural = image_data(path)
        settings = self.styles["images"]
        caption = settings["caption"]

        def add_caption():
            text = inline.attrs.get("title") or inline.text
            number = str(self.image_number) if settings["numbering"]["enabled"] else ""
            p = self.paragraph(container, current.body_style, caption["style"], main=main)
            p.add_run(caption["template"].replace("{number}", number).replace("{text}", text))
            if caption["position"] == "above":
                p.paragraph_format.keep_with_next = True

        if caption["enabled"] and caption["position"] == "above":
            add_caption()
        p = self.paragraph(container, current.body_style, main=main)
        p.alignment = ALIGN[settings["alignment"]]
        p.paragraph_format.first_line_indent = 0
        p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(settings["space_before"]), Pt(settings["space_after"])
        maximum = width(settings["max_width"], self.available)
        shape = p.add_run().add_picture(data, width=min(maximum, int(Pt(natural))))
        shape._inline.docPr.set("descr", inline.text)
        if caption["enabled"] and caption["position"] == "below":
            p.paragraph_format.keep_with_next = True
            add_caption()
        if caption["enabled"] and settings["numbering"]["enabled"]:
            self.image_number += 1
        self.report.images += 1

    def render_table(self, block, container, current, main):
        rows = [row for group in block.children for row in group.children]
        settings = self.styles["tables"]
        requested_break = self.pending_break or self.resolver.resolve(current.body_style)["paragraph"]["page_break_before"]
        if requested_break and self.has_content and main:
            # An explicit break on a paragraph before a table is reliable in Word.
            self.pending_break = True
            p = self.paragraph(container, current.body_style)
            p.paragraph_format.space_before = p.paragraph_format.space_after = 0
            p.paragraph_format.keep_with_next = True
        if main:
            self.pending_break = False
        table = container.add_table(rows=len(rows), cols=len(rows[0].children))
        table.autofit = False
        table.alignment = {"left": WD_TABLE_ALIGNMENT.LEFT, "center": WD_TABLE_ALIGNMENT.CENTER, "right": WD_TABLE_ALIGNMENT.RIGHT}[settings["alignment"]]
        total = width(settings["width"], self.available)
        for column in table.columns:
            column.width = total // len(table.columns)
        pr = table._tbl.tblPr
        property_node(pr, "w:tblW", w_w=round(total / 635), w_type="dxa")
        border = property_node(pr, "w:tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            b = settings["border"]
            border.append(element("w:" + side, w_val=b["style"], w_sz=round(b["width"] * 8), w_color=b["color"][1:]))
        padding = property_node(pr, "w:tblCellMar")
        for side in ("top", "left", "bottom", "right"):
            value = settings["cell_padding"][side]
            padding.append(element("w:" + side, w_w=round(length(value).twips), w_type="dxa"))
        estimated_height = 0
        for i, source_row in enumerate(rows):
            row = table.rows[i]
            trpr = row._tr.get_or_add_trPr()
            if i == 0 and settings["repeat_header"]:
                property_node(trpr, "w:tblHeader")
            if not settings["allow_row_split"]:
                property_node(trpr, "w:cantSplit")
            longest = 1
            for j, source_cell in enumerate(source_row.children):
                cell = row.cells[j]
                cell.width = total // len(row.cells)
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                if any(item.kind == "image" for item in source_cell.inlines):
                    initial = cell.paragraphs[0]
                    available = self.available
                    self.available = max(1, total // len(row.cells) - length(settings["cell_padding"]["left"]) - length(settings["cell_padding"]["right"]))
                    try:
                        self.blocks([Block("paragraph", inlines=source_cell.inlines)], cell, current, main=False)
                    finally:
                        self.available = available
                    cell._tc.remove(initial._p)
                else:
                    p = self.paragraph(cell, current.body_style, existing=cell.paragraphs[0], main=False)
                    self.inlines(p, source_cell.inlines, current)
                alignment = source_cell.attrs.get("style", "")
                for p in cell.paragraphs:
                    p.paragraph_format.first_line_indent = 0
                    if alignment:
                        p.alignment = ALIGN[alignment.split(":")[-1].strip()]
                    if i == 0:
                        for run in p.runs:
                            run.bold = True
                fill = settings["header_fill"] if i == 0 else settings["banded_rows"]["odd" if i % 2 else "even"] if settings["banded_rows"]["enabled"] else None
                if fill:
                    property_node(cell._tc.get_or_add_tcPr(), "w:shd", w_fill=fill[1:], w_val="clear")
                text = "".join(x.text for x in source_cell.inlines)
                font = self.resolver.resolve(current.body_style)["font"]
                usable = max(1, total / 12700 / len(row.cells) - length(settings["cell_padding"]["left"]).pt - length(settings["cell_padding"]["right"]).pt)
                longest = max(longest, int(self.measure(text, font) / usable) + 1)
            height = longest * self.line_height(self.resolver.resolve(current.body_style)) + length(settings["cell_padding"]["top"]).pt + length(settings["cell_padding"]["bottom"]).pt
            estimated_height += height
            if height > self.height / 12700:
                node = trpr.find(qn("w:cantSplit"))
                if node is not None:
                    trpr.remove(node)
                self.report.warn("W_TABLE_ROW_TOO_TALL", "Estimated row height exceeds a page; row splitting enabled.", self.source)
        keep = self.styles["breaks"]["table_pagination"] == "keep_table"
        if keep and estimated_height > self.height / 12700:
            keep = False
            self.report.warn("W_TABLE_TOO_TALL", "Estimated table height exceeds a page; falling back to between_rows.", self.source)
        if keep:
            for i, row in enumerate(table.rows):
                for cell in row.cells:
                    for p in cell.paragraphs:
                        p.paragraph_format.keep_with_next = i != len(table.rows) - 1
        if main:
            first = table.cell(0, 0).paragraphs[0]
            for name in self.pending_anchors:
                self.anchor(first, name)
            self.pending_anchors.clear()
            self.has_content = True
        self.report.tables += 1
