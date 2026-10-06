"""Resumes and job postings, uploaded as files, read into the text a model is given."""

import io
import zipfile

import pytest

from coach import documents


def pdf(text: str) -> bytes:
    """The smallest real PDF with one line of text on it, offsets and all."""
    stream = f"BT /F1 12 Tf 20 50 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 100] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (n, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def zipped(inside: str, xml: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(inside, xml)
    return buffer.getvalue()


def test_a_pdf_resume_is_read():
    assert "Senior engineer at Acme" in documents.text("cv.PDF", pdf("Senior engineer at Acme"))


def test_word_gives_one_paragraph_a_line_and_its_symbols_back():
    xml = (
        "<w:document><w:body><w:p><w:r><w:t>R&amp;D lead</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Acme</w:t><w:tab/><w:t>2021</w:t></w:r></w:p></w:body></w:document>"
    )
    assert documents.text("cv.docx", zipped("word/document.xml", xml)) == "R&D lead\nAcme 2021"


def test_opendocument_keeps_its_headings_and_line_breaks():
    xml = (
        "<office:text><text:h>Ali</text:h>"
        "<text:p>Backend<text:line-break/>Berlin</text:p></office:text>"
    )
    assert documents.text("cv.odt", zipped("content.xml", xml)) == "Ali\nBackend\nBerlin"


def test_text_and_markdown_are_taken_as_they_are():
    assert documents.text("cv.md", b"# Ali\r\n\r\n\r\n\r\n- Go  \n") == "# Ali\n\n- Go"
    assert documents.text("posting.txt", "Café".encode()) == "Café"


def test_a_job_posting_page_loses_its_html():
    assert documents.plain("<p>We use <b>Go</b> &amp; Postgres</p><ul><li>On call</li></ul>") == (
        "We use Go & Postgres\nOn call"
    )


@pytest.mark.parametrize(
    ("name", "data", "says"),
    [
        ("cv.pages", b"anything", "Can't read .pages"),
        ("cv", b"anything", "Can't read that"),
        ("cv.docx", b"not a zip", "damaged"),
        ("cv.docx", zipped("other.xml", "<x/>"), "damaged"),
        ("cv.pdf", b"%PDF-1.4 and then nothing", "damaged"),
        ("cv.txt", b"  \n\n ", "No text"),
        ("scan.pdf", pdf(""), "No text"),
    ],
)
def test_what_cannot_be_read_says_what_to_do_instead(name, data, says):
    with pytest.raises(ValueError, match=says):
        documents.text(name, data)
