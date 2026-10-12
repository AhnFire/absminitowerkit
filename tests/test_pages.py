"""Tests for the status pages.

Only the I2C transport is faked: `luma.core.render.canvas` is the real rendering
path, and a small recording device captures the image it is handed. That keeps
these tests fast and dependency-light, and lets them inspect actual pixels - no
emulator, no display, no Raspberry Pi.
"""

import pytest

from minitower import pages
from minitower.config import PanelConfig
from minitower.panel import Panel
from minitower.sampler import Sample

pytest.importorskip("luma.core.render")

HISTORY = [10.0, 40.0, 90.0, 20.0] * 10


class RecordingDevice:
    """Minimal stand-in for a luma device that keeps the last image shown to it.

    luma's canvas() reads ``device.mode`` and ``device.size``, while the pages
    read ``device.width``/``device.height``, so this provides all four.
    """

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


def full_sample(**overrides) -> Sample:
    """A sample with every field populated, so each page has something to draw."""
    values = {
        "taken_at": 1.0,
        "hostname": "pitower",
        "uptime": "1d 5h 3m",
        "load": (0.52, 0.28, 0.22),
        "cpu_percent": 12.4,
        "memory_percent": 43.0,
        "memory_used": 521 * 1024**2,
        "memory_total": 7800 * 1024**2,
        "disk_percent": 11.0,
        "disk_used": 4_100_000_000,
        "disk_total": 1_800_000_000_000,
        "temperature_c": 40.4,
        "clock_mhz": 1500,
        # A real throttle flag, because an empty one hid the overlap bug: the long
        # phrase used to be drawn through the row label.
        "throttled": ["* low voltage"],
        "iface": "eth0",
        "ip": "10.73.77.24",
        "tx_bytes": 1_200_000_000,
        "rx_bytes": 3_400_000_000,
        "tx_rate": 310_000.0,
        "rx_rate": 1_050_000.0,
        "top": [("python3", 12.4), ("dockerd", 3.1), ("systemd", 0.9)],
    }
    values.update(overrides)
    return Sample(**values)


def make_panel(**overrides):
    cfg = PanelConfig(**overrides)
    device = RecordingDevice()
    return Panel(cfg, device=device), device


@pytest.mark.parametrize("name", sorted(pages.PAGES))
def test_every_page_renders(name):
    panel, device = make_panel(pages=(name,))
    panel.render(pages.PAGES[name], sample=full_sample(), history=HISTORY)
    assert device.image is not None


@pytest.mark.parametrize("name", sorted(pages.PAGES))
def test_no_page_draws_nothing(name):
    """A blank page is a silent regression.

    The original code lost two lines of information on a wired Pi because the
    `wlan0` lookup raised and its `except KeyError` skipped the IP line too.
    """
    panel, device = make_panel(pages=(name,))
    panel.render(pages.PAGES[name], sample=full_sample(), history=HISTORY)
    assert device.image.convert("L").getbbox() is not None, f"page {name!r} drew nothing"


@pytest.mark.parametrize("name", sorted(pages.PAGES))
def test_every_page_survives_having_nothing_to_report(name):
    """Off a Pi there is no vcgencmd, no /proc/uptime and possibly no psutil, so
    every field can be None. Each page must still draw its frame."""
    panel, device = make_panel(pages=(name,))
    panel.render(pages.PAGES[name], sample=Sample(), history=[])
    assert device.image.convert("L").getbbox() is not None


def test_content_follows_the_sample_rather_than_being_hardcoded():
    panel, device = make_panel(pages=("sysinfo",))
    panel.render(pages.PAGES["sysinfo"], sample=full_sample(cpu_percent=99.0), history=HISTORY)
    busy = device.image.tobytes()
    panel.render(pages.PAGES["sysinfo"], sample=full_sample(cpu_percent=1.0), history=HISTORY)
    assert device.image.tobytes() != busy


def test_the_graph_is_driven_by_the_history():
    panel, device = make_panel(pages=("graph",))
    panel.render(pages.PAGES["graph"], sample=full_sample(), history=[0.0] * 40)
    flat = device.image.tobytes()
    spiky = [100.0 if index % 2 else 0.0 for index in range(40)]
    panel.render(pages.PAGES["graph"], sample=full_sample(), history=spiky)
    assert device.image.tobytes() != flat


def test_bordered_pages_are_framed_and_the_clock_is_not():
    """The frame is what makes a page look designed; the clock is deliberately
    full-bleed."""
    for name, page in pages.PAGES.items():
        panel, device = make_panel(pages=(name,))
        panel.render(page, sample=full_sample(), history=HISTORY)
        corner = device.image.convert("L").getpixel((0, 0))
        if page.border:
            assert corner, f"page {name!r} should be framed"
        else:
            assert not corner, f"page {name!r} is meant to be full-bleed"


def test_unknown_page_name_is_rejected():
    with pytest.raises(KeyError, match="unknown page"):
        pages.resolve(("nope",))


def test_font_falls_back_instead_of_raising():
    """Pi OS Lite ships no DejaVu, and PIL's OSError is what crash-looped the
    OLED service on this hardware."""
    from minitower.panel import load_font

    assert load_font("/nonexistent/dir/NoSuchFont.ttf", 10) is not None


def test_clear_is_called_on_the_way_out():
    panel, device = make_panel(pages=("sysinfo",), refresh_seconds=0.01)
    panel.run(max_seconds=0.05)
    assert device.cleared, "the panel was not cleared on exit"
