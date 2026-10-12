"""Status pages for the 0.96" SSD1306 panel.

This is the part people actually look at, so the layout matters as much as the
data. The design follows the luma.examples system demos, which is what the kit's
own rotation script used to show and what reads as "a proper readout": a frame
around the edge, a title row, then rows sharing one column grid - label on the
left, value right-aligned in its own column, and an outlined bar with a filled
portion showing the proportion.

The previous version of this file drew three or four short lines of plain text at
top-left with no frame at all, which is why it looked unfinished next to the demos
it replaced. Rendered previews of all six pages are attached to the PR.

Pages receive a `Ctx` (canvas, fonts, geometry, the current `Sample` and the CPU
history) instead of reaching for global state, which is why they can be rendered
and asserted in tests with no hardware attached.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import log10
from typing import Callable

from . import system, widgets
from .sampler import Sample, rate_human


@dataclass(frozen=True)
class Ctx:
    """Everything a page needs to draw one frame."""

    draw: object                  # PIL ImageDraw
    font: object                  # row font
    bold: object                  # title font
    width: int
    height: int
    row_h: int                    # vertical step between rows, from font metrics
    font_path: str                # so a page can ask for a larger size of it
    sample: Sample
    history: list[float]


@dataclass(frozen=True)
class Page:
    """A named screen. `border=False` suits full-bleed pages such as the clock."""

    name: str
    draw: Callable[[Ctx], None]
    border: bool = True
    dither: bool = False


# --------------------------------------------------------------------- helpers
def temperature_fraction(celsius: float | None) -> float:
    """Map 20-85 C onto 0-1 - the range a Pi actually lives in."""
    if celsius is None:
        return 0.0
    return (celsius - 20.0) / 65.0


def rate_fraction(rate_bytes: float) -> float:
    """Log scale from 10 kbit/s to 1 Gbit/s, i.e. four usable decades.

    A linear bar would be useless (100 Mbit/s and 900 Mbit/s both look full) and
    a square-root one still saturates early, so: 1 Mbit/s -> 0.4, 100 Mbit/s ->
    0.8, 1 Gbit/s -> full.
    """
    bits = rate_bytes * 8.0
    if bits <= 10_000.0:
        return 0.0
    if bits >= 1e9:
        return 1.0
    return (log10(bits) - 4.0) / 5.0


def _title(ctx: Ctx, left: str, right: str | None = None) -> None:
    widgets.title(ctx.draw, ctx.bold, 3, left, ctx.width, right=right)
    widgets.divider(ctx.draw, 15, ctx.width)


def _rows(ctx: Ctx, start: int, rows) -> None:
    """Draw bar rows with a shared step, stopping before the bottom border."""
    y = start
    while rows and y + ctx.row_h <= ctx.height - 2:
        label, value, fraction = rows.pop(0)
        widgets.bar_row(ctx.draw, ctx.font, y, label, value, ctx.width, fraction)
        y += ctx.row_h


# ----------------------------------------------------------------------- pages
def page_sysinfo(ctx: Ctx) -> None:
    """The hero page: the classic system readout, framed."""
    sample = ctx.sample
    temp = sample.temperature_c
    _title(ctx, sample.hostname[:14], sample.uptime)
    _rows(
        ctx,
        17,
        [
            ("Temp", f"{temp:.1f}C" if temp is not None else "--", temperature_fraction(temp)),
            ("CPU", f"{sample.percent(sample.cpu_percent):.0f}%", sample.percent(sample.cpu_percent) / 100.0),
            ("Mem", f"{sample.percent(sample.memory_percent):.0f}%", sample.percent(sample.memory_percent) / 100.0),
            ("Disk", f"{sample.percent(sample.disk_percent):.0f}%", sample.percent(sample.disk_percent) / 100.0),
        ],
    )


def page_graph(ctx: Ctx) -> None:
    """CPU history. The showpiece - the page people leave on the display."""
    history = ctx.history or [0.0]
    current = ctx.sample.percent(ctx.sample.cpu_percent)
    _title(ctx, "CPU", f"{current:.0f}% now")
    widgets.histogram(ctx.draw, (3, 17, ctx.width - 4, 48), history)
    widgets.text_row(
        ctx.draw,
        ctx.font,
        50,
        f"peak {max(history):.0f}%",
        f"avg {sum(history) / len(history):.0f}%",
        ctx.width,
    )


def page_net(ctx: Ctx) -> None:
    """Live throughput as well as the totals, because a NAS is judged on I/O."""
    sample = ctx.sample
    _title(ctx, f"NET {sample.iface or '-'}"[:14], sample.ip or "-")
    _rows(
        ctx,
        17,
        [
            ("TX", f"{rate_human(sample.tx_rate)}bit/s", rate_fraction(sample.tx_rate)),
            ("RX", f"{rate_human(sample.rx_rate)}bit/s", rate_fraction(sample.rx_rate)),
            ("Sent", system.bytes2human(sample.tx_bytes), None),
            ("Recv", system.bytes2human(sample.rx_bytes), None),
        ],
    )


def page_temp(ctx: Ctx) -> None:
    """Temperature and power health - the page that spots a failing PSU."""
    sample = ctx.sample
    temp = sample.temperature_c
    one = sample.load[0]
    _title(ctx, "THERMAL", f"{sample.clock_mhz}MHz" if sample.clock_mhz else "--")
    _rows(
        ctx,
        17,
        [
            ("CPU", f"{temp:.1f}C" if temp is not None else "--", temperature_fraction(temp)),
            ("Load", f"{one:.2f}", min(1.0, one / 4.0)),
            ("Up", sample.uptime, None),
        ],
    )
    # The sticky throttle bits are the whole point of this page, so they get the
    # full width rather than being squeezed into the value column.
    flag = sample.throttled[0][:18] if sample.throttled else "no throttle"
    widgets.text_row(ctx.draw, ctx.font, 50, "power", flag, ctx.width)


def page_top(ctx: Ctx) -> None:
    """What is actually using the CPU."""
    sample = ctx.sample
    one, five, fifteen = sample.load
    _title(ctx, "PROCESSES", f"{one:.2f}")
    if sample.top:
        y = 17
        for name, cpu in sample.top:
            widgets.text_row(ctx.draw, ctx.font, y, name[:14], f"{cpu:.1f}%", ctx.width)
            y += ctx.row_h
    else:
        widgets.text_row(ctx.draw, ctx.font, 17, "sampling...", "", ctx.width)
    widgets.text_row(ctx.draw, ctx.font, 50, "load", f"{one:.2f} {five:.2f} {fifteen:.2f}", ctx.width)


def page_clock(ctx: Ctx) -> None:
    """Full-bleed: a framed clock reads as a widget, not a clock face."""
    draw = ctx.draw
    now = datetime.now()
    face = now.strftime("%H:%M")
    big = widgets.fit_font(draw, face, ctx.font_path, ctx.width - 12, 30)
    widgets.centre(draw, big, 2, face, ctx.width)
    widgets.centre(draw, ctx.font, 34, now.strftime("%a %d %b %Y"), ctx.width)
    widgets.text_row(
        draw,
        ctx.font,
        50,
        ctx.sample.hostname[:10],
        f"{ctx.sample.percent(ctx.sample.temperature_c):.0f}C",
        ctx.width,
    )


PAGES: dict[str, Page] = {
    "sysinfo": Page("sysinfo", page_sysinfo),
    "graph": Page("graph", page_graph),
    "net": Page("net", page_net),
    "temp": Page("temp", page_temp),
    "top": Page("top", page_top),
    "clock": Page("clock", page_clock, border=False),
}

#: What a fresh install rotates through.
DEFAULT_PAGES = ("sysinfo", "graph", "net", "temp", "top", "clock")


def resolve(names: tuple[str, ...]) -> list[Page]:
    """Map configured page names onto Page objects, rejecting typos loudly."""
    unknown = [name for name in names if name not in PAGES]
    if unknown:
        raise KeyError(
            f"unknown page(s) {', '.join(sorted(unknown))}; "
            f"available: {', '.join(sorted(PAGES))}"
        )
    return [PAGES[name] for name in names]
