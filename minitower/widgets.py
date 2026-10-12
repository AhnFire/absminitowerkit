"""Layout primitives for the panel.

Everything draws in integer pixel coordinates on a 128x64 mono canvas, and the
column geometry is derived from the canvas width so a 128x32 or 96x16 panel
still renders something sensible.

The look deliberately follows the luma.examples system demos, because that is
what people recognise as "a proper readout": a full-screen frame, labels on the
left, values right-aligned in a fixed column, and an outlined bar with a filled
portion showing the proportion.
"""

from __future__ import annotations

PAD = 3          # gap between the frame and the content
ROW_H = 11       # vertical step between rows
FIRST_ROW_Y = 4
BAR_H = 7        # bar outer height (5px of fill inside it)
LABEL_X = PAD + 1


def border(draw, width: int, height: int) -> None:
    """The full-screen frame. On its own this is the biggest visual upgrade."""
    draw.rectangle((0, 0, width - 1, height - 1), outline="white")


def divider(draw, y: int, width: int) -> None:
    draw.line((LABEL_X, y, width - 1 - LABEL_X, y), fill="white")


def text_width(draw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def text_right(draw, font, y: int, text: str, right_edge: int) -> None:
    """Draw `text` so that it ends at `right_edge`."""
    draw.text((right_edge - text_width(draw, text, font), y), text, font=font, fill="white")


def title(draw, font, y: int, text: str, width: int, *, right: str | None = None) -> None:
    """Bold label on the left, optional right-aligned value."""
    draw.text((LABEL_X, y), text, font=font, fill="white")
    if right:
        text_right(draw, font, y, right, width - 1 - LABEL_X)


def value_column(width: int) -> int:
    """Right edge of the numeric value column."""
    return int(width * 0.60)


def bar_span(width: int) -> tuple[int, int]:
    """Left and right edge of the bar column."""
    return (int(width * 0.63), width - 1 - LABEL_X)


def bar(draw, x0: int, x1: int, y: int, fraction: float, *, height: int = BAR_H) -> None:
    """Outlined bar with a filled portion - the classic readout."""
    fraction = min(1.0, max(0.0, fraction))
    draw.rectangle((x0, y, x1, y + height), outline="white")
    inner = x1 - x0 - 2
    if inner <= 0 or fraction <= 0:
        return
    filled = max(1, int(round(inner * fraction)))
    draw.rectangle((x0 + 1, y + 1, x0 + filled, y + height - 1), fill="white")


def bar_row(
    draw, font, y: int, label: str, value: str, width: int, fraction: float | None
) -> None:
    """`CPU        12%  [####      ]` - one complete readout row.

    A fraction of None draws the label and value only, for rows that have no
    meaningful proportion (a throttle flag, a lifetime total).
    """
    draw.text((LABEL_X, y), label, font=font, fill="white")
    text_right(draw, font, y, value, value_column(width))
    if fraction is None:
        return
    x0, x1 = bar_span(width)
    bar(draw, x0, x1, y + 1, fraction)


def text_row(draw, font, y: int, left: str, right: str, width: int) -> None:
    """Two-column text row for values that are not proportions."""
    draw.text((LABEL_X, y), left, font=font, fill="white")
    text_right(draw, font, y, right, width - 1 - LABEL_X)


def centre(draw, font, y: int, text: str, width: int) -> None:
    """Horizontally centre `text` - a clock that is 3 px off looks broken."""
    draw.text(((width - text_width(draw, text, font)) // 2, y), text, font=font, fill="white")


def histogram(draw, box: tuple[int, int, int, int], values: list[float], maximum: float = 100.0) -> None:
    """Vertical bars inside an outlined box; newest sample on the right."""
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline="white")
    inner_w = (x1 - x0) - 2
    inner_h = (y1 - y0) - 2
    if not values or inner_w <= 0 or inner_h <= 0:
        return
    step = inner_w / len(values)
    width = max(1, int(step) - 1) if step >= 2 else 1
    for index, raw in enumerate(values):
        level = min(1.0, max(0.0, raw / maximum))
        height = int(round(inner_h * level))
        if height <= 0:
            continue
        left = x0 + 1 + int(index * step)
        if left + width > x1:
            break
        draw.rectangle((left, y1 - 1 - height, left + width - 1, y1 - 1), fill="white")


def fit_font(draw, text: str, font_path: str, max_width: int, max_size: int, *, minimum: int = 8):
    """Largest font size (<= max_size) at which `text` fits in max_width."""
    from PIL import ImageFont

    for size in range(max_size, minimum - 1, -1):
        try:
            font = ImageFont.truetype(font_path, size)
        except OSError:
            return ImageFont.load_default()
        if text_width(draw, text, font) <= max_width:
            return font
    return ImageFont.truetype(font_path, minimum)
