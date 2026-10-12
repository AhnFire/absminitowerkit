"""Status pages for the 0.96" SSD1306 panel.

Each page is a small function that draws into an already-open canvas. Pages are
looked up by name, so the rotation is just a list of names and a timer driven by
the config file - which is what replaces the vendor's spawn-`&`-sleep-kill shell
loop (and the orphaned processes it used to leave behind).

Lines are kept to about 18 characters: that is all that fits across 128 px in
DejaVuSansMono 11.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import system

WHITE = "white"
LINE_HEIGHT = 12


@dataclass(frozen=True)
class Page:
    """A named screen: what to call it, and how to draw it."""

    name: str
    draw: Callable[..., None]


def _line(draw, font, row: int, text: str) -> None:
    draw.text((0, 1 + row * LINE_HEIGHT), text, font=font, fill=WHITE)


def draw_load(draw, font, width: int, height: int) -> None:
    one, five, fifteen = system.load_average()
    _line(draw, font, 0, f"load {one:.2f}")
    _line(draw, font, 1, f"5m   {five:.2f}")
    _line(draw, font, 2, f"15m  {fifteen:.2f}")
    _line(draw, font, 3, f"up {system.uptime_human()}")


def draw_mem(draw, font, width: int, height: int) -> None:
    used, total = system.memory()
    percent = (used / total * 100.0) if total else 0.0
    _line(draw, font, 0, "memory")
    _line(draw, font, 1, f"{system.bytes2human(used)}/{system.bytes2human(total)}")
    _line(draw, font, 2, f"used {percent:.0f}%")


def draw_disk(draw, font, width: int, height: int) -> None:
    used, total = system.disk("/")
    percent = (used / total * 100.0) if total else 0.0
    _line(draw, font, 0, "disk /")
    _line(draw, font, 1, f"{system.bytes2human(used)}/{system.bytes2human(total)}")
    _line(draw, font, 2, f"used {percent:.0f}%")


def draw_net(draw, font, width: int, height: int) -> None:
    iface = system.default_iface()
    _line(draw, font, 0, f"net {iface or '-'}")
    counters = system.net_counters(iface)
    if counters is None:
        _line(draw, font, 1, "counters n/a")
    else:
        sent, received = counters
        _line(draw, font, 1, f"Tx {system.bytes2human(sent)}")
        _line(draw, font, 2, f"Rx {system.bytes2human(received)}")
    _line(draw, font, 3, f"IP {system.primary_ipv4() or '-'}")


def draw_temp(draw, font, width: int, height: int) -> None:
    temperature = system.cpu_temperature_c()
    clock = system.arm_clock_mhz()
    _line(draw, font, 0, "cpu")
    _line(draw, font, 1, f"{temperature:.1f}C" if temperature is not None else "temp n/a")
    _line(draw, font, 2, f"{clock}MHz" if clock else "clk n/a")
    # The sticky throttle bits are worth surfacing: they survive reboots and are
    # how you find out the power supply is marginal.
    reasons = system.throttled_reasons(system.throttled())
    _line(draw, font, 3, reasons[0][:18] if reasons else "no throttle")


PAGES: dict[str, Page] = {
    "load": Page("load", draw_load),
    "mem": Page("mem", draw_mem),
    "disk": Page("disk", draw_disk),
    "net": Page("net", draw_net),
    "temp": Page("temp", draw_temp),
}


def resolve(names: tuple[str, ...]) -> list[Page]:
    """Map configured page names onto Page objects, rejecting typos loudly."""
    unknown = [name for name in names if name not in PAGES]
    if unknown:
        raise KeyError(
            f"unknown page(s) {', '.join(sorted(unknown))}; "
            f"available: {', '.join(sorted(PAGES))}"
        )
    return [PAGES[name] for name in names]
