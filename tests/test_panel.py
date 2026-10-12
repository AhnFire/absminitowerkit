"""Tests for the panel loop and its failure paths.

The rotation timer and the "clean error rather than a traceback" promise are the
two things here that are easy to get wrong and impossible to see in a screenshot.
"""

import sys
import types
from pathlib import Path

import pytest

from minitower.config import PanelConfig
from minitower.panel import Panel, PanelError


class RecordingDevice:
    """A luma device that keeps the last image instead of sending it over I2C."""

    mode = "1"

    def __init__(self, width: int = 128, height: int = 64) -> None:
        self.width = width
        self.height = height
        self.size = (width, height)
        self.image = None
        self.cleared = False

    def display(self, image) -> None:
        self.image = image

    def clear(self) -> None:
        self.image = None
        self.cleared = True

    def show(self) -> None:
        pass


def make_panel(**overrides):
    cfg = PanelConfig(**overrides)
    device = RecordingDevice()
    return Panel(cfg, device=device), device


def test_the_loop_rotates_pages_on_the_timer(monkeypatch):
    panel, _ = make_panel(
        pages=("sysinfo", "graph", "clock"), page_seconds=0.02, refresh_seconds=0.005
    )
    seen: list[str] = []
    draw = panel.render

    def spy(page, **kwargs):
        seen.append(page.name)
        draw(page, **kwargs)

    monkeypatch.setattr(panel, "render", spy)
    panel.run(max_seconds=0.12)

    assert len(set(seen)) >= 2, f"the pages never rotated: {seen}"


def test_the_loop_clears_the_display_on_the_way_out():
    panel, device = make_panel(pages=("sysinfo",), page_seconds=0.02, refresh_seconds=0.005)
    panel.run(max_seconds=0.05)
    assert device.cleared, "the display was left showing a stale page"


def test_stopping_does_not_wait_out_the_refresh_interval():
    """run() waits on an Event rather than sleeping, so SIGTERM is acted on at
    once - otherwise a stop could take `refresh_seconds` to take effect."""
    panel, _ = make_panel(pages=("sysinfo",), refresh_seconds=30.0)
    panel.request_stop()

    panel.run()  # would block for 30 seconds if it used time.sleep

    assert panel._stop.is_set()


def test_a_failed_display_open_is_a_clean_error(monkeypatch):
    """An unhelpful luma exception must become an actionable message, because
    this is what a user sees in journalctl on a box with no /dev/i2c-1."""

    class Boom:
        def __init__(self, **_kwargs):
            raise OSError("no such i2c bus")

    fake = types.ModuleType("luma.oled.device")
    fake.ssd1306 = Boom
    monkeypatch.setitem(sys.modules, "luma.oled.device", fake)

    with pytest.raises(PanelError, match="i2c-1"):
        Panel(PanelConfig())


def test_render_named_draws_that_page_and_nothing_else():
    panel, device = make_panel()
    panel.render_named("clock")
    assert device.image is not None
    # the clock is deliberately full-bleed, so the top-left corner stays black
    assert device.image.convert("L").getpixel((0, 0)) == 0


def test_row_height_is_taken_from_the_font(monkeypatch):
    if not Path(PanelConfig().font_path).is_file():
        pytest.skip("needs the real DejaVu font, which the Pi and the package provide")

    short, _ = make_panel(font_size=10)
    tall, _ = make_panel(font_size=18)

    assert tall.row_height > short.row_height
