"""SSD1306 status panel: a rotating display of system pages.

Why this differs from the vendor's sysinfo.py:

* the panel is constructed directly (`ssd1306(port=..., address=...)`) instead
  of through luma.examples' demo helper, so no demo scaffolding is in the
  runtime path;
* the font is loaded with a fallback, because Pi OS Lite has no DejaVu and the
  resulting `OSError` crash-looped the service on this hardware;
* pages rotate on a timer inside one process, replacing the shell loop that
  spawned and killed a python process every 10 seconds - which is what left an
  orphaned renderer behind when the service was stopped;
* the row step comes from the font's own metrics instead of a hardcoded 12 px,
  which is what made a larger font collide with itself;
* SIGTERM clears the panel and exits 0.
"""

from __future__ import annotations

import logging
import signal
import threading
import time

from PIL import ImageFont

from . import pages as pages_module
from . import widgets
from .config import PanelConfig
from .sampler import Sampler

log = logging.getLogger("minitower.panel")


class PanelError(RuntimeError):
    """Raised when the display cannot be opened or used."""


def load_font(path: str, size: int):
    """DejaVu when it is installed, Pillow's bitmap font otherwise.

    Never raises: a missing font must not be able to take the display down.
    """
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        log.warning("panel: font %s unavailable, falling back to Pillow default", path)
        return ImageFont.load_default()


def _open_device(cfg: PanelConfig):
    """Open the I2C panel, translating failures into an actionable message."""
    try:
        from luma.oled.device import ssd1306
    except ImportError as exc:
        raise PanelError("luma.oled is missing: sudo apt install python3-luma.oled") from exc

    try:
        return ssd1306(port=cfg.i2c_port, address=cfg.i2c_address)
    except Exception as exc:
        raise PanelError(
            f"cannot open the panel on i2c-{cfg.i2c_port} at 0x{cfg.i2c_address:02X}: {exc}. "
            f"Check that /dev/i2c-{cfg.i2c_port} exists (the i2c-dev module must be loaded) "
            f"and that `i2cdetect -y {cfg.i2c_port}` lists the address."
        ) from exc


class Panel:
    """Rotates through status pages on an SSD1306 display."""

    def __init__(self, cfg: PanelConfig, device=None, font=None) -> None:
        self.cfg = cfg.validated()
        self.pages = pages_module.resolve(self.cfg.pages)
        self._font = font if font is not None else load_font(self.cfg.font_path, self.cfg.font_size)
        self._bold = load_font(self.cfg.font_bold_path, self.cfg.font_size)
        self._device = device if device is not None else _open_device(self.cfg)
        self._stop = threading.Event()
        # Only pay for per-process sampling when a page actually shows it.
        self._sampler = Sampler(want_top="top" in self.cfg.pages)

    @property
    def row_height(self) -> int:
        """Row step taken from the font's own metrics.

        A hardcoded 12 px step was what made larger fonts collide with
        themselves; the reference demos use metrics - 1 and look right.
        """
        try:
            ascent, descent = self._font.getmetrics()
            return max(9, ascent + descent - 1)
        except Exception:  # pragma: no cover - Pillow's bitmap fallback font
            return 11

    @property
    def device(self):
        """The display device, exposed so callers and tests can inspect it."""
        return self._device

    # ----------------------------------------------------------------- output
    def render(self, page: pages_module.Page, *, sample=None, history=None) -> None:
        """Draw one page into an already-open canvas.

        `sample` and `history` default to the live ones but can be supplied, so a
        page can be rendered to a throwaway canvas for a preview or a test.
        """
        from luma.core.render import canvas

        with canvas(self._device, dither=page.dither) as draw:
            ctx = pages_module.Ctx(
                draw=draw,
                font=self._font,
                bold=self._bold,
                width=self._device.width,
                height=self._device.height,
                row_h=self.row_height,
                font_path=self.cfg.font_path,
                sample=sample if sample is not None else self._sampler.latest,
                history=history if history is not None else self._sampler.cpu_history(),
            )
            if page.border:
                widgets.border(draw, ctx.width, ctx.height)
            page.draw(ctx)

    def render_named(self, name: str) -> None:
        """Draw a single page by name (used by --page and by the tests)."""
        for page in pages_module.resolve((name,)):
            self.render(page)

    def clear(self) -> None:
        """Wipe the display; called on every exit path."""
        try:
            self._device.clear()
            self._device.show()
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.warning("panel: could not clear the display: %s", exc)

    # -------------------------------------------------------------- lifecycle
    def request_stop(self, *_args: object) -> None:
        self._stop.set()

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self.request_stop)

    def run(self, *, max_seconds: float | None = None) -> None:
        """Rotate pages until SIGTERM/SIGINT, or for max_seconds (tests)."""
        self.install_signal_handlers()
        started = time.monotonic()
        index = 0
        next_page_at = started + self.cfg.page_seconds
        log.info(
            "panel: %d page(s) %s, %.0fs each, refreshing every %.1fs",
            len(self.pages),
            ", ".join(page.name for page in self.pages),
            self.cfg.page_seconds,
            self.cfg.refresh_seconds,
        )
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if max_seconds is not None and now - started >= max_seconds:
                    break
                if now >= next_page_at:
                    index = (index + 1) % len(self.pages)
                    next_page_at = now + self.cfg.page_seconds
                    log.info("panel: page %s", self.pages[index].name)
                # Sample before drawing, so the page shows current numbers and
                # the histogram gains a point per refresh even while it is not
                # the page on screen.
                sample = self._sampler.sample_once()
                self.render(self.pages[index], sample=sample)
                self._stop.wait(self.cfg.refresh_seconds)
        finally:
            log.info("panel: clearing the display and exiting")
            self.clear()
