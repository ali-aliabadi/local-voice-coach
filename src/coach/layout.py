"""A few pages of text, drawn with Pillow: the study sheet's typesetting.

Pillow already draws the charts and can save pages as a PDF, so the printable report and
the images sent to Telegram come from one renderer, with no PDF library added. The text
is drawn rather than embedded, so it cannot be selected - a study sheet does not need to.
"""

import io
import pathlib
import unicodedata

from PIL import Image, ImageDraw, ImageFont

from . import config, picture

W, H, MARGIN = 1240, 1754, 100  # A4 at 150 dpi
WIDTH = W - 2 * MARGIN
FOOT = 70  # kept clear at the bottom for the page number
GOOD, FAR = "#067d5f", "#b5501f"
# What Pillow's own font cannot draw, for when the real font is missing.
ASCII = {
    "→": "->",
    "—": "-",
    "–": "-",
    "•": "*",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "…": "...",
}


class Doc:
    """Pages that fill top to bottom; a new one starts whenever the next line will not fit."""

    def __init__(self, footer: str = "") -> None:
        self.footer = footer
        self.pages: list[Image.Image] = []
        self.fonts: dict = {}
        self.plain = not pathlib.Path(config.REPORT_FONT).exists()
        self._page()

    def _page(self) -> None:
        self.pages.append(Image.new("RGB", (W, H), picture.SURFACE))
        self.draw = ImageDraw.Draw(self.pages[-1])
        self.y = MARGIN

    def font(self, size: int, bold: bool = False):
        if (size, bold) not in self.fonts:
            if self.plain:
                font = ImageFont.load_default(size=size)
            else:
                font = ImageFont.truetype(config.REPORT_FONT, size)
                font.set_variation_by_name("Bold" if bold else "Regular")
            self.fonts[size, bold] = font
        return self.fonts[size, bold]

    def clean(self, text: str) -> str:
        if not self.plain:
            return text
        for fancy, plain in ASCII.items():
            text = text.replace(fancy, plain)
        return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()

    def room(self, height: int) -> None:
        if self.y + height > H - MARGIN - FOOT:
            self._page()

    def text(self, text, size=26, bold=False, color=picture.INK, indent=0, after=14) -> None:
        font = self.font(size, bold)
        step = round(size * 1.45)
        for line in wrap(self.clean(str(text)), font, WIDTH - indent):
            self.room(step)
            self.draw.text((MARGIN + indent, self.y), line, font=font, fill=color)
            self.y += step
        self.y += after

    def heading(self, text: str) -> None:
        self.room(200)  # never strand a heading at the foot of a page
        self.y += 30
        self.text(text, size=34, bold=True, after=6)
        self.draw.line((MARGIN, self.y, W - MARGIN, self.y), fill=picture.LINE, width=2)
        self.y += 22

    def bullet(self, text: str, marker: str = "•", **style) -> None:
        self.room(40)
        self.draw.text(
            (MARGIN, self.y), self.clean(marker), font=self.font(26), fill=picture.ACCENT
        )
        self.text(text, indent=44, after=10, **style)

    def tiles(self, items: list[tuple[str, str, str, bool]]) -> None:
        """A row of numbers: (value, what it is, a verdict, whether the verdict is good)."""
        gap = 24
        width = (WIDTH - gap * (len(items) - 1)) / len(items)
        self.room(170)
        for i, (value, label, note, good) in enumerate(items):
            x = MARGIN + i * (width + gap)
            self.draw.rounded_rectangle((x, self.y, x + width, self.y + 160), 16, fill=picture.PAGE)
            self.draw.text((x + 20, self.y + 18), value, font=self.font(44, True), fill=picture.INK)
            for n, line in enumerate(wrap(self.clean(label), self.font(19), width - 40)[:2]):
                self.draw.text(
                    (x + 20, self.y + 76 + n * 24), line, font=self.font(19), fill=picture.MUTED
                )
            colour = GOOD if good else FAR
            self.draw.text(
                (x + 20, self.y + 128), self.clean(note), font=self.font(19), fill=colour
            )
        self.y += 184

    def _numbered(self) -> list[Image.Image]:
        if getattr(self, "stamped", False):  # pdf() and pngs() on the same doc
            return self.pages
        self.stamped = True
        for n, page in enumerate(self.pages, 1):
            stamp = f"{self.footer}  ·  page {n} of {len(self.pages)}".strip(" ·")
            ImageDraw.Draw(page).text(
                (W / 2, H - MARGIN + 10), self.clean(stamp), font=self.font(18),
                fill=picture.MUTED, anchor="ma",
            )  # fmt: skip
        return self.pages

    def pdf(self) -> bytes:
        out = io.BytesIO()
        first, *rest = self._numbered()
        first.save(out, "PDF", save_all=True, append_images=rest, resolution=150)
        return out.getvalue()

    def pngs(self) -> list[bytes]:
        out = []
        for page in self._numbered():
            buffer = io.BytesIO()
            page.save(buffer, "PNG", optimize=True)
            out.append(buffer.getvalue())
        return out


def wrap(text: str, font, width: float) -> list[str]:
    """Greedy word wrap by measured width. A word wider than the line gets a line alone."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and font.getlength(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return [*lines, line] if line else lines
