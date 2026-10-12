"""Mini Tower NAS V2 (ZP-0130) accessory drivers.

Two independent programs share one read-only configuration file:

    minitower-leds     drives the WS281X RGB fan light / mood light
    minitower-panel    drives the 0.96" SSD1306 OLED status display

Design goals, in order:

1. Run forever under systemd without leaking processes or leaving the
   hardware latched on a stale frame.
2. Be testable without the hardware attached (pure frame functions plus an
   injectable strip, and a fake I2C transport for the panel).
3. Keep every hardware parameter in one configuration file - no magic
   GPIO numbers or pixel counts buried in animation code.
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
