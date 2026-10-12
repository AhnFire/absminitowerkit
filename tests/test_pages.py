"""Tests for the status pages.

Only the I2C transport is faked: `luma.core.render.canvas` is the real rendering
path, and a small recording device captures the image it is handed. That makes
these tests fast and dependency-light, and lets them inspect actual pixels - no
emulator, no display, no Raspberry Pi.
"""

import pytest

from minitower import pages
from minitower.config import PanelConfig
from minitower.panel import Panel, load_font

pytest.importorskip("luma.core.render")


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


def make_panel(**overrides):
    cfg = PanelConfig(**overrides)
    device = RecordingDevice()
    panel = Panel(cfg, device=device, font=load_font(cfg.font_path, cfg.font_size))
    return panel, device


@pytest.mark.parametrize("name", sorted(pages.PAGES))
def test_every_page_renders(name):
    panel, device = make_panel(pages=(name,))
    panel.render(pages.PAGES[name])
    assert device.image is not None


@pytest.mark.parametrize("name", sorted(pages.PAGES))
def test_no_page_draws_nothing(name):
    """A blank page is a silent regression.

    That is exactly what the original code did on a wired Pi: the wlan0 lookup
    raised, and the `except KeyError` skipped the network line along with the IP
    line, so the panel quietly lost two lines of information.
    """
    panel, device = make_panel(pages=(name,))
    panel.render(pages.PAGES[name])
    assert device.image.convert("L").getbbox() is not None, f"page {name!r} drew nothing"


def test_pages_reflect_the_system_instead_of_hardcoding(monkeypatch):
    """Rendering with different system facts must give different pixels."""
    panel, device = make_panel(pages=("net",))

    monkeypatch.setattr(pages.system, "default_iface", lambda: "eth0")
    monkeypatch.setattr(pages.system, "primary_ipv4", lambda: "10.0.0.5")
    monkeypatch.setattr(pages.system, "net_counters", lambda iface: (1024, 2048))
    panel.render(pages.PAGES["net"])
    from_eth0 = device.image.tobytes()

    monkeypatch.setattr(pages.system, "default_iface", lambda: "wlan0")
    monkeypatch.setattr(pages.system, "primary_ipv4", lambda: "192.0.2.99")
    panel.render(pages.PAGES["net"])

    assert device.image.tobytes() != from_eth0


def test_missing_system_facts_do_not_raise(monkeypatch):
    """Every helper in minitower.system returns None on failure; pages must cope."""
    panel, device = make_panel(pages=("net",))
    monkeypatch.setattr(pages.system, "default_iface", lambda: None)
    monkeypatch.setattr(pages.system, "primary_ipv4", lambda: None)
    monkeypatch.setattr(pages.system, "net_counters", lambda iface: None)

    panel.render(pages.PAGES["net"])

    assert device.image is not None


def test_unknown_page_name_is_rejected():
    with pytest.raises(KeyError, match="unknown page"):
        pages.resolve(("nope",))


def test_font_falls_back_instead_of_raising():
    """Pi OS Lite ships no DejaVu, and PIL's OSError is what crash-looped the
    OLED service on this hardware."""
    assert load_font("/nonexistent/dir/NoSuchFont.ttf", 11) is not None


def test_clear_is_called_on_the_way_out():
    panel, device = make_panel(pages=("load",), refresh_seconds=0.01)
    panel.run(max_seconds=0.05)
    assert device.cleared, "the panel was not cleared on exit"
