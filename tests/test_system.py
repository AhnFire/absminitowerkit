"""Tests for the system facts.

On a Pi most of this runs for real; these tests cover the parsing and the failure
branches, which is where the bugs actually live - the throttle bit decode, and the
promise that nothing here raises, because a monitoring display must not be able to
take a service down.
"""

import pytest

from minitower import system


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        ("", []),
        ("0x0", []),
        ("not-hex", []),
        ("0x1", ["low voltage"]),
        ("0x8", ["temp limit"]),
        ("0x40000", ["* throttled"]),
        ("0x50000", ["* low voltage", "* throttled"]),
        ("0xf0000", ["* low voltage", "* cpu capped", "* throttled", "* temp limit"]),
    ],
)
def test_throttle_bits_are_decoded(value, expected):
    """A bit-mask decode with an off-by-one is exactly the kind of thing that
    only shows up on a machine that is already struggling."""
    assert system.throttled_reasons(value) == expected


def test_the_most_severe_reason_comes_first():
    """The thermal page shows reasons[0], so the declaration order matters."""
    reasons = system.throttled_reasons("0xf0003")
    assert reasons[0] == "low voltage"
    assert reasons[-1] == "* temp limit"


def test_bytes2human_scales_in_binary_steps():
    assert system.bytes2human(0) == "0K"
    assert system.bytes2human(1536) == "1K"
    assert system.bytes2human(1024**2 * 3) == "3M"
    assert system.bytes2human(1_800_000_000_000) == "1T"


def test_uptime_human_picks_the_useful_unit():
    assert system.uptime_human(0) == "0m"
    assert system.uptime_human(90) == "1m"
    assert system.uptime_human(3600 * 5 + 60) == "5h 1m"
    assert system.uptime_human(86400 * 2 + 3600 * 5) == "2d 5h"


def test_a_missing_command_is_not_an_error(monkeypatch):
    """Off a Pi there is no vcgencmd; that must read as 'no data', not crash."""

    class Missing:
        @staticmethod
        def run(*_args, **_kwargs):
            raise FileNotFoundError("no vcgencmd here")

    monkeypatch.setattr(system, "subprocess", Missing)
    assert system._run(["vcgencmd", "get_throttled"]) is None


def test_a_failing_command_is_not_an_error(monkeypatch):
    class Failing:
        returncode = 1
        stdout = ""

        @staticmethod
        def run(*_args, **_kwargs):
            return Failing()

    monkeypatch.setattr(system, "subprocess", Failing)
    assert system._run(["false"]) is None


def test_arm_clock_is_parsed_out_of_vcgencmd(monkeypatch):
    monkeypatch.setattr(system, "_run", lambda args, timeout=3.0: "frequency(48)=1500000000")
    assert system.arm_clock_mhz() == 1500


def test_arm_clock_is_none_when_vcgencmd_is_unhelpful(monkeypatch):
    monkeypatch.setattr(system, "_run", lambda args, timeout=3.0: "frequency(48)=huh")
    assert system.arm_clock_mhz() is None


def test_throttled_returns_the_raw_value(monkeypatch):
    monkeypatch.setattr(system, "_run", lambda args, timeout=3.0: "throttled=0x50005")
    assert system.throttled() == "0x50005"


def test_cpu_temperature_reads_the_thermal_zone(monkeypatch, tmp_path):
    zone = tmp_path / "temp"
    zone.write_text("40400\n", encoding="utf-8")
    monkeypatch.setattr(system, "_THERMAL_ZONE", zone)
    assert system.cpu_temperature_c() == pytest.approx(40.4)


def test_cpu_temperature_is_none_when_the_zone_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "_THERMAL_ZONE", tmp_path / "absent")
    assert system.cpu_temperature_c() is None


def test_cpu_temperature_is_none_when_the_zone_is_not_a_number(monkeypatch, tmp_path):
    zone = tmp_path / "temp"
    zone.write_text("banana", encoding="utf-8")
    monkeypatch.setattr(system, "_THERMAL_ZONE", zone)
    assert system.cpu_temperature_c() is None


def test_uptime_seconds_reads_proc_uptime(monkeypatch, tmp_path):
    uptime = tmp_path / "uptime"
    uptime.write_text("12345.67 98765.43\n", encoding="utf-8")
    monkeypatch.setattr(system, "_PROC_UPTIME", uptime)
    assert system.uptime_seconds() == pytest.approx(12345.67)


def test_uptime_seconds_is_zero_without_proc(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "_PROC_UPTIME", tmp_path / "absent")
    assert system.uptime_seconds() == 0.0


def test_primary_ipv4_survives_a_socket_error(monkeypatch):
    class NoRoute:
        def __init__(self, *_args, **_kwargs):
            raise OSError("network is unreachable")

    monkeypatch.setattr(system.socket, "socket", NoRoute)
    assert system.primary_ipv4() is None


def test_load_average_returns_zeros_where_the_platform_has_none(monkeypatch):
    """This is the path that runs on the test machine itself."""
    monkeypatch.delattr(system.os, "getloadavg", raising=False)
    assert system.load_average() == (0.0, 0.0, 0.0)


def test_default_iface_is_none_when_routing_cannot_be_read(monkeypatch):
    monkeypatch.setattr(system, "_run", lambda args, timeout=3.0: None)

    class NoPsutil:
        pass

    monkeypatch.setitem(__import__("sys").modules, "psutil", NoPsutil())
    assert system.default_iface() is None
