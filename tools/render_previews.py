#!/usr/bin/env python3
"""Render every panel page to a PNG, so the layout can be reviewed without a Pi.

    python3 tools/render_previews.py --out /tmp/panel-preview
    python3 tools/render_previews.py --demo --scale 6     # fixed sample data

This goes through the real rendering path (`luma.core.render.canvas`) with only
the I2C transport replaced by an in-memory device, so what it writes is what the
panel would draw. It is how the page layout in this repository was iterated on,
and it is the fastest way to review a change to `minitower/pages.py`.

Without --demo it samples the machine it runs on, which is what you want on a
Pi. Off a Pi most fields come back empty (no vcgencmd, no /proc/uptime) and the
pages correctly render "--", so --demo exists to produce a representative image.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from minitower import pages
from minitower.config import PanelConfig
from minitower.panel import Panel
from minitower.sampler import Sample, Sampler


class MemoryDevice:
    """A luma device that keeps the last image instead of sending it over I2C."""

    mode = "1"

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.size = (width, height)
        self.image = None

    def display(self, image) -> None:
        self.image = image

    def clear(self) -> None:
        self.image = None

    def show(self) -> None:
        pass


def demo_sample() -> Sample:
    """A representative sample, so previews look the same on every machine.

    It deliberately includes a throttle flag: an empty one hid the fact that a
    long flag was drawn straight through its row label on the thermal page.
    """
    return Sample(
        hostname="pitower",
        uptime="1d 5h 3m",
        load=(0.52, 0.28, 0.22),
        cpu_percent=12.4,
        memory_percent=43.0,
        memory_used=521 * 1024**2,
        memory_total=7800 * 1024**2,
        disk_percent=11.0,
        disk_used=4_100_000_000,
        disk_total=1_800_000_000_000,
        temperature_c=40.4,
        clock_mhz=1500,
        throttled=["* low voltage"],
        iface="eth0",
        ip="10.73.77.24",
        tx_bytes=1_200_000_000,
        rx_bytes=3_400_000_000,
        tx_rate=310_000.0,
        rx_rate=1_050_000.0,
        top=[("python3", 12.4), ("dockerd", 3.1), ("systemd", 0.9)],
    )


DEMO_HISTORY = [
    10,
    8,
    22,
    45,
    30,
    12,
    6,
    18,
    60,
    88,
    40,
    25,
    12,
    9,
    15,
    33,
    21,
    11,
    8,
    30,
    52,
    14,
    10,
    7,
    19,
    26,
    12,
    9,
    11,
    40,
    65,
    20,
    13,
    10,
    16,
    24,
    12,
    8,
    14,
    31,
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("panel-preview"))
    parser.add_argument("--scale", type=int, default=4, help="integer upscale")
    parser.add_argument("--demo", action="store_true", help="use fixed sample data")
    parser.add_argument("--pages", nargs="*", help="page names (default: all)")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    cfg = PanelConfig()

    if args.demo:
        sample, history = demo_sample(), [float(v) for v in DEMO_HISTORY]
    else:
        sampler = Sampler(want_top=True)
        sample, history = sampler.sample_once(), sampler.cpu_history()

    names = args.pages or sorted(pages.PAGES)
    for name in names:
        device = MemoryDevice(128, 64)
        panel = Panel(cfg, device=device)
        panel.render(pages.PAGES[name], sample=sample, history=history)
        image = device.image.convert("L")
        path = args.out / f"{name}.png"
        image.resize((image.width * args.scale, image.height * args.scale), Image.NEAREST).save(
            path
        )
        print(f"{name:8s} bbox={image.getbbox()}  -> {path}")

    print(f"\n{len(names)} page(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
