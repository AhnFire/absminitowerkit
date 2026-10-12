"""Tests for configuration parsing and validation."""

from pathlib import Path

import pytest

from minitower import config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_defaults_match_the_zp0130():
    cfg = config.load()
    assert cfg.leds.gpio == 18
    assert cfg.panel.i2c_address == 0x3C
    assert cfg.panel.pages


def test_unknown_section_is_rejected(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[leds2]\npixel_count = 6\n", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="unknown sections"):
        config.load(path)


def test_unknown_key_is_rejected_with_a_useful_message(tmp_path):
    path = tmp_path / "typo.toml"
    path.write_text("[leds]\npixelcount = 6\n", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="pixelcount"):
        config.load(path)


def test_missing_explicit_file_is_an_error(tmp_path):
    with pytest.raises(config.ConfigError, match="not found"):
        config.load(tmp_path / "does-not-exist.toml")


def test_pages_list_is_coerced_to_a_tuple(tmp_path):
    path = tmp_path / "good.toml"
    path.write_text('[panel]\npages = ["net", "temp"]\npage_seconds = 5\n', encoding="utf-8")
    cfg = config.load(path)
    assert cfg.panel.pages == ("net", "temp")
    assert cfg.panel.page_seconds == 5.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"brightness": 999},
        {"brightness": -1},
        {"pixel_count": 0},
        {"mode": "party"},
        {"hue_speed_deg_per_s": 999.0},
        {"frame_hz": 0.0},
        {"gamma": 0.0},
    ],
)
def test_invalid_led_values_are_rejected(kwargs):
    with pytest.raises(config.ConfigError):
        config.LedConfig(**kwargs).validated()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"i2c_address": 0x99},
        {"pages": ()},
        {"page_seconds": 0},
        {"refresh_seconds": -1},
    ],
)
def test_invalid_panel_values_are_rejected(kwargs):
    with pytest.raises(config.ConfigError):
        config.PanelConfig(**kwargs).validated()


def test_the_shipped_example_config_is_valid():
    """config.toml.example is what users copy to /etc/minitower/config.toml, so a
    mistake in it would be a mistake in everyone's install."""
    example = REPO_ROOT / "config.toml.example"
    assert example.is_file(), "config.toml.example is missing"
    cfg = config.load(example)
    assert cfg.leds.pixel_count >= 1
    assert cfg.panel.pages
