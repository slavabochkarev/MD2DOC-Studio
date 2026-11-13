from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from md2doc.diagnostics.report import BuildError
from md2doc.renderers.integrity import verify_docx
from conftest import successful


@pytest.mark.parametrize("member,old,new", [
    ("word/document.xml", b'w:anchor="md_', b'w:anchor="missing_md_'),
    ("word/_rels/document.xml.rels", b'Target="styles.xml"', b'Target="missing.xml"'),
    ("word/numbering.xml", b'w:abstractNumId w:val="0"', b'w:abstractNumId w:val="99999"'),
])
def test_integrity_rejects_dangling_objects(project, member, old, new):
    project.add(text="# Main\n\n[Self](#main)\n\n- Item")
    successful(project)
    broken = project.root / "output/broken.docx"
    with ZipFile(project.output) as source, ZipFile(broken, "w", ZIP_DEFLATED) as target:
        for name in source.namelist():
            raw = source.read(name)
            if name == member:
                assert old in raw
                raw = raw.replace(old, new, 1)
            target.writestr(name, raw)
    with pytest.raises(BuildError) as error:
        verify_docx(broken)
    assert error.value.diagnostic.code == "E_DOCX_INTEGRITY"
