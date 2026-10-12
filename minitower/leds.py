"""WS281X mood light / RGB fan light driver.

The animation is a pure function of elapsed time and the hardware is injected,
so the whole thing is testable with no strip attached:

    frame = ring.frame_for(1.5)     # -> [(r, g, b), ...]
    ring.apply(frame)               # only this method touches hardware

Two behaviours matter more than the pretty colours:

* the strip is blanked whatever the exit path, because the vendor's binary left
  the LEDs latched on its last frame when it was stopped;
* a failed initialisation is reported cleanly rather than segfaulting, which is
  what the rpi_ws281x binding does if you keep using an object whose begin()
  failed (observed on this hardware when run without root).
"""

from __future__ import annotations

import colorsys
import logging
import os
import signal
import threading
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

from .config import LedConfig

log = logging.getLogger("minitower.leds")

RGB = tuple[int, int, int]


class LedInitError(RuntimeError):
    """Raised when the strip cannot be opened."""


class StripLike(Protocol):
    """The slice of rpi_ws281x's PixelStrip that this module actually uses."""

    def setPixelColor(self, index: int, color: int) -> None: ...
    def show(self) -> None: ...


def _open_strip(cfg: LedConfig) -> StripLike:
    """Open the strip, turning the library's failure modes into clean errors."""
    # getattr rather than os.geteuid(): that only exists on POSIX, and this keeps
    # the module importable and type-clean elsewhere. The /dev/vcio check below
    # is what actually rejects a machine that is not a Pi.
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None and geteuid() != 0:
        raise LedInitError(
            "the WS281X driver needs root (it maps the DMA/PWM registers via "
            "/dev/vcio); run it under systemd as root, or with sudo"
        )
    if not Path("/dev/vcio").exists():
        raise LedInitError("/dev/vcio is missing - is this really a Raspberry Pi?")

    try:
        import rpi_ws281x
    except ImportError as exc:  # pragma: no cover - depends on the host
        raise LedInitError(
            "rpi_ws281x is not installed: sudo pip3 install --break-system-packages rpi-ws281x"
        ) from exc

    strip_order = getattr(rpi_ws281x, cfg.strip_order, None)
    if strip_order is None:
        raise LedInitError(
            f"unknown strip order {cfg.strip_order!r}; expected one of "
            "WS2812_STRIP, WS2811_STRIP_GRB, WS2811_STRIP_RGB, ..."
        )

    strip = rpi_ws281x.PixelStrip(
        cfg.pixel_count,
        cfg.gpio,
        800000,
        10,
        False,
        cfg.brightness,
        0,
        strip_order,
    )
    strip.begin()
    return strip


def build_gamma(gamma: float) -> list[int]:
    """256-entry table mapping an ideal intensity to a perceived one."""
    return [min(255, round((i / 255.0) ** gamma * 255.0)) for i in range(256)]


class LedRing:
    """Renders a slow, smooth colour drift onto a WS281X strip."""

    def __init__(self, cfg: LedConfig, strip: StripLike | None = None) -> None:
        self.cfg = cfg.validated()
        self._gamma = build_gamma(self.cfg.gamma)
        self._strip = strip if strip is not None else _open_strip(self.cfg)
        self._stop = threading.Event()

    # ----------------------------------------------------------------- frames
    def _pack(self, rgb: RGB) -> int:
        r, g, b = (self._gamma[channel] for channel in rgb)
        return (r << 16) | (g << 8) | b

    def _hue_frame(self, base_hue: float, spread: float) -> list[RGB]:
        frame: list[RGB] = []
        for index in range(self.cfg.pixel_count):
            hue = (base_hue + index * spread) % 360.0
            r, g, b = colorsys.hsv_to_rgb(hue / 360.0, 1.0, 1.0)
            frame.append((int(r * 255), int(g * 255), int(b * 255)))
        return frame

    def gradient_frame(self, base_hue: float) -> list[RGB]:
        """A hue gradient spread across the ring, shifted by base_hue."""
        return self._hue_frame(base_hue, self.cfg.hue_spread_deg)

    def solid_frame(self, base_hue: float) -> list[RGB]:
        """Every pixel the same colour, drifting through the hue wheel."""
        return self._hue_frame(base_hue, 0.0)

    def frame_for(self, elapsed_seconds: float) -> list[RGB]:
        """The frame to show `elapsed_seconds` after start. Pure, so testable."""
        base_hue = (elapsed_seconds * self.cfg.hue_speed_deg_per_s) % 360.0
        if self.cfg.mode == "solid":
            return self.solid_frame(base_hue)
        return self.gradient_frame(base_hue)

    # ----------------------------------------------------------------- output
    def apply(self, frame: Sequence[RGB]) -> None:
        """Push one frame - the only method here that touches hardware."""
        if len(frame) != self.cfg.pixel_count:
            raise ValueError(f"frame has {len(frame)} pixels, the strip has {self.cfg.pixel_count}")
        for index, rgb in enumerate(frame):
            self._strip.setPixelColor(index, self._pack(rgb))
        self._strip.show()

    def off(self) -> None:
        """Blank the strip. Ran on every exit path, including failures."""
        for index in range(self.cfg.pixel_count):
            self._strip.setPixelColor(index, 0)
        self._strip.show()

    # -------------------------------------------------------------- lifecycle
    def request_stop(self, *_args: object) -> None:
        self._stop.set()

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self.request_stop)

    def run(self, *, max_seconds: float | None = None) -> None:
        """Render until SIGTERM/SIGINT, or for max_seconds (used by tests)."""
        self.install_signal_handlers()
        interval = 1.0 / self.cfg.frame_hz
        started = time.monotonic()
        log.info(
            "leds: mode=%s pixels=%d gpio=%d brightness=%d speed=%.1f deg/s",
            self.cfg.mode,
            self.cfg.pixel_count,
            self.cfg.gpio,
            self.cfg.brightness,
            self.cfg.hue_speed_deg_per_s,
        )
        try:
            while not self._stop.is_set():
                elapsed = time.monotonic() - started
                if max_seconds is not None and elapsed >= max_seconds:
                    break
                self.apply(self.frame_for(elapsed))
                # Event.wait rather than time.sleep, so SIGTERM is acted on now.
                self._stop.wait(interval)
        finally:
            log.info("leds: stopping and blanking the strip")
            self.off()


def describe(frame: Iterable[RGB]) -> str:
    """Compact frame rendering, for --dry-run output and test failures."""
    return " ".join("#{:02X}{:02X}{:02X}".format(*rgb) for rgb in frame)


class NullStrip:
    """A strip that records frames instead of driving hardware.

    Used by `--dry-run` and by the unit tests, so the animation can be checked
    on any machine - no Pi, no root, no LEDs.
    """

    def __init__(self, pixel_count: int) -> None:
        self.recorded: list[list[int]] = []
        self._buffer: list[int] = [0] * pixel_count

    def setPixelColor(self, index: int, color: int) -> None:
        self._buffer[index] = color

    def show(self) -> None:
        self.recorded.append(list(self._buffer))
