import hashlib

from .document_model import Block, DocumentModel, Element, Inline
from .markdown_parser import parse_markdown, substitute
from .numbering import numbered_siblings
from md2doc.config.heading_numbering import merge_options, native_enabled


def bookmark(key):
    # Word names: ASCII letter first, maximum 40 characters, globally unique.
    return "md_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def build_structure(loaded, report):
    root, module, validator, manifest, metadata, styles = loaded
    targets = {}
    infos = {info["node"]["id"]: info for info in validator.nodes}
    native = native_enabled(manifest, styles)
    base = {k: v for k, v in manifest["defaults"]["numbering"].items() if k != "scope"}
    if base.get("format") == "decimal":
        base.setdefault("template", "{path}")
    global_config = merge_options(base, styles.get("heading_numbering", {}))
    global_config = merge_options(global_config, manifest["defaults"].get("heading_numbering", {}))

    def build(nodes, settings, body, prefix="", parent_kind=None, heading_config=None):
        result = []
        entries = numbered_siblings(nodes, settings, prefix, parent_kind) if not native else (
            (node, {**settings, **node.get("numbering", {})}, "") for node in nodes if node.get("enabled", True))
        for node, effective, number in entries:
            info = infos[node["id"]]
            blocks = parse_markdown(info["text"], metadata)
            heading = node.get("heading")
            if heading and heading["from"] == "yaml":
                label = substitute(heading["text"], metadata)
                blocks.insert(0, Block("heading", attrs={"tag": f"h{heading['level']}"}, inlines=[Inline("text", label)]))
            own_body = node.get("style", {}).get("body", body)
            chosen = None
            if heading:
                chosen = node.get("style", {}).get("heading") or {"title_page": "title", "appendix": "appendix_heading"}.get(node["type"], f"h{heading['level']}")
                blocks[0].structural = True
            element = Element(node["id"], node["type"], info["path"], own_body, blocks, number, chosen,
                              node.get("page_break", {}).get("before", False), node.get("page_break", {}).get("after", False))
            element.heading_config = merge_options(heading_config or global_config, node.get("heading_numbering", {}))
            if parent_kind == "appendix" and "format" not in node.get("numbering", {}):
                effective["format"] = "decimal"
            # Legacy enabled inheritance still controls the structural heading;
            # explicit element settings affect that heading only, not local MD.
            element.structural_numbering = {**({"enabled": False} if not effective["enabled"] else {}), **node.get("numbering", {})}
            targets[(str(element.source), "")] = targets[element.id] = bookmark(element.id)
            slugs = set()

            def headings(items):
                for block in items:
                    if block.kind == "heading":
                        # Match validator slug semantics, including code placeholders.
                        original = info["text"].splitlines()[block.line - 1] if block.line else ""
                        if block.structural and heading["from"] == "yaml":
                            label = substitute(heading["text"], metadata)
                        elif original.lstrip().startswith("#"):
                            import re
                            label = re.sub(r"^\s*#{1,6}\s+|\s+#+\s*$", "", original)
                            label = module.expand(label) if hasattr(module, "expand") else validator.expand(label)
                        else:
                            label = "".join(i.text for i in block.inlines)
                        base = module.slug(label)
                        slug, counter = base, 2
                        while slug in slugs:
                            slug, counter = f"{base}-{counter}", counter + 1
                        slugs.add(slug)
                        block.bookmark = bookmark(element.id + "#" + slug)
                        targets[(str(element.source), slug)] = block.bookmark
                    headings(block.children)
            headings(blocks)
            child_config = {k: v for k, v in element.heading_config.items() if k != "reset"}
            element.children = build(node.get("children", []), effective, own_body, number or prefix, node["type"], child_config)
            result.append(element)
        return result

    elements = build(manifest["elements"], manifest["defaults"]["numbering"], manifest["defaults"]["style"]["body"])
    model = DocumentModel(root, manifest, metadata, styles, elements, targets, validator)
    if native:
        from .heading_numbering import assign_heading_numbers
        assign_heading_numbers(model)
    report.processed_files = sum(1 for _ in model.walk())
    report.sections = sum(e.heading_style is not None for e in model.walk())
    return model
