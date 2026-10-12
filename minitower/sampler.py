"""Rolling samples for the pages that need history or rates.

This exists rather than the pages calling psutil directly for two reasons:

* `psutil.cpu_percent(interval=1)` **blocks for a second**, which is what makes
  the luma demos stutter on a busy box. Every sample here is non-blocking
  (`interval=None`) and the history is built by the panel's own loop.
* the histogram and the network rates are meaningless without the *previous*
  sample, so something has to own that state.

Values that come from spawning a process (`vcgencmd`, `ip route`) are cached
with a TTL, so a 2-second redraw does not mean three `fork()`+`exec()` per tick.
"""

from __future__ import annotations

import logging
import socket
import time
from collections import deque
from dataclasses import dataclass, field

from . import system

log = logging.getLogger("minitower.sampler")

HISTORY = 40          # graph samples kept: 40 x 2 s = 80 s of history
CLOCK_TTL = 10.0      # vcgencmd is cheap once, but not every 2 s forever
IFACE_TTL = 30.0      # the default route rarely changes


@dataclass
class Sample:
    """One point in time. Every field is optional: nothing is guaranteed."""

    taken_at: float = 0.0
    hostname: str = ""
    uptime: str = ""
    load: tuple[float, float, float] = (0.0, 0.0, 0.0)
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used: int = 0
    memory_total: int = 0
    disk_percent: float | None = None
    disk_used: int = 0
    disk_total: int = 0
    temperature_c: float | None = None
    clock_mhz: int | None = None
    throttled: list[str] = field(default_factory=list)
    iface: str | None = None
    ip: str | None = None
    tx_bytes: int = 0
    rx_bytes: int = 0
    tx_rate: float = 0.0          # bytes per second
    rx_rate: float = 0.0
    top: list[tuple[str, float]] = field(default_factory=list)

    def percent(self, value: float | None) -> float:
        """None means 'no data', which reads better as 0% than as a blank bar."""
        return 0.0 if value is None else value


def _hostname() -> str:
    try:
        return socket.gethostname().split(".")[0] or "pi"
    except OSError:  # pragma: no cover - only if the hostname is broken
        return "pi"


class Sampler:
    """Collects samples, keeps the history, and caches the slow lookups."""

    def __init__(self, *, history: int = HISTORY, want_top: bool = True) -> None:
        self.history: deque[Sample] = deque(maxlen=history)
        self.latest = Sample(hostname=_hostname())
        self.want_top = want_top
        self._cache: dict[str, tuple[float, object]] = {}
        self._prime_psutil()

    def _prime_psutil(self) -> None:
        """Make the first reading real.

        psutil's first `cpu_percent()` always reports 0.0 because it needs a
        previous call to diff against, so the first value shown would otherwise
        be a misleading zero. Priming here also warms the per-process counters.
        """
        try:
            import psutil

            psutil.cpu_percent(interval=None)
            for proc in psutil.process_iter(["name"]):
                proc.info["cpu_percent"] = 0.0
        except Exception:
            pass

    def _cached(self, key: str, ttl: float, produce):
        """Memoise a slow lookup (a process spawn) for `ttl` seconds."""
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]
        value = produce()
        self._cache[key] = (now, value)
        return value

    def _top_processes(self, limit: int = 3) -> list[tuple[str, float]]:
        try:
            import psutil
        except ImportError:  # pragma: no cover - psutil is a declared dependency
            return []
        rows: list[tuple[str, float]] = []
        for proc in psutil.process_iter(["name", "cpu_percent"]):
            try:
                cpu = proc.info.get("cpu_percent") or 0.0
                name = (proc.info.get("name") or "?")[:12]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if cpu > 0.0:
                rows.append((name, cpu))
        rows.sort(key=lambda row: row[1], reverse=True)
        return rows[:limit]

    # ------------------------------------------------------------------ sample
    def sample_once(self) -> Sample:
        """Take a fresh sample, append it to the history, and return it."""
        now = time.monotonic()
        sample = Sample(taken_at=now, hostname=_hostname())

        sample.uptime = system.uptime_human()
        sample.load = system.load_average()
        sample.iface = self._cached("iface", IFACE_TTL, system.default_iface)
        sample.ip = system.primary_ipv4()
        sample.temperature_c = system.cpu_temperature_c()
        sample.clock_mhz = self._cached("clock", CLOCK_TTL, system.arm_clock_mhz)
        sample.throttled = system.throttled_reasons(
            self._cached("throttled", CLOCK_TTL, system.throttled)
        )

        try:
            import psutil

            sample.cpu_percent = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            sample.memory_percent = memory.percent
            sample.memory_used, sample.memory_total = memory.used, memory.total
            usage = psutil.disk_usage("/")
            sample.disk_percent = usage.percent
            sample.disk_used, sample.disk_total = usage.used, usage.total
            if sample.iface:
                counters = psutil.net_io_counters(pernic=True).get(sample.iface)
                if counters is not None:
                    sample.tx_bytes = counters.bytes_sent
                    sample.rx_bytes = counters.bytes_recv
                    elapsed = now - self.latest.taken_at
                    if self.latest.taken_at > 0 and elapsed > 0:
                        sample.tx_rate = max(0.0, (sample.tx_bytes - self.latest.tx_bytes) / elapsed)
                        sample.rx_rate = max(0.0, (sample.rx_bytes - self.latest.rx_bytes) / elapsed)
            if self.want_top:
                sample.top = self._top_processes()
        except Exception as exc:  # pragma: no cover - psutil is optional at runtime
            log.debug("sampling failed: %s", exc)

        self.latest = sample
        self.history.append(sample)
        return sample

    # ------------------------------------------------------------------- views
    def cpu_history(self) -> list[float]:
        return [sample.cpu_percent or 0.0 for sample in self.history]

    def peak_cpu(self) -> float:
        return max(self.cpu_history(), default=0.0)

    def average_cpu(self) -> float:
        values = self.cpu_history()
        return sum(values) / len(values) if values else 0.0


def bits_per_second(rate_bytes: float) -> float:
    """Bytes/s to bits/s - what network figures are actually quoted in."""
    return rate_bytes * 8.0


def rate_human(rate_bytes: float) -> str:
    """Compact bit rate: 2400000 B/s -> '2.4M'."""
    bits = bits_per_second(rate_bytes)
    for unit in ("", "K", "M", "G"):
        if bits < 1000.0:
            return f"{bits:.0f}" if unit == "" else f"{bits:.1f}{unit}"
        bits /= 1000.0
    return f"{bits:.1f}T"
