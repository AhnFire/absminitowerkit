"""Tests for the LED animation.

The animation is a pure function of elapsed time and the hardware is injected,
so every one of these runs on any machine - no Pi, no root, no LEDs. That is the
main reason minitower.leds is shaped the way it is.
"""

import colorsys
import itertools

import pytest

from minitower.config import LedConfig
from minitower.leds import LedRing, NullStrip, build_gamma


def make_ring(**overrides):
    """A ring wired to a recording strip instead of the real hardware."""
    cfg = LedConfig(**overrides)
    strip = NullStrip(cfg.pixel_count)
    return LedRing(cfg, strip=strip), strip


def test_gamma_table_is_monotonic_and_bounded():
    table = build_gamma(2.2)
    assert len(table) == 256
    assert table[0] == 0
    assert table[255] == 255
    assert all(later >= earlier for earlier, later in itertools.pairwise(table))


def test_gradient_spreads_a_full_wheel_around_the_ring():
    ring, _ = make_ring(pixel_count=6, hue_spread_deg=60.0, gamma=1.0)
    frame = ring.gradient_frame(0.0)
    assert len(frame) == 6
    hues = [colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))[0] * 360.0 for rgb in frame]
    assert hues[0] == pytest.approx(0.0, abs=1.0)
    assert hues[-1] == pytest.approx(300.0, abs=1.0)


def test_animation_is_smooth_not_a_disco():
    """Regression test for the reported problem.

    The vendor's `moodlight` binary ran upstream's 8x8 matrix demo at 15 fps, so
    colours jumped abruptly. A single frame here must move only a little.
    """
    ring, _ = make_ring(gamma=1.0, hue_speed_deg_per_s=6.0, frame_hz=30.0)
    before_frame = ring.frame_for(0.0)
    after_frame = ring.frame_for(1.0 / 30.0)
    for before, after in zip(before_frame, after_frame, strict=False):
        delta = max(abs(a - b) for a, b in zip(before, after, strict=False))
        assert delta <= 8, f"one frame moved {delta}/255 - too abrupt to be a gradient"


def test_a_full_colour_cycle_takes_about_a_minute():
    ring, _ = make_ring(gamma=1.0, hue_speed_deg_per_s=6.0)
    assert ring.frame_for(0.0) == ring.frame_for(60.0)
    assert ring.frame_for(0.0) != ring.frame_for(30.0)


def test_solid_mode_keeps_every_pixel_identical():
    ring, _ = make_ring(mode="solid", pixel_count=5, gamma=1.0)
    frames = [ring.frame_for(t) for t in (0.0, 10.0, 20.0)]
    for frame in frames:
        assert len(set(frame)) == 1


def test_apply_writes_exactly_one_frame_per_show():
    ring, strip = make_ring(pixel_count=4)
    ring.apply(ring.frame_for(0.0))
    assert len(strip.recorded) == 1
    assert len(strip.recorded[0]) == 4


def test_apply_rejects_a_frame_with_the_wrong_pixel_count():
    ring, _ = make_ring(pixel_count=4)
    with pytest.raises(ValueError, match="pixels"):
        ring.apply([(1, 2, 3)])


def test_off_blanks_every_pixel():
    ring, strip = make_ring(pixel_count=6)
    ring.apply(ring.gradient_frame(120.0))
    ring.off()
    assert strip.recorded[-1] == [0] * 6


def test_run_blanks_the_strip_on_the_way_out():
    """The vendor's binary left the LEDs latched on its last frame when stopped."""
    ring, strip = make_ring(pixel_count=4)
    ring.run(max_seconds=0.05)
    assert strip.recorded, "the run loop rendered nothing"
    assert strip.recorded[-1] == [0] * 4, "the strip was not blanked on exit"


def test_brightness_is_applied_by_the_driver_not_the_animation():
    """Two brightness levels must produce identical frames, because the driver
    scales them - that is what keeps the loop cheap."""
    dim, _ = make_ring(brightness=40, gamma=1.0)
    bright, _ = make_ring(brightness=255, gamma=1.0)
    assert dim.frame_for(3.0) == bright.frame_for(3.0)
