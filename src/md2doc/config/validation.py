"""Single input validator for MD2DOC 0.1/0.2.

Format 0.1 rules relocated from doc1/tools/validate.py on 2026-11-11;
the historical project-local file is untouched and no longer a dependency.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import sys
from urllib.parse import unquote, urlsplit

from .heading_numbering import FORMATS as HEADING_FORMATS, check_options, validate_directives

try:
    import yaml
except ImportError:
    yaml = None


class ConfigError(ValueError):
    pass


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if not isinstance(key, str):
            raise ConfigError("Configuration keys must be strings")
        if key in result:
            raise ConfigError(f"Duplicate key: {key}")
        result[key] = value
    return result


def reject_constant(token):
    raise ConfigError(f"Non-finite number: {token}")


def load_config(path):
    try:
        raw = path.read_text(encoding="utf-8-sig")
        if yaml is None:
            try:
                return json.loads(raw, object_pairs_hook=unique_pairs,
                                  parse_constant=reject_constant)
            except json.JSONDecodeError as exc:
                raise ConfigError("PyYAML is unavailable; use JSON-compatible YAML "
                                  "or install requirements.txt manually. " + str(exc)) from exc

        class UniqueLoader(yaml.SafeLoader):
            pass

        def construct_mapping(loader, node):
            return unique_pairs((loader.construct_object(k, deep=True),
                                 loader.construct_object(v, deep=True))
                                for k, v in node.value)

        UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                                     construct_mapping)
        for token in yaml.scan(raw):
            if isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken,
                                  yaml.tokens.TagToken)):
                raise ConfigError("YAML anchors, aliases and explicit tags are unsupported")
        return yaml.load(raw, Loader=UniqueLoader)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ConfigError(f"{path.name}: {exc}") from exc
    except Exception as exc:
        if yaml is not None and isinstance(exc, yaml.YAMLError):
            raise ConfigError(f"{path.name}: {exc}") from exc
        raise


class Validator:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.errors = []
        self.warnings = []
        self.nodes = []
        self.ids = {}
        self.sources = {}
        self.metadata = {}
        self.styles = {}
        self.schema_version = "0.1"
        self.style_names = {"body", *(f"h{i}" for i in range(1, 7)), *BLOCKS}

    def error(self, code, where, message):
        self.errors.append(f"ERROR {code} {where}: {message}")

    def warn(self, code, where, message):
        self.warnings.append(f"WARNING {code} {where}: {message}")

    def obj(self, value, where, spec, partial=False):
        if not isinstance(value, dict):
            self.error("E_TYPE", where, "expected an object")
            return
        optional = set()
        if where in ("styles", "document.defaults") or re.fullmatch(r"elements\[\d+\](?:\.children\[\d+\])*", where):
            spec = {**spec, "heading_numbering": check_options}
            optional.add("heading_numbering")
            if "heading_numbering" in value and self.schema_version != "0.2":
                self.error("E_SCHEMA_EXTENSION", where, "heading_numbering requires schema_version 0.2")
        if spec is NUMBERING or set(spec) == set(NUMBERING):
            optional.update({"template", "start", "restart", "display", "reset", "number_text_separator"})
            if self.schema_version != "0.2" and (any(k in value for k in optional) or value.get("format", "decimal") not in ("decimal", "upper_alpha")):
                self.error("E_SCHEMA_EXTENSION", where, "extended numbering requires schema_version 0.2")
        for key in value:
            if not isinstance(key, str):
                self.error("E_FIELD", where, "keys must be strings")
            elif key.startswith("x-"):
                self.warn("W_EXTENSION", f"{where}.{key}", "extension ignored")
            elif key not in spec:
                self.error("E_FIELD", f"{where}.{key}", "unknown field")
        if not partial:
            for key in spec.keys() - value.keys() - optional:
                self.error("E_REQUIRED", f"{where}.{key}", "required field missing")
        for key, check in spec.items():
            if key in value:
                check(self, value[key], f"{where}.{key}")

    def path(self, value, where, base=None, config=True, kind="file"):
        if not isinstance(value, str) or not value:
            self.error("E_PATH", where, "expected a nonempty relative path")
            return None
        parts = value.split("/")
        win = PureWindowsPath(value)
        if ("\\" in value or win.drive or win.root or value.startswith("/")
                or any(c in value for c in ':?#<>"|*') or any(ord(c) < 32 for c in value)
                or (config and any(p in ("", ".", "..") for p in parts))
                or any(re.search(r"[. ]$", p) for p in parts if p not in (".", ".."))
                or any(is_reserved(p) for p in parts)):
            self.error("E_PATH", where, f"unsafe or nonportable path: {value!r}")
            return None
        try:
            resolved = ((base or self.root) / value).resolve()
            resolved.relative_to(self.root)
        except (OSError, ValueError, RuntimeError):
            self.error("E_PATH", where, f"path escapes project or cannot resolve: {value!r}")
            return None
        if kind == "file" and not resolved.is_file():
            self.error("E_MISSING", where, f"file does not exist: {value}")
        elif kind == "dir" and not resolved.is_dir():
            self.error("E_MISSING", where, f"directory does not exist: {value}")
        return resolved

    def style_ref(self, value, where):
        string(self, value, where)
        if isinstance(value, str) and value not in self.style_names:
            self.error("E_STYLE_REF", where, f"unknown style: {value}")

    def check_metadata(self, data):
        spec = {k: string for k in ("title", "subtitle", "author", "organization", "version",
                                    "status", "date", "language", "description")}
        spec.update(schema_version=enum("0.1", "0.2"), language=language,
                    keywords=array(string, nonempty=True))
        self.obj(data, "metadata", spec)
        if not isinstance(data, dict):
            return
        self.metadata = data
        value = data.get("date")
        if isinstance(value, str):
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError()
                dt.date.fromisoformat(value)
            except ValueError:
                self.error("E_DATE", "metadata.date", "expected an actual YYYY-MM-DD date")

    def check_styles(self, data):
        if isinstance(data, dict) and isinstance(data.get("named_styles"), dict):
            self.style_names.update(k for k in data["named_styles"] if isinstance(k, str)
                                    and not k.startswith("x-"))
        style = mapping({"font": mapping(FONT, partial=True),
                         "paragraph": mapping(PARAGRAPH, partial=True)}, partial=True)
        self.obj(data, "styles", {
            "schema_version": enum("0.1", "0.2"),
            "page": mapping({"paper": enum("A4", "A5", "Letter"),
                             "orientation": enum("portrait", "landscape"),
                             "margins": mapping({k: dimension for k in SIDES}),
                             "header_distance": dimension, "footer_distance": dimension,
                             "mirror_margins": boolean}),
            "font": mapping(FONT), "paragraph": mapping(PARAGRAPH),
            "headings": mapping({f"h{i}": style for i in range(1, 7)}),
            "lists": mapping({"max_depth": integer(1, 6), "bullet_markers": array(string, True),
                              "ordered_formats": array(enum(*FORMATS), True), "ordered_start": integer(1),
                              "indent_per_level": dimension, "hanging": dimension,
                              "space_before": number(0), "space_after": number(0)}),
            "tables": mapping({
                "border": mapping({"style": enum("none", "single", "double"),
                                   "width": number(0, positive=True), "color": color}),
                "width": width, "alignment": enum("left", "center", "right"),
                "cell_padding": mapping({k: dimension for k in SIDES}),
                "repeat_header": boolean, "allow_row_split": boolean, "header_fill": color,
                "banded_rows": mapping({"enabled": boolean, "odd": color, "even": color})}),
            "images": mapping({"max_width": width, "alignment": enum("left", "center", "right"),
                               "space_before": number(0), "space_after": number(0),
                               "caption": mapping({"enabled": boolean, "style": ref,
                                                   "position": enum("above", "below"), "template": template}),
                               "numbering": mapping({"enabled": boolean,
                                                     "scope": enum("document", "chapter"), "start": integer(1)})}),
            "headers_footers": mapping({
                "page_number": mapping({"visible": boolean, "position": enum(*POSITIONS),
                                        "start": integer(1), "format": enum("decimal", "lower_roman", "upper_roman")}),
                "different_first_page": boolean,
                "first_page": mapping({"header_text": text_value, "footer_text": text_value,
                                       "show_page_number": boolean}),
                "header_text": text_value, "footer_text": text_value}),
            "blocks": mapping({k: style for k in BLOCKS}),
            "breaks": mapping({
                "hyphenation": mapping({"enabled": boolean, "language": language, "consecutive_limit": integer(1)}),
                "soft_line_break": enum("space", "line"), "hard_line_break": enum("line"),
                "page_break_marker": enum("<!-- pagebreak -->"), "paragraph_keep_together": boolean,
                "table_pagination": enum("between_rows", "keep_table"),
                "code_long_lines": enum("wrap", "overflow", "error")}),
            "named_styles": any_object})
        if not isinstance(data, dict):
            return
        self.styles = data
        named = data.get("named_styles", {})
        if not isinstance(named, dict):
            return
        builtins = {"body", *(f"h{i}" for i in range(1, 7)), *BLOCKS}
        for name, value in named.items():
            where = f"styles.named_styles.{name}"
            if isinstance(name, str) and name.startswith("x-"):
                self.warn("W_EXTENSION", where, "extension ignored")
                continue
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in builtins:
                self.error("E_STYLE_NAME", where, "invalid or reserved style name")
            self.obj(value, where, {"based_on": ref, "font": mapping(FONT, True),
                                    "paragraph": mapping(PARAGRAPH, True)}, partial=True)
        # Each traversal is bounded by the number of named styles; no recursion on untrusted chains.
        for name in named:
            if not isinstance(name, str) or name.startswith("x-"):
                continue
            current, seen = name, set()
            while current in named and current not in builtins:
                if current in seen:
                    self.error("E_STYLE_CYCLE", f"styles.named_styles.{name}", "based_on cycle")
                    break
                seen.add(current)
                entry = named[current]
                current = entry.get("based_on", "body") if isinstance(entry, dict) else "body"
                if not isinstance(current, str):
                    break

    def check_document(self, data):
        self.obj(data, "document", {
            "schema_version": enum("0.1", "0.2"), "id": identifier, "language": language,
            "metadata": string, "styles": string,
            "build": mapping({"output_dir": string, "output_name": filename}),
            "defaults": mapping({"numbering": mapping(NUMBERING), "style": mapping({"body": ref})}),
            "elements": array(any_object, nonempty=True)})
        if not isinstance(data, dict):
            return
        if data.get("language") != self.metadata.get("language"):
            self.error("E_LANGUAGE", "document.language", "must equal metadata.language")
        build = data.get("build")
        if isinstance(build, dict) and "output_dir" in build:
            self.path(build["output_dir"], "document.build.output_dir", kind="dir")
        defaults = data.get("defaults", {})
        numbering = defaults.get("numbering", {}) if isinstance(defaults, dict) else {}
        if not isinstance(numbering, dict):
            numbering = {}
        inherited = {"enabled": True, "format": "decimal", "scope": "siblings", **numbering}
        elements = data.get("elements", [])
        if not isinstance(elements, list):
            return
        appendix_seen, title_count = False, 0
        for i, node in enumerate(elements):
            if isinstance(node, dict):
                kind = node.get("type")
                if kind == "appendix":
                    appendix_seen = True
                elif appendix_seen:
                    self.error("E_ORDER", f"elements[{i}]", "only appendices may follow an appendix")
                if kind == "title_page":
                    title_count += 1
                    if i != 0 or title_count > 1:
                        self.error("E_ORDER", f"elements[{i}]", "title_page must be unique and first")
            self.walk(node, f"elements[{i}]", None, inherited, True)

    def walk(self, node, where, parent, inherited, active):
        if not isinstance(node, dict):
            return
        spec = {"id": identifier, "type": enum(*TYPES), "source": string,
                "enabled": boolean, "heading": any_object,
                "numbering": mapping(NUMBERING, True),
                "style": mapping({"body": ref, "heading": ref}, True),
                "page_break": mapping({"before": boolean, "after": boolean}, True),
                "children": array(any_object)}
        self.obj(node, where, spec, partial=True)
        for key in ("id", "type", "source"):
            if key not in node:
                self.error("E_REQUIRED", f"{where}.{key}", "required field missing")
        identity, kind = node.get("id"), node.get("type")
        if isinstance(identity, str):
            if identity in self.ids:
                self.error("E_DUPLICATE_ID", where, f"duplicate ID: {identity}")
            else:
                self.ids[identity] = node
        active = active and node.get("enabled", True) is not False
        node_info = {"node": node, "where": where, "active": active, "headings": [], "text": ""}
        self.nodes.append(node_info)
        if parent is None:
            if kind == "section":
                self.error("E_NESTING", where, "section requires a parent")
        elif parent.get("type") not in ("chapter", "section", "appendix") or kind not in ("section", "content"):
            self.error("E_NESTING", where, "invalid child type or parent type")
        heading = node.get("heading")
        if kind != "content" and kind in TYPES:
            if heading is None:
                self.error("E_REQUIRED", where + ".heading", "structural heading required")
            else:
                self.obj(heading, where + ".heading", {"from": enum("markdown", "yaml"),
                                                       "level": integer(1, 6), "text": string}, True)
                if isinstance(heading, dict):
                    for key in ("from", "level"):
                        if key not in heading:
                            self.error("E_REQUIRED", where + ".heading." + key, "required field missing")
                    if heading.get("from") == "yaml" and "text" not in heading:
                        self.error("E_REQUIRED", where + ".heading.text", "YAML heading needs text")
                    if heading.get("from") == "markdown" and "text" in heading:
                        self.error("E_HEADING", where, "Markdown heading must not also have YAML text")
                    parent_heading = parent.get("heading", {}) if parent else {}
                    parent_level = parent_heading.get("level", 0) if isinstance(parent_heading, dict) else 0
                    expected = parent_level + 1 if kind == "section" and type(parent_level) is int else 1
                    if heading.get("level") != expected:
                        self.error("E_HEADING", where, f"heading level must be {expected}")
        elif kind == "content":
            if "heading" in node or (isinstance(node.get("style"), dict) and "heading" in node["style"]):
                self.error("E_HEADING", where, "content cannot declare heading or style.heading")
        own = node.get("numbering", {})
        own = own if isinstance(own, dict) else {}
        effective = {**inherited, **own}
        if parent and parent.get("type") == "appendix" and "format" not in own:
            effective["format"] = "decimal"
        if kind in ("title_page", "frontmatter", "content") and own.get("enabled") is True:
            self.error("E_NUMBERING", where, f"{kind} cannot be numbered")
        if kind == "appendix" and own.get("format") != "upper_alpha":
            self.error("E_NUMBERING", where, "appendix must explicitly set format=upper_alpha")
        if self.schema_version == "0.1" and kind in ("chapter", "section") and effective.get("format") != "decimal":
            self.error("E_NUMBERING", where, "chapter/section requires decimal format")
        if "source" in node:
            source = self.path(node["source"], where + ".source")
            node_info["path"] = source
            if source is not None:
                if source.suffix.lower() != ".md":
                    self.error("E_SOURCE", where, "source must be a Markdown (.md) file")
                key = os.path.normcase(str(source))
                if key in self.sources:
                    self.error("E_DUPLICATE_SOURCE", where, f"duplicate source: {node['source']}")
                else:
                    self.sources[key] = node_info
                if source.is_file():
                    try:
                        text = source.read_text(encoding="utf-8-sig")
                        if not text.strip():
                            self.error("E_SOURCE", where, "empty source")
                        node_info["text"] = text
                        self.markdown(node_info, parent)
                    except (OSError, UnicodeError) as exc:
                        self.error("E_READ", where, str(exc))
        children = node.get("children", [])
        if isinstance(children, list):
            if children and kind not in ("chapter", "section", "appendix"):
                self.error("E_NESTING", where, f"{kind} cannot have children")
            # Depth is bounded by heading levels; stop maliciously deep input early.
            if where.count("children") >= 6 and children:
                self.error("E_NESTING", where, "maximum structural depth exceeded")
                return
            for i, child in enumerate(children):
                self.walk(child, f"{where}.children[{i}]", node, effective, active)

    def placeholders(self, text, where):
        for match in re.finditer(r"\{\{(.*?)\}\}", text, re.S):
            key = match.group(1)
            if not key.startswith("metadata.") or not isinstance(self.metadata.get(key[9:]), str):
                self.error("E_PLACEHOLDER", where, f"unknown/non-string placeholder: {match.group(0)}")
        if "{{" in re.sub(r"\{\{.*?\}\}", "", text, flags=re.S):
            self.error("E_PLACEHOLDER", where, "unclosed placeholder")

    def expand(self, text):
        return re.sub(r"\{\{metadata\.([a-z_]+)\}\}",
                      lambda m: str(self.metadata.get(m[1], m[0])), text)

    def markdown(self, info, parent):
        text, where = info["text"], info["where"]
        text = validate_directives(self, text, where)
        clean_lines, headings = [], []
        fence, container = None, None
        for line_no, line in enumerate(text.splitlines(), 1):
            fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if fence:
                if fence_match and fence_match[1][0] == fence[0] and len(fence_match[1]) >= fence[1] and not fence_match[2].strip():
                    fence = None
                clean_lines.append("")
                continue
            if fence_match:
                fence = (fence_match[1][0], len(fence_match[1]))
                clean_lines.append("")
                continue
            clean_lines.append(line)
            stripped = line.strip()
            if stripped.startswith(":::"):
                if stripped == ":::" and container:
                    container = None
                elif stripped in ("::: note", "::: warning", "::: subtitle") and not container:
                    container = stripped
                else:
                    self.error("E_MARKDOWN", f"{where}:{line_no}", "invalid/nested container")
            match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", line)
            if match:
                label = re.sub(r"\s+#+\s*$", "", match[2])
                headings.append((line_no, len(match[1]), self.expand(label)))
            if re.fullmatch(r" {0,3}(?:=+|-+)\s*", line):
                previous = clean_lines[-2].strip() if len(clean_lines) > 1 else ""
                if previous and not previous.startswith(("#", "|", "-", "*", ">")):
                    self.error("E_MARKDOWN", f"{where}:{line_no}", "Setext headings are outside profile 0.1")
            if re.match(r"^ {0,3}<", line) and stripped != "<!-- pagebreak -->":
                self.error("E_MARKDOWN", f"{where}:{line_no}", "HTML is outside profile 0.1")
            if re.match(r"^ {0,3}\[[^]]+\]:", line):
                self.error("E_MARKDOWN", f"{where}:{line_no}", "reference links are outside profile 0.1")
        if fence:
            self.error("E_MARKDOWN", where, "unclosed fenced code block")
        if container:
            self.error("E_MARKDOWN", where, "unclosed container")
        clean = "\n".join(clean_lines)
        inline_clean = re.sub(r"(`+).*?\1", "", clean, flags=re.S)
        without_pagebreak = inline_clean.replace("<!-- pagebreak -->", "")
        if re.search(r"(?<!\\)<(?:/?[A-Za-z][^>\n]*|!--[^>\n]*--|![A-Za-z][^>\n]*)>", without_pagebreak):
            self.error("E_MARKDOWN", where, "HTML/autolinks are outside profile 0.1")
        self.placeholders(inline_clean, where)
        heading = info["node"].get("heading")
        level = 0
        if isinstance(heading, dict) and type(heading.get("level")) is int:
            level = heading["level"]
            if heading.get("from") == "markdown":
                first = next((i for i, line in enumerate(text.splitlines(), 1) if line.strip()), None)
                if not headings or headings[0][:2] != (first, level):
                    self.error("E_HEADING", where, "first nonblank line must be the declared ATX heading")
                else:
                    for _, depth, _ in headings[1:]:
                        if depth <= level:
                            self.error("E_HEADING", where, "subsequent headings must be deeper than element")
            elif heading.get("from") == "yaml":
                label = heading.get("text", "")
                if isinstance(label, str):
                    self.placeholders(label, where + ".heading.text")
                    headings.insert(0, (0, level, self.expand(label)))
                if any(depth <= level for line, depth, _ in headings if line != 0):
                    self.error("E_HEADING", where, "YAML heading must not be duplicated in Markdown")
        elif parent:
            parent_heading = parent.get("heading", {})
            level = parent_heading.get("level", 0) if isinstance(parent_heading, dict) else 0
            if type(level) is int and any(depth <= level for _, depth, _ in headings):
                self.error("E_HEADING", where, "content headings must be deeper than parent")
        slugs = set()
        for _, _, label in headings:
            base = slug(label)
            candidate, index = base, 2
            while candidate in slugs:
                candidate, index = f"{base}-{index}", index + 1
            slugs.add(candidate)
        info["headings"] = slugs
        info["links_text"] = inline_clean

    def links(self):
        for info in self.nodes:
            text = info.get("links_text", "")
            where = info["where"]
            matched_spans = []
            for match in re.finditer(r"(!?)\[([^\]\n]*)\]\(([^)\n]*)\)", text):
                matched_spans.append(match.span())
                address = re.fullmatch(r'(\S+?)(?:\s+"[^"\n]*")?', match[3])
                if not address:
                    self.error("E_LINK", where, f"invalid inline link: {match[0]}")
                    continue
                target, image = address[1], bool(match[1])
                if re.search(r"%(?![0-9A-Fa-f]{2})", target):
                    self.error("E_LINK", where, "invalid percent encoding")
                    continue
                if target.startswith("md2doc:"):
                    identity = target[7:]
                    if image or not re.fullmatch(r"[a-z][a-z0-9-]*", identity) or identity not in self.ids:
                        self.error("E_LINK", where, f"unknown/invalid element link: {target}")
                    else:
                        self.excluded_link(info, self.ids[identity])
                    continue
                try:
                    parsed = urlsplit(target)
                except ValueError:
                    self.error("E_LINK", where, f"invalid URI: {target}")
                    continue
                if parsed.scheme in ("http", "https", "mailto"):
                    if image or (parsed.scheme == "mailto" and not parsed.path) or (parsed.scheme != "mailto" and not parsed.netloc):
                        self.error("E_LINK", where, f"invalid external link or external image: {target}")
                    continue
                if parsed.scheme or parsed.netloc or parsed.query or "?" in target:
                    self.error("E_PATH", where, f"unsupported URI or unsafe path: {target}")
                    continue
                path_text = unquote(parsed.path)
                if path_text:
                    path = self.path(path_text, where + " link", base=info["path"].parent, config=False)
                else:
                    path = info["path"]
                if path is None:
                    continue
                if image:
                    if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".svg") or parsed.fragment:
                        self.error("E_IMAGE", where, "unsupported image extension or fragment")
                    continue
                other = self.sources.get(os.path.normcase(str(path)))
                if other:
                    self.excluded_link(info, other["node"])
                elif path.suffix.lower() == ".md" and path.is_file():
                    try:
                        path.relative_to(self.root / "content")
                        self.error("E_LINK", where, "Markdown target in content is not in manifest")
                    except ValueError:
                        self.warn("W_AUX_LINK", where, f"auxiliary Markdown is not assembled: {target}")
                if parsed.fragment:
                    if not other or unquote(parsed.fragment) not in other["headings"]:
                        self.error("E_FRAGMENT", where, f"unknown Markdown heading anchor: {target}")
            for match in re.finditer(r"\]\(", text):
                if not any(start <= match.start() < end for start, end in matched_spans):
                    self.error("E_LINK", where, "malformed/unsupported inline link")
            if re.search(r"\[[^]\n]+\]\[[^]\n]*\]", text):
                self.error("E_MARKDOWN", where, "reference links are outside profile 0.1")

    def excluded_link(self, source, target):
        info = next((n for n in self.nodes if n["node"] is target), None)
        if info and source["active"] and not info["active"]:
            self.warn("W_EXCLUDED_LINK", source["where"], f"target excluded from assembly: {target.get('id')}")

    def run(self):
        if not self.root.is_dir():
            raise ConfigError(f"Project directory does not exist: {self.root}")
        manifest_path = self.path("document.yaml", "document.yaml")
        if not manifest_path or not manifest_path.is_file():
            return
        document = load_config(manifest_path)
        if not isinstance(document, dict):
            self.error("E_TYPE", "document", "expected an object")
            return
        self.schema_version = document.get("schema_version", "0.1")
        for key in ("metadata", "styles"):
            if key in document:
                path = self.path(document[key], "document." + key)
                if path is not None and path.is_file():
                    loaded = load_config(path)
                    if isinstance(loaded, dict) and loaded.get("schema_version") != self.schema_version:
                        self.error("E_SCHEMA_MISMATCH", "document." + key, "all three schema_version values must match")
                    if key == "metadata":
                        self.check_metadata(loaded)
                    else:
                        self.check_styles(loaded)
        self.check_document(document)
        for source in sorted((self.root / "content").rglob("*.md")):
            resolved = self.path(source.relative_to(self.root).as_posix(), "content scan")
            if resolved is not None and os.path.normcase(str(resolved)) not in self.sources:
                self.error("E_UNLISTED", str(source.relative_to(self.root)), "Markdown source not in manifest")
        self.links()


def string(v, value, where):
    if not isinstance(value, str) or not value.strip():
        v.error("E_TYPE", where, "expected a nonempty string")


def text_value(v, value, where):
    if not isinstance(value, str):
        v.error("E_TYPE", where, "expected a string (empty allowed)")


def boolean(v, value, where):
    if type(value) is not bool:
        v.error("E_TYPE", where, "expected a boolean")


def any_object(v, value, where):
    if not isinstance(value, dict):
        v.error("E_TYPE", where, "expected an object")


def enum(*values):
    def check(v, value, where):
        if not isinstance(value, str) or value not in values:
            v.error("E_VALUE", where, f"expected one of {', '.join(values)}")
    return check


def number(minimum=None, positive=False):
    def check(v, value, where):
        if type(value) not in (float, int) or (type(value) is float and not math.isfinite(value)):
            v.error("E_TYPE", where, "expected a finite number")
        elif (minimum is not None and value < minimum) or (positive and value <= 0):
            v.error("E_VALUE", where, "number outside permitted range")
    return check


def integer(minimum, maximum=None):
    def check(v, value, where):
        if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
            v.error("E_VALUE", where, f"expected integer >= {minimum}" + (f" and <= {maximum}" if maximum else ""))
    return check


def pattern(regex, description):
    def check(v, value, where):
        if not isinstance(value, str) or not re.fullmatch(regex, value):
            v.error("E_VALUE", where, description)
    return check


def mapping(spec, partial=False):
    return lambda v, value, where: v.obj(value, where, spec, partial)


def array(item, nonempty=False):
    def check(v, value, where):
        if not isinstance(value, list) or (nonempty and not value):
            v.error("E_TYPE", where, "expected " + ("nonempty " if nonempty else "") + "array")
        elif isinstance(value, list):
            for index, entry in enumerate(value):
                item(v, entry, f"{where}[{index}]")
    return check


def width(v, value, where):
    if isinstance(value, str) and re.fullmatch(r"(?:\d+(?:\.\d+)?|\.\d+)%", value):
        if not 0 < float(value[:-1]) <= 100:
            v.error("E_VALUE", where, "percentage must be >0 and <=100")
    elif isinstance(value, str) and re.fullmatch(r"(?:\d+(?:\.\d+)?|\.\d+)(mm|cm|pt|in)", value):
        if not 0 < float(value[:-2]) < float("inf"):
            v.error("E_VALUE", where, "width must be positive and finite")
    else:
        v.error("E_VALUE", where, "expected positive dimension or percentage")


def ref(v, value, where):
    v.style_ref(value, where)


def template(v, value, where):
    string(v, value, where)
    if isinstance(value, str) and re.search(r"[{}]", value.replace("{number}", "").replace("{text}", "")):
        v.error("E_VALUE", where, "template supports only {number} and {text}")


def is_reserved(value):
    return bool(re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", value.split(".")[0]))


def filename(v, value, where):
    if (not isinstance(value, str) or not value.endswith(".docx") or len(value) <= 5
            or any(c in value for c in '/\\:<>"|?*') or any(ord(c) < 32 for c in value) or is_reserved(value)
            or value.endswith((".", " "))):
        v.error("E_PATH", where, "expected a portable plain .docx filename")


def slug(label):
    label = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", label)
    label = re.sub(r"[^\w\s-]", "", label.lower())
    return re.sub(r"\s+", "-", label.strip())


def dimension_value(signed=False):
    def check(v, value, where):
        regex = r"-?(?:\d+(?:\.\d+)?|\.\d+)(?:mm|cm|pt|in)" if signed else r"(?:\d+(?:\.\d+)?|\.\d+)(?:mm|cm|pt|in)"
        if (not isinstance(value, str) or not re.fullmatch(regex, value)
                or not math.isfinite(float(value[:-2]))):
            v.error("E_VALUE", where, "expected finite dimension with mm/cm/pt/in" +
                    (", sign permitted" if signed else ", nonnegative"))
    return check


identifier = pattern(r"[a-z][a-z0-9-]*", "expected ID [a-z][a-z0-9-]*")
language = pattern(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", "expected a language tag, e.g. ru-RU")
color = pattern(r"#[0-9a-fA-F]{6}", "expected #RRGGBB")
dimension = dimension_value()
signed_dimension = dimension_value(signed=True)
SIDES = ("top", "bottom", "left", "right")
BLOCKS = ("code", "quote", "note", "warning", "caption", "title", "subtitle", "appendix_heading")
TYPES = ("title_page", "frontmatter", "chapter", "section", "content", "appendix")
FORMATS = ("decimal", "lower_alpha", "upper_alpha", "lower_roman", "upper_roman")
POSITIONS = tuple(f"{area}_{pos}" for area in ("header", "footer") for pos in ("left", "center", "right"))
FONT = {"family": string, "size": number(0, True), "color": color,
        "bold": boolean, "italic": boolean, "underline": enum("none", "single", "double"),
        "strike": boolean, "case": enum("normal", "uppercase", "lowercase", "small_caps"),
        "character_spacing": number()}
PARAGRAPH = {"alignment": enum("left", "center", "right", "justify"),
             "indent_left": dimension, "indent_right": dimension, "first_line": signed_dimension,
             "space_before": number(0), "space_after": number(0),
             "line_spacing": mapping({"mode": enum("multiple", "exact", "at_least"), "value": number(0, True)}),
             "widow_control": boolean, "keep_with_next": boolean, "keep_together": boolean,
             "page_break_before": boolean}
NUMBERING = {"enabled": boolean, "format": enum(*HEADING_FORMATS), "scope": enum("siblings"),
             **{key: (lambda v, value, where, key=key: check_options(v, {key: value}, where.rsplit('.', 1)[0], False))
                for key in ("template", "start", "restart", "display", "reset", "number_text_separator")}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    validator = Validator(args.project)
    engine = "PyYAML" if yaml is not None else "stdlib JSON-compatible YAML (PyYAML unavailable)"
    print(f"MD2DOC schema 0.1 | parser: {engine}")
    try:
        validator.run()
    except (ConfigError, OSError, RecursionError) as exc:
        for message in validator.errors + validator.warnings:
            print(message)
        print(f"ERROR E_CONFIG: {exc}")
        return 2
    for message in validator.errors + validator.warnings:
        print(message)
    print(f"Checked {len(validator.nodes)} elements; {len(validator.errors)} error(s), "
          f"{len(validator.warnings)} warning(s).")
    return 1 if validator.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
