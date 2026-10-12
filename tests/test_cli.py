"""Tests for the command line, which had no coverage at all before this file.

Everything here is hardware-free: --dry-run, --version, argument overrides and the
error paths. Opening a real display is the one thing deliberately not covered,
because that needs a Pi - test_pages.py exercises the drawing with a fake device
instead.
"""

import pytest

from minitower import __main__ as cli
from minitower.config import ConfigError


def test_version_exits_zero():
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0


def test_help_lists_both_programs(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "drive the WS281X fan light / mood light" in out
    assert "drive the SSD1306 OLED status display" in out


def test_a_missing_subcommand_is_a_usage_error():
    """argparse exits 2 for a usage error, which is what a cron wrapper expects."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2


def test_an_unknown_page_is_a_usage_error():
    with pytest.raises(SystemExit):
        cli.main(["panel", "--page", "nope"])


def test_led_dry_run_prints_frames_without_hardware(capsys):
    assert cli.main_leds(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "mode=gradient" in out
    assert out.count("t=") == 4
    assert "#FF0000" in out


def test_led_dry_run_never_opens_the_strip(monkeypatch):
    """--dry-run exists to be safely runnable anywhere, so it must not need root,
    a strip, or even rpi_ws281x."""
    from minitower import leds

    def explode(*_args, **_kwargs):
        raise AssertionError("--dry-run touched the hardware")

    monkeypatch.setattr(leds, "_open_strip", explode)
    assert cli.main_leds(["--dry-run"]) == 0


def test_led_dry_run_honours_overrides(capsys):
    assert cli.main_leds(["--dry-run", "--pixels", "4", "--mode", "solid"]) == 0
    out = capsys.readouterr().out
    assert "pixels=4" in out
    assert "mode=solid" in out


def test_led_overrides_produce_a_validated_config():
    args = cli.build_parser().parse_args(
        ["leds", "--pixels", "12", "--brightness", "200", "--gpio", "21", "--speed", "2.5"]
    )

    cfg = cli._led_config(args)

    assert (cfg.pixel_count, cfg.brightness, cfg.gpio) == (12, 200, 21)
    assert cfg.hue_speed_deg_per_s == 2.5


def test_an_out_of_range_override_is_rejected():
    args = cli.build_parser().parse_args(["leds", "--brightness", "999"])
    with pytest.raises(ConfigError, match="brightness"):
        cli._led_config(args)


def test_a_missing_config_file_is_reported():
    args = cli.build_parser().parse_args(["leds", "--config", "no-such-file.toml"])
    with pytest.raises(ConfigError, match="not found"):
        cli._led_config(args)


def test_the_default_config_is_used_when_none_is_given(tmp_path):
    """No --config at all must fall back to the built-in defaults rather than
    failing on the absent /etc/minitower/config.toml."""
    args = cli.build_parser().parse_args(["leds"])
    cfg = cli._led_config(args)
    assert args.config is None
    assert cfg.gpio == 18


def test_panel_reports_a_display_failure_as_exit_code_one(monkeypatch):
    """systemd (and the installer) care about the exit code, not the traceback."""
    from minitower import panel as panel_module

    class Boom:
        def __init__(self, *_args, **_kwargs):
            raise panel_module.PanelError("cannot open the panel on i2c-1 at 0x3C")

    monkeypatch.setattr(panel_module, "Panel", Boom)

    assert cli.main_panel([]) == 1


def test_panel_page_flag_draws_one_page_and_exits(monkeypatch):
    from minitower import panel as panel_module

    calls = []

    class FakePanel:
        def __init__(self, *_args, **_kwargs):
            pass

        def render_named(self, name):
            calls.append(("page", name))

        def run(self, **_kwargs):
            calls.append(("run", None))

    monkeypatch.setattr(panel_module, "Panel", FakePanel)

    assert cli.main_panel(["--page", "clock"]) == 0
    assert calls == [("page", "clock")]


def test_panel_without_a_page_flag_runs_the_rotation(monkeypatch):
    from minitower import panel as panel_module

    calls = []

    class FakePanel:
        def __init__(self, *_args, **_kwargs):
            pass

        def render_named(self, name):
            calls.append("page")

        def run(self, *, max_seconds=None):
            calls.append(("run", max_seconds))

    monkeypatch.setattr(panel_module, "Panel", FakePanel)

    assert cli.main_panel(["--seconds", "3"]) == 0
    assert calls == [("run", 3.0)]


def test_led_run_delegates_to_the_ring(monkeypatch):
    """The non-dry-run path, without a strip: it must hand the config and the
    time limit to the ring and nothing else."""
    from minitower import leds as leds_module

    calls = []

    class FakeRing:
        def __init__(self, cfg, *_args, **_kwargs):
            calls.append(("init", cfg.pixel_count))

        def run(self, **kwargs):
            calls.append(("run", kwargs.get("max_seconds")))

    monkeypatch.setattr(leds_module, "LedRing", FakeRing)

    assert cli.main_leds(["--pixels", "3", "--seconds", "2"]) == 0
    assert calls == [("init", 3), ("run", 2.0)]


def test_main_dispatches_a_led_command(capsys):
    assert cli.main(["leds", "--dry-run"]) == 0
    assert "mode=gradient" in capsys.readouterr().out


def test_main_dispatches_a_panel_command(monkeypatch):
    from minitower import panel as panel_module

    drawn = []

    class FakePanel:
        def __init__(self, *_args, **_kwargs):
            pass

        def render_named(self, name):
            drawn.append(name)

        def run(self, **_kwargs):
            pass

    monkeypatch.setattr(panel_module, "Panel", FakePanel)

    assert cli.main(["panel", "--page", "sysinfo"]) == 0
    assert drawn == ["sysinfo"]
