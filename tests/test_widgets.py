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


def test_histogram_ignores_bars_with_no_height():
    draw, image = canvas()
    widgets.histogram(draw, (3, 17, 124, 48), [0.0] * 8)
    assert image.getbbox() == (3, 17, 125, 49), "only the box outline should be drawn"


def test_histogram_stops_when_it_runs_out_of_room():
    """More samples than pixels: the loop must stop at the box edge, not run off it."""
    draw, image = canvas()
    widgets.histogram(draw, (3, 17, 10, 20), [100.0] * 1000)
    assert image.getbbox()[2] <= 11


def test_fit_font_falls_back_instead_of_raising():
    draw, _ = canvas()
    assert widgets.fit_font(draw, "12:34", "/nonexistent/NoSuchFont.ttf", 100, 30) is not None


def _drawn_between(image, label_end: int, band=range(40, 52)) -> set[int]:
    """Which of the gap columns right after a label have anything drawn in them."""
    return {
        x
        for x in range(label_end, label_end + widgets.COLUMN_GAP)
        if any(image.getpixel((x, y)) for y in band)
    }


def test_clip_text_trims_to_fit():
    draw, _ = canvas()
    original = "undervoltage has occurred"

    clipped = widgets.clip_text(draw, original, FONT, 40)

    assert clipped, "something should survive the clip"
    assert original.startswith(clipped), "clipping must only remove from the end"
    assert widgets.text_width(draw, clipped, FONT) <= 40


def test_clip_text_leaves_short_text_alone():
    draw, _ = canvas()
    assert widgets.clip_text(draw, "ok", FONT, 40) == "ok"


def test_text_row_never_draws_a_value_over_its_label():
    """Reported from the Pi: "the word power and undervoltage are overlapping".

    text_row right-aligns its value at the full width, so a long value used to be
    drawn straight over the label.
    """
    draw, image = canvas()
    widgets.text_row(draw, FONT, 40, "power", "undervoltage has occurred", WIDTH)

    label_end = widgets.LABEL_X + widgets.text_width(draw, "power", FONT)

    assert not _drawn_between(image, label_end), "the value is drawn against its label"


def test_bar_row_never_draws_a_value_over_its_label():
    draw, image = canvas()
    widgets.bar_row(draw, FONT, 40, "Sent", "1.2G/3.4G", WIDTH, None)

    label_end = widgets.LABEL_X + widgets.text_width(draw, "Sent", FONT)

    assert not _drawn_between(image, label_end)


def test_the_title_value_cannot_reach_the_title():
    draw, image = canvas()
    widgets.title(draw, FONT, 40, "NET wlan0", WIDTH, right="10.73.77.24")

    label_end = widgets.LABEL_X + widgets.text_width(draw, "NET wlan0", FONT)

    assert not _drawn_between(image, label_end)
