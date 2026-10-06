"""A resume or a job posting, uploaded as a file, as the plain text a model reads.

PDF goes through pypdf. Word and OpenDocument files are zipped XML: their text is the XML
with the tags taken out, so no XML parser is involved, and nothing an XML parser can be
tricked into doing can happen. Anything else, paste.
"""

import html
import io
import re
import zipfile

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_BYTES = 5 * 1024 * 1024  # a resume is well under 1MB; this only stops accidents
FORMATS = (".pdf", ".docx", ".odt", ".txt", ".md")

# Where a line ends, in Word, OpenDocument and HTML. Every other tag just goes.
_BREAK = re.compile(r"</w:p>|</text:p>|</text:h>|<text:line-break/>|<w:br/>|</p>|<br\s*/?>|</li>")
_TAB = re.compile(r"<w:tab/>|<text:tab/>")
_TAG = re.compile(r"<[^>]+>")


def plain(markup: str) -> str:
    """Text out of Word's or OpenDocument's XML, or out of HTML, one paragraph a line."""
    text = _TAG.sub("", _TAB.sub(" ", _BREAK.sub("\n", markup)))
    return tidy(html.unescape(text))


def tidy(text: str) -> str:
    """Trailing spaces off, and never more than one blank line in a row."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _pdf(data: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def _zipped(data: bytes, inside: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return plain(archive.read(inside).decode("utf-8"))


def text(name: str, data: bytes) -> str:
    """The text of an uploaded file. Raises ValueError with something the user can act on."""
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in FORMATS:
        raise ValueError(
            f"Can't read {suffix or 'that'} files. Use PDF, Word (.docx), OpenDocument "
            "(.odt), text or Markdown, or paste the text."
        )
    try:
        if suffix == ".pdf":
            found = _pdf(data)
        elif suffix in (".docx", ".odt"):
            found = _zipped(data, "word/document.xml" if suffix == ".docx" else "content.xml")
        else:
            found = data.decode("utf-8", errors="replace")
    except (PdfReadError, zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
        raise ValueError(f"That {suffix} file looks damaged and could not be read.") from exc
    found = tidy(found)
    if not found:
        raise ValueError(
            "No text in that file. A scanned PDF is a picture of text - paste the text instead."
        )
    return found
