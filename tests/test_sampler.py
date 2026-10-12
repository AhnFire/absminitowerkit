"""Tests for the sampling layer.

This module holds the logic that is least obvious and was, until now, untested:
rates come from the difference between two samples, interface counters reset,
the history is bounded, and the lookups that spawn a process are cached.

All of it is reachable by replacing the `time` module inside the sampler and the
two psutil calls it uses, so these still need no hardware.
"""

import sys
from types import SimpleNamespace

import pytest

from minitower import sampler as sampler_module
from minitower.sampler import Sample, Sampler


class FakeClock:
    """Stands in for the time module inside the sampler."""

    now = 1000.0

    @classmethod
    def monotonic(cls) -> float:
        return cls.now


def advance(seconds: float) -> None:
    FakeClock.now += seconds


@pytest.fixture
def sampled(monkeypatch):
    """A Sampler with a controllable clock, interface and counters."""
    counters = {"eth0": SimpleNamespace(bytes_sent=1_000, bytes_recv=2_000)}
    import psutil

    monkeypatch.setattr(sampler_module, "time", FakeClock)
    monkeypatch.setattr(sampler_module.system, "default_iface", lambda: "eth0")
    monkeypatch.setattr(psutil, "net_io_counters", lambda pernic=False: counters)
    FakeClock.now = 1000.0
    return Sampler(want_top=False), counters


def test_network_rates_come_from_the_delta_between_samples(sampled):
    sampler, counters = sampled
    sampler.sample_once()

    counters["eth0"] = SimpleNamespace(bytes_sent=3_000, bytes_recv=6_000)
    advance(2.0)
    sample = sampler.sample_once()

    assert sample.tx_rate == pytest.approx(1_000.0)  # 2000 bytes over 2 s
    assert sample.rx_rate == pytest.approx(2_000.0)


def test_the_first_sample_reports_no_rate(sampled):
    """There is nothing to diff against yet, and a wild first number on screen
    would be worse than no number."""
    sampler, _ = sampled
    sample = sampler.sample_once()
    assert sample.tx_rate == 0.0
    assert sample.rx_rate == 0.0


def test_a_counter_that_goes_backwards_is_not_a_negative_rate(sampled):
    """Interface counters reset on a link bounce, and on reboot."""
    sampler, counters = sampled
    sampler.sample_once()

    counters["eth0"] = SimpleNamespace(bytes_sent=10, bytes_recv=20)
    advance(1.0)
    sample = sampler.sample_once()

    assert sample.tx_rate == 0.0
    assert sample.rx_rate == 0.0


def test_history_is_bounded_and_keeps_the_newest(monkeypatch):
    monkeypatch.setattr(sampler_module, "time", FakeClock)
    monkeypatch.setattr(sampler_module.system, "default_iface", lambda: None)
    sampler = Sampler(history=3, want_top=False)

    for index in range(10):
        advance(1.0)
        sampler.sample_once()
        sampler.history[-1].uptime = f"#{index}"

    assert len(sampler.history) == 3
    assert sampler.history[-1].uptime == "#9"


def test_slow_lookups_are_cached_for_their_ttl(monkeypatch):
    """A 2-second redraw must not fork vcgencmd on every tick."""
    calls = []

    def clock():
        calls.append(1)
        return 1500

    monkeypatch.setattr(sampler_module, "time", FakeClock)
    monkeypatch.setattr(sampler_module.system, "default_iface", lambda: None)
    monkeypatch.setattr(sampler_module.system, "arm_clock_mhz", clock)
    sampler = Sampler(want_top=False)

    sampler.sample_once()
    advance(2.0)
    sampler.sample_once()
    assert len(calls) == 1, "the cached value should have been reused"

    advance(sampler_module.CLOCK_TTL + 1.0)
    sampler.sample_once()
    assert len(calls) == 2, "the cache should expire"


def test_peak_and_average_come_from_the_history(sampled):
    sampler, _ = sampled
    sampler.history.extend(
        [Sample(cpu_percent=10.0), Sample(cpu_percent=50.0), Sample(cpu_percent=30.0)]
    )

    assert sampler.peak_cpu() == 50.0
    assert sampler.average_cpu() == pytest.approx(30.0)


def test_cpu_history_treats_a_missing_reading_as_zero(sampled):
    sampler, _ = sampled
    sampler.history.append(Sample(cpu_percent=None))
    assert sampler.cpu_history() == [0.0]


def test_top_processes_are_ranked_and_limited(monkeypatch):
    class Proc:
        def __init__(self, name, cpu):
            self.info = {"name": name, "cpu_percent": cpu}

    import psutil

    # Construct the Sampler first: priming deliberately zeroes every process's
    # cpu_percent so the first real reading is meaningful rather than a one-off.
    sampler = Sampler(want_top=True)
    procs = [Proc("python3", 12.4), Proc("dockerd", 3.1), Proc("systemd", 0.9), Proc("idle", 0.0)]
    monkeypatch.setattr(psutil, "process_iter", lambda fields=None: procs)

    assert sampler._top_processes() == [("python3", 12.4), ("dockerd", 3.1), ("systemd", 0.9)]


def test_a_process_that_dies_mid_scan_is_skipped(monkeypatch):
    """psutil raises NoSuchProcess while *reading* a PID that has already exited,
    which happens routinely on a busy box, so the scan must skip it."""

    class Proc:
        def __init__(self, name, cpu):
            self.info = {"name": name, "cpu_percent": cpu}

    class Vanished:
        @property
        def info(self):
            import psutil

            raise psutil.NoSuchProcess(1234)

    import psutil

    sampler = Sampler(want_top=True)
    monkeypatch.setattr(psutil, "process_iter", lambda fields=None: [Proc("top", 5.0), Vanished()])

    assert sampler._top_processes() == [("top", 5.0)]


def test_top_processes_are_skipped_when_no_page_shows_them(monkeypatch):
    """The per-process scan is the most expensive sample, so it is opt-in."""
    calls = []

    import psutil

    monkeypatch.setattr(sampler_module, "time", FakeClock)
    monkeypatch.setattr(sampler_module.system, "default_iface", lambda: None)
    monkeypatch.setattr(psutil, "process_iter", lambda fields=None: calls.append(1) or [])
    sampler = Sampler(want_top=False)

    baseline = len(calls)  # priming may have used it once
    sampler.sample_once()

    assert len(calls) == baseline


def test_a_missing_psutil_does_not_stop_a_sample(monkeypatch):
    """Off a Pi, or in a minimal environment, a page must still render."""
    monkeypatch.setattr(sampler_module, "time", FakeClock)
    monkeypatch.setattr(sampler_module.system, "default_iface", lambda: None)
    monkeypatch.setitem(sys.modules, "psutil", None)

    sampler = Sampler(want_top=False)
    sample = sampler.sample_once()

    assert sample.hostname
    assert sample.cpu_percent is None
