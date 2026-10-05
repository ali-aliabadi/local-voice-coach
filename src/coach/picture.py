"""Charts as PNG, for places with no browser: the reports sent to your phone.

Four small panels, one per metric, on the same fixed scales and goal bands as the charts
in the app. SERIES mirrors SERIES in web/chart.js; a test keeps the two in step.
"""

import io
import math
import statistics

from PIL import Image, ImageDraw, ImageFont

# key: (label, domain, goal) - the same windows as web/chart.js, so a phone and the app agree
SERIES = {
    "wpm": ("words per minute", (60, 180), (140, 160)),
    "fillers": ("fillers per 100 words", (0, 10), (0, 2)),
    "pauses": ("pauses per minute", (0, 20), (0, 5)),
    "lead_in": ("seconds before you start", (0, 6), (0, 1.5)),
}
# The size of change worth saying out loud, and how to say it - MOVED and PHRASE in
# web/chart.js, so a change reads the same on a phone as in the app.
MOVED = {"wpm": 4, "fillers": 0.4, "pauses": 0.8, "lead_in": 0.3}
PHRASE = {
    "wpm": lambda d, better: f"{abs(d):.0f} wpm {'faster' if better else 'slower'}",
    "fillers": lambda d, better: (
        f"{abs(d):.1f} {'fewer' if better else 'more'} fillers per 100 words"
    ),
    "pauses": lambda d, better: f"{abs(d):.1f} {'fewer' if better else 'more'} pauses a minute",
    "lead_in": lambda d, better: f"{abs(d):.1f}s {'quicker' if better else 'slower'} to start",
}


def shifts(before: dict, now: dict) -> list[str]:
    """What moved more than noise from `before` to `now`, in words."""
    said = []
    for key, threshold in MOVED.items():
        a, b = before.get(key), now.get(key)
        if a is not None and b is not None and abs(b - a) >= threshold:
            said.append(PHRASE[key](b - a, b > a if key == "wpm" else b < a))
    return said


# The light theme's tokens from web/style.css: Telegram shows images on either theme, and
# light reads on both.
PAGE, SURFACE, INK, MUTED = "#f4f9fd", "#ffffff", "#16232f", "#5c7285"
LINE, ACCENT, GOAL = "#dde8f1", "#1c6fbe", "#dbeaf8"
# The trend, in the warn colour: blue and orange stay apart under every colour blindness,
# and it is dashed so it does not rest on colour alone.
TREND_COLOUR = "#b5501f"
TREND = "The dashed orange line is the trend."

W, H = 1200, 760  # drawn at twice the size it is read at, so it stays sharp on a phone
PANEL_W, PANEL_H, GAP = 570, 345, 20


def _font(size: int):
    return ImageFont.load_default(size=size)


def _shown(key: str, value: float) -> str:
    return f"{value:.0f}" if key == "wpm" else f"{value:.1f}"


def _dashed(draw, start: tuple, end: tuple, dash: int = 16, gap: int = 10) -> None:
    (x0, y0), (x1, y1) = start, end
    length = math.hypot(x1 - x0, y1 - y0) or 1
    for at in range(0, int(length), dash + gap):
        a, b = at / length, min(at + dash, length) / length
        segment = (x0 + (x1 - x0) * a, y0 + (y1 - y0) * a, x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)
        draw.line(segment, fill=TREND_COLOUR, width=4)


def _panel(draw, x0: int, y0: int, key: str, values: list[float], labels, headline):
    label, (lo, hi), (glo, ghi) = SERIES[key]
    draw.rounded_rectangle((x0, y0, x0 + PANEL_W, y0 + PANEL_H), 18, fill=SURFACE)
    # The headline is the average over the whole period, never the last point: one good
    # final answer must not stand in for the session.
    if headline is not None:
        draw.text((x0 + 28, y0 + 22), _shown(key, headline), font=_font(44), fill=INK)
    draw.text((x0 + 28, y0 + 76), label, font=_font(22), fill=MUTED)

    left, right, top, bottom = x0 + 72, x0 + PANEL_W - 28, y0 + 120, y0 + PANEL_H - 44
    peak = max([hi, *values])  # like the app: only grow the window when someone exceeds it

    def y(v: float) -> float:
        return bottom - (min(max(v, lo), peak) - lo) / (peak - lo) * (bottom - top)

    draw.rectangle((left, y(ghi), right, y(glo)), fill=GOAL)
    for v in (lo, (lo + peak) / 2, peak):
        draw.line((left, y(v), right, y(v)), fill=LINE, width=2)
        draw.text((left - 12, y(v)), _shown(key, v), font=_font(18), fill=MUTED, anchor="rm")
    if values:
        step = (right - left) / max(1, len(values) - 1)
        points = [(left + i * step if len(values) > 1 else (left + right) / 2, y(v))
                  for i, v in enumerate(values)]  # fmt: skip
        if len(points) > 1:
            draw.line(points, fill=ACCENT, width=5, joint="curve")
        if len(values) > 2:  # through two points the trend is the line itself
            fit = statistics.linear_regression(range(len(values)), values)
            last = fit.intercept + fit.slope * (len(values) - 1)
            _dashed(draw, (points[0][0], y(fit.intercept)), (points[-1][0], y(last)))
        px, py = points[-1]
        draw.ellipse((px - 8, py - 8, px + 8, py + 8), fill=ACCENT, outline=SURFACE, width=3)
    if labels:
        draw.text((left, bottom + 12), labels[0], font=_font(18), fill=MUTED)
        draw.text((right, bottom + 12), labels[-1], font=_font(18), fill=MUTED, anchor="ra")


def panels(rows: list[dict], labels: list[str], headline: dict) -> bytes:
    """A 2x2 PNG of the four metrics across `rows`, labelled by `labels` at either end, each
    headed by its value in `headline` - the period's average."""
    image = Image.new("RGB", (W, H), PAGE)
    draw = ImageDraw.Draw(image)
    for i, key in enumerate(SERIES):
        x0 = GAP + (i % 2) * (PANEL_W + GAP)
        y0 = GAP + (i // 2) * (PANEL_H + GAP)
        values = [float(r[key]) for r in rows if r.get(key) is not None]
        _panel(draw, x0, y0, key, values, labels, headline.get(key))
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()
