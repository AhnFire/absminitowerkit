"""Tests for the sampling layer.

This module holds the logic that is least obvious and was, until now, untested:
rates come from the difference between two samples, interface counters reset,
the history is bounded, and the lookups that spawn a process are cached.

All of it is reachable by replacing the `time` module inside the sampler and the
two psutil calls it uses, so these still need no hardware.
"""

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
