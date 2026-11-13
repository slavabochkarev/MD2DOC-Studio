"""markdown-it AST with two narrowly scoped Format 0.1 block rules."""
import re

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from .document_model import Block, Inline
from md2doc.config.heading_numbering import DIRECTIVE, directive_options


def special_block(state, start, end, silent):
    def line(index):
        return state.src[state.bMarks[index] + state.tShift[index]:state.eMarks[index]].strip()

    marker = line(start)
    if DIRECTIVE.fullmatch(marker):
        if not silent:
            token = state.push("heading_options", "", 0)
            token.content = marker
            token.map = [start, start + 1]
            state.line = start + 1
        return True
    if marker == "<!-- pagebreak -->":
        if not silent:
            token = state.push("pagebreak", "", 0)
            token.map = [start, start + 1]
            state.line = start + 1
        return True
    if marker not in ("::: note", "::: warning", "::: subtitle"):
        return False
    if silent:
        return True
    fence = None
    closing = start + 1
    while closing < end:
        current = line(closing)
        match = re.match(r"^(`{3,}|~{3,})(.*)$", current)
        if match:
            if fence is None:
                fence = match[1]
            elif match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
        if current == ":::" and fence is None:
            break
        closing += 1
    kind = marker[4:]
    token = state.push(f"{kind}_open", "div", 1)
    token.map = [start, min(closing + 1, end)]
    old_parent, old_max = state.parentType, state.lineMax
    state.parentType, state.lineMax = "container", closing
    state.md.block.tokenize(state, start + 1, closing)
    state.parentType, state.lineMax = old_parent, old_max
    state.push(f"{kind}_close", "div", -1)
    state.line = min(closing + 1, end)
    return True


def parser():
    md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
    md.block.ruler.before("fence", "md2doc_special", special_block, {"alt": ["paragraph", "blockquote", "list"]})
    return md


def substitute(text, metadata):
    return re.sub(r"\{\{metadata\.([a-z_]+)\}\}", lambda m: metadata[m[1]], text)


def parse_markdown(text, metadata):
    root = SyntaxTreeNode(parser().parse(text))

    def convert(node):
        token = node.token if node.type not in ("root",) else None
        # Paired nodes expose their opening token through nester_tokens.
        if token is None and node.nester_tokens:
            token = node.nester_tokens.opening
        attrs = dict(token.attrs or {}) if token else {}
        if node.type == "ordered_list":
            # Markdown explicitly spells its first number, including `1.`.
            attrs.setdefault("start", 1)
        attrs["tag"] = node.tag
        block = Block(node.type, node.content, attrs, line=(node.map or [0])[0] + 1)
        for child in node.children:
            if child.type == "inline":
                for t in child.token.children or []:
                    content = t.content if t.type in ("code_inline", "image") else substitute(t.content, metadata)
                    block.inlines.append(Inline(t.type, content, dict(t.attrs or {})))
            else:
                block.children.append(convert(child))
        return block

    def attach(blocks):
        result = []
        pending = None
        for block in blocks:
            if block.kind == "heading_options":
                pending = directive_options(block.text)
                continue
            if pending is not None:
                block.numbering_override = pending
                pending = None
            block.children = attach(block.children)
            result.append(block)
        return result
    return attach([convert(child) for child in root.children])
