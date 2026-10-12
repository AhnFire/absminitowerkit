"""Tests for the layout primitives.

Geometry is easy to get subtly wrong - a bar overflowing its column, a value
colliding with its label - and pixel assertions catch that without a display.
"""

import pytest
from PIL import Image, ImageDraw, ImageFont

from minitower import pages, widgets
from minitower.sampler import rate_human

WIDTH, HEIGHT = 128, 64
FONT = ImageFont.load_default()


def canvas():
    image = Image.new("1", (WIDTH, HEIGHT))
    return ImageDraw.Draw(image), image


def test_border_frames_the_whole_canvas():
    draw, image = canvas()
    widgets.border(draw, WIDTH, HEIGHT)
    assert image.getbbox() == (0, 0, WIDTH, HEIGHT)


def test_label_and_value_columns_cannot_collide():
    """The demo this is modelled on drew its bars over its figures; ours may not."""
    draw, _ = canvas()
    assert widgets.value_column(WIDTH) < widgets.bar_span(WIDTH)[0]
    for label, value in (("Temp", "40.4C"), ("Disk", "100%"), ("Sent", "1.9T")):
        label_end = widgets.LABEL_X + widgets.text_width(draw, label, FONT)
        value_start = widgets.value_column(WIDTH) - widgets.text_width(draw, value, FONT)
        assert label_end <= value_start, (label, value)


@pytest.mark.parametrize("fraction", [-1.0, 0.0, 0.5, 1.0, 2.0])
def test_bar_never_leaves_its_span(fraction):
    draw, image = canvas()
    x0, x1 = widgets.bar_span(WIDTH)
    widgets.bar(draw, x0, x1, 10, fraction)
    bbox = image.getbbox()
    assert bbox is not None, "even an empty bar draws its outline"
    assert bbox[0] >= x0
    assert bbox[2] <= x1 + 1


def test_bar_fill_is_proportional_to_the_fraction():
    draw, image = canvas()
    x0, x1 = widgets.bar_span(WIDTH)
    widgets.bar(draw, x0, x1, 10, 0.5)
    row = 10 + widgets.BAR_H // 2
    filled = sum(1 for x in range(x0, x1 + 1) if image.getpixel((x, row)))
    span = x1 - x0 + 1
    assert 0.35 * span < filled < 0.75 * span


def test_histogram_stays_inside_its_box():
    draw, image = canvas()
    box = (3, 17, WIDTH - 4, 48)
    widgets.histogram(draw, box, [100.0] * 40)
    bbox = image.getbbox()
    assert bbox[0] >= box[0] and bbox[1] >= box[1]
    assert bbox[2] <= box[2] + 1 and bbox[3] <= box[3] + 1


def test_histogram_handles_an_empty_history():
    draw, image = canvas()
    widgets.histogram(draw, (3, 17, 124, 48), [])
    assert image.getbbox() is not None, "the box outline should still be drawn"


def test_temperature_fraction_covers_the_useful_range():
    assert pages.temperature_fraction(None) == 0.0
    assert pages.temperature_fraction(20.0) == pytest.approx(0.0)
    assert pages.temperature_fraction(85.0) == pytest.approx(1.0)
    assert 0.0 < pages.temperature_fraction(40.4) < 0.5


def test_rate_fraction_spans_four_usable_decades():
    assert pages.rate_fraction(0.0) == 0.0
    assert pages.rate_fraction(10_000 / 8) <= 0.01
    assert pages.rate_fraction(1_000_000 / 8) == pytest.approx(0.4, abs=0.05)
    assert pages.rate_fraction(100_000_000 / 8) == pytest.approx(0.8, abs=0.05)
    assert pages.rate_fraction(1_000_000_000) == 1.0


def test_rate_human_reports_bits_not_bytes():
    assert rate_human(0) == "0"
    assert rate_human(125_000) == "1.0M"
    assert rate_human(125_000_000) == "1.0G"
