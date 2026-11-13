"""Read-only OPC, XML and semantic relationship checks before atomic publish."""
import posixpath
from zipfile import ZipFile

from docx import Document
from lxml import etree

from md2doc.diagnostics.report import BuildError

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def verify_docx(path):
    try:
        with ZipFile(path) as archive:
            if archive.testzip():
                raise ValueError("ZIP CRC failure")
            names = set(archive.namelist())
            for required in ("[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml", "word/numbering.xml", "word/_rels/document.xml.rels", "docProps/core.xml"):
                if required not in names:
                    raise ValueError(f"Missing package part: {required}")
            xml = {}
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            for name in names:
                if name.endswith((".xml", ".rels")):
                    xml[name] = etree.fromstring(archive.read(name), parser)
            for name, root in xml.items():
                if not name.endswith(".rels"):
                    continue
                base = posixpath.dirname(posixpath.dirname(name))
                for rel in root:
                    if rel.get("TargetMode") != "External":
                        target = rel.get("Target")
                        member = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base, target))
                        if member not in names:
                            raise ValueError(f"Dangling relationship: {name}: {target}")
            for name, root in xml.items():
                if not name.endswith(".xml"):
                    continue
                rel_name = posixpath.join(posixpath.dirname(name), "_rels", posixpath.basename(name) + ".rels")
                rel_ids = {n.get("Id") for n in xml[rel_name]} if rel_name in xml else set()
                for node in root.iter():
                    for attr in ("id", "embed", "link"):
                        identity = node.get("{%s}%s" % (NS["r"], attr))
                        if identity and identity not in rel_ids:
                            raise ValueError(f"Undefined relationship ID {identity} in {name}")
            body = xml["word/document.xml"]
            starts = body.xpath("//w:bookmarkStart", namespaces=NS)
            bookmarks = {n.get("{%s}name" % NS["w"]) for n in starts}
            if len(bookmarks) != len(starts):
                raise ValueError("Duplicate bookmark names")
            start_ids = [n.get("{%s}id" % NS["w"]) for n in starts]
            end_ids = body.xpath("//w:bookmarkEnd/@w:id", namespaces=NS)
            if len(set(start_ids)) != len(start_ids) or sorted(start_ids) != sorted(end_ids):
                raise ValueError("Unbalanced bookmark IDs")
            for anchor in body.xpath("//w:hyperlink/@w:anchor", namespaces=NS):
                if anchor not in bookmarks:
                    raise ValueError(f"Dangling internal hyperlink: {anchor}")
            style_ids = set(xml["word/styles.xml"].xpath("//w:style/@w:styleId", namespaces=NS))
            for style in body.xpath("//w:pStyle/@w:val | //w:rStyle/@w:val", namespaces=NS):
                if style not in style_ids:
                    raise ValueError(f"Undefined style: {style}")
            num_ids = set(xml["word/numbering.xml"].xpath("//w:num/@w:numId", namespaces=NS))
            if any(n != "0" and n not in num_ids for n in body.xpath("//w:numPr/w:numId/@w:val", namespaces=NS)):
                raise ValueError("Undefined list numbering")
            abstract_ids = set(xml["word/numbering.xml"].xpath("//w:abstractNum/@w:abstractNumId", namespaces=NS))
            if any(n not in abstract_ids for n in xml["word/numbering.xml"].xpath("//w:num/w:abstractNumId/@w:val", namespaces=NS)):
                raise ValueError("Undefined abstract list numbering")
        Document(path)  # Independent public API reopening.
        from md2doc.diagnostics.numbering_inspector import inspect_heading_numbering
        inspect_heading_numbering(path)
    except Exception as exc:
        raise BuildError("E_DOCX_INTEGRITY", str(exc), path) from exc
