from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Inline:
    kind: str
    text: str = ""
    attrs: dict = field(default_factory=dict)


@dataclass
class Block:
    kind: str
    text: str = ""
    attrs: dict = field(default_factory=dict)
    children: list["Block"] = field(default_factory=list)
    inlines: list[Inline] = field(default_factory=list)
    line: int = 0
    bookmark: str | None = None
    structural: bool = False
    numbering_override: dict = field(default_factory=dict)
    heading_number: object | None = None


@dataclass
class Element:
    id: str
    kind: str
    source: Path
    body_style: str
    blocks: list[Block]
    number: str = ""
    heading_style: str | None = None
    before: bool = False
    after: bool = False
    children: list["Element"] = field(default_factory=list)
    heading_config: dict = field(default_factory=dict)
    structural_numbering: dict = field(default_factory=dict)


@dataclass
class DocumentModel:
    root: Path
    manifest: dict
    metadata: dict
    styles: dict
    elements: list[Element]
    targets: dict
    validator: object

    def walk(self):
        def visit(elements):
            for element in elements:
                yield element
                yield from visit(element.children)
        return visit(self.elements)
