"""Configuration for the Mini Tower accessory programs.

Defaults live here so there is exactly one place to look. They can be
overridden by a TOML file (default: /etc/minitower/config.toml) and, for a few
of the most useful values, by command-line flags.

Nothing else in this package hardcodes a GPIO number, pixel count, I2C address
or timing - if you need to change how the hardware behaves, this is the file.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("/etc/minitower/config.toml")

#: Card order for a WS2812B strip. The vendor's own `moodlight` binary used
#: WS2811_STRIP_GBR, which swaps red and blue; the Adafruit CircuitPython
#: scripts used the standard GRB. If red and blue come out swapped, change this
#: to "WS2811_STRIP_GBR".
DEFAULT_STRIP_ORDER = "WS2812_STRIP"

LED_MODES = ("gradient", "solid", "off")
PANEL_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


class ConfigError(ValueError):
    """Raised when configuration values are unusable."""


@dataclass(frozen=True)
class LedConfig:
    """Settings for the WS281X fan light / mood light.

    pixel_count   number of addressable LEDs on the chain. The ZP-0130 has one
                  on the OLED driver board plus the fan LEDs.
    gpio          BCM pin driving the data line (18 on the ZP-0130).
    brightness    0-255, applied by the driver itself.
    mode          "gradient" (hue drifts around the ring), "solid" (the whole
                  ring fades through the hue wheel together), or "off".
    hue_spread_deg        hue difference between neighbouring pixels; 360/count
                  gives a full wheel around the ring.
    hue_speed_deg_per_s   how fast the pattern drifts. 6.0 means a full wheel
                  every 60 seconds - deliberately slow, so the change is a
                  gradient rather than a series of jumps.
    frame_hz      refresh rate. At a few degrees per second, 30 Hz makes the
                  change from frame to frame imperceptible.
    gamma         perceptual correction so fades look linear to the eye.
    strip_order   rpi_ws281x constant name, see DEFAULT_STRIP_ORDER.
    """

    pixel_count: int = 6
    gpio: int = 18
    brightness: int = 128
    mode: str = "gradient"
    hue_spread_deg: float = 60.0
    hue_speed_deg_per_s: float = 6.0
    frame_hz: float = 30.0
    gamma: float = 2.2
    strip_order: str = DEFAULT_STRIP_ORDER

    def validated(self) -> "LedConfig":
        if not 1 <= self.pixel_count <= 4096:
            raise ConfigError(f"pixel_count must be 1..4096, got {self.pixel_count}")
        if not 0 <= self.brightness <= 255:
            raise ConfigError(f"brightness must be 0..255, got {self.brightness}")
        if self.mode not in LED_MODES:
            raise ConfigError(f"mode must be one of {LED_MODES}, got {self.mode!r}")
        if not 0.0 <= self.hue_speed_deg_per_s <= 360.0:
            raise ConfigError("hue_speed_deg_per_s must be 0..360")
        if not 0.1 <= self.frame_hz <= 240:
            raise ConfigError("frame_hz must be 0.1..240")
        if self.gamma <= 0:
            raise ConfigError("gamma must be > 0")
        return self


@dataclass(frozen=True)
class PanelConfig:
    """Settings for the SSD1306 OLED status display.

    i2c_port / i2c_address  the panel is on i2c-1 at 0x3C on the ZP-0130.
    font_size / font_path   falls back to Pillow's default font when absent,
                            which is what left the display blank on Pi OS Lite.
    refresh_seconds         how often the current page is redrawn.
    page_seconds            how long each page is shown before rotating.
    pages                   which pages to rotate through, in order.
    """

    i2c_port: int = 1
    i2c_address: int = 0x3C
    font_size: int = 11
    font_path: str = PANEL_FONT_PATH
    refresh_seconds: float = 2.0
    page_seconds: float = 12.0
    pages: tuple[str, ...] = ("load", "mem", "disk", "net", "temp")

    def validated(self) -> "PanelConfig":
        if not 0 <= self.i2c_port <= 99:
            raise ConfigError(f"i2c_port out of range: {self.i2c_port}")
        if not 0x03 <= self.i2c_address <= 0x77:
            raise ConfigError(
                f"i2c_address must be a 7-bit address, got 0x{self.i2c_address:02X}"
            )
        if self.refresh_seconds <= 0:
            raise ConfigError("refresh_seconds must be > 0")
        if self.page_seconds <= 0:
            raise ConfigError("page_seconds must be > 0")
        if not self.pages:
            raise ConfigError("pages must not be empty")
        return self


@dataclass(frozen=True)
class Config:
    leds: LedConfig = LedConfig()
    panel: PanelConfig = PanelConfig()

    def validated(self) -> "Config":
        return Config(leds=self.leds.validated(), panel=self.panel.validated())


def _section(obj: Any, values: dict[str, Any], name: str) -> Any:
    unknown = set(values) - set(obj.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"unknown keys in [{name}]: {', '.join(sorted(unknown))}")
    return replace(obj, **values)


def load(path: os.PathLike[str] | str | None = None) -> Config:
    """Load configuration, falling back to defaults when the file is absent.

    A path you pass explicitly must exist; the default path need not, so the
    programs work out of the box before anyone has written a config file.
    """
    candidate = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not candidate.is_file():
        if path is not None:
            raise ConfigError(f"config file not found: {candidate}")
        return Config().validated()

    with candidate.open("rb") as handle:
        raw = tomllib.load(handle)

    unknown = set(raw) - {"leds", "panel"}
    if unknown:
        raise ConfigError(f"unknown sections: {', '.join(sorted(unknown))}")

    panel_values = dict(raw.get("panel", {}))
    # TOML has no tuple type, but the dataclass wants one.
    if "pages" in panel_values:
        panel_values["pages"] = tuple(panel_values["pages"])

    return Config(
        leds=_section(LedConfig(), raw.get("leds", {}), "leds"),
        panel=_section(PanelConfig(), panel_values, "panel"),
    ).validated()
