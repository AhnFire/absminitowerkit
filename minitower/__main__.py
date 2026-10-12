"""Command-line entry points.

Installed as two console scripts by pyproject.toml:

    minitower-leds     drive the WS281X fan light / mood light
    minitower-panel    drive the SSD1306 OLED status display

Both accept --config, so a systemd unit never has to hardcode hardware values.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from . import config as config_module
from . import leds as leds_module
from . import pages as pages_module

LOG_FORMAT = "%(levelname)s: %(message)s"


def _add_common(parser: argparse.ArgumentParser) -> None:
    # default=None, not the default path: an absent file at the *default*
    # location is fine (built-in defaults are used), whereas a path the user
    # typed must exist. Passing the Path object as the default would make every
    # run behave as if the user had asked for /etc/minitower/config.toml.
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="FILE",
        help=f"TOML configuration file (default: {config_module.DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minitower",
        description="Mini Tower NAS V2 (ZP-0130) accessory drivers",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    leds = sub.add_parser("leds", help="drive the WS281X fan light / mood light")
    _add_common(leds)
    leds.add_argument("--mode", choices=config_module.LED_MODES)
    leds.add_argument("--pixels", type=int, help="number of addressable LEDs")
    leds.add_argument("--brightness", type=int, help="0-255")
    leds.add_argument("--gpio", type=int, help="BCM data pin")
    leds.add_argument("--speed", type=float, metavar="DEG_PER_SEC")
    leds.add_argument(
        "--dry-run",
        action="store_true",
        help="print sample frames and exit without touching the hardware",
    )
    leds.add_argument("--seconds", type=float, help="exit after N seconds")

    panel = sub.add_parser("panel", help="drive the SSD1306 OLED status display")
    _add_common(panel)
    panel.add_argument("--page", choices=sorted(pages_module.PAGES), help="draw one page and exit")
    panel.add_argument("--seconds", type=float, help="exit after N seconds")

    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=LOG_FORMAT,
        stream=sys.stderr,
    )


def _led_config(args: argparse.Namespace) -> config_module.LedConfig:
    cfg = config_module.load(args.config).leds
    overrides = {}
    for name, value in (
        ("mode", args.mode),
        ("pixel_count", args.pixels),
        ("brightness", args.brightness),
        ("gpio", args.gpio),
        ("hue_speed_deg_per_s", args.speed),
    ):
        if value is not None:
            overrides[name] = value
    return replace(cfg, **overrides).validated()


def _run_leds(args: argparse.Namespace) -> int:
    cfg = _led_config(args)

    if args.dry_run:
        strip = leds_module.NullStrip(cfg.pixel_count)
        ring = leds_module.LedRing(cfg, strip=strip)
        print(f"# mode={cfg.mode} pixels={cfg.pixel_count} speed={cfg.hue_speed_deg_per_s}/s")
        for elapsed in (0.0, 5.0, 10.0, 15.0):
            print(f"t={elapsed:5.1f}s  {leds_module.describe(ring.frame_for(elapsed))}")
        return 0

    leds_module.LedRing(cfg).run(max_seconds=args.seconds)
    return 0


def _run_panel(args: argparse.Namespace) -> int:
    cfg = config_module.load(args.config).panel

    from .panel import Panel, PanelError

    try:
        panel = Panel(cfg)
    except PanelError as exc:
        logging.getLogger("minitower").error("%s", exc)
        return 1

    if args.page:
        panel.render_named(args.page)
        return 0

    panel.run(max_seconds=args.seconds)
    return 0


def main_leds(argv: list[str] | None = None) -> int:
    """Console script entry point for minitower-leds."""
    args = build_parser().parse_args(["leds", *(argv if argv is not None else sys.argv[1:])])
    _configure_logging(args.verbose)
    return _run_leds(args)


def main_panel(argv: list[str] | None = None) -> int:
    """Console script entry point for minitower-panel."""
    args = build_parser().parse_args(["panel", *(argv if argv is not None else sys.argv[1:])])
    _configure_logging(args.verbose)
    return _run_panel(args)


def main(argv: list[str] | None = None) -> int:
    """`python -m minitower <command>`; dispatches on the subcommand."""
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    _configure_logging(args.verbose)
    if args.command == "leds":
        return _run_leds(args)
    return _run_panel(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
