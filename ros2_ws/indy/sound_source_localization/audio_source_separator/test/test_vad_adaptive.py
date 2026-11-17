"""Unit tests for the adaptive (noise-floor-relative) VAD and output normalization."""

import math

import numpy as np

from audio_source_separator.vad import EnergyVAD
from audio_source_separator.separator_node import normalize_segment

BLK = 512


def _blk(level_db, rng):
    return (10 ** (level_db / 20) * rng.standard_normal(BLK)).astype(np.float32)


def _run(vad, levels, seed=0):
    rng = np.random.default_rng(seed)
    return [vad.process_frame(_blk(lv, rng)) for lv in levels]


def test_fixed_threshold_unchanged():
    vad = EnergyVAD(threshold_db=-54.0, hangover_frames=2, min_speech_frames=3)
    out = _run(vad, [-60] * 20 + [-57] * 10)
    assert not any(out)                 # -57 dB speech stays below -54 dB


def test_adaptive_detects_quiet_speech_and_ignores_noise():
    vad = EnergyVAD(threshold_db=-70.0, hangover_frames=2, min_speech_frames=3,
                    adaptive=True, margin_db=6.0, noise_init_db=-60.0)
    noise = _run(vad, [-66] * 100)      # learns a -66 dB floor
    assert not any(noise)
    assert abs(vad.noise_floor_db + 66.0) < 1.5
    speech = _run(vad, [-57] * 10, seed=1)   # 9 dB above the floor
    assert speech[-1]


def test_adaptive_floor_follows_rising_noise():
    vad = EnergyVAD(threshold_db=-70.0, hangover_frames=2, min_speech_frames=3,
                    adaptive=True, margin_db=6.0, noise_init_db=-70.0,
                    noise_rise_db=0.05)
    out = _run(vad, [-60] * 600)        # stationary noise much louder than init
    assert not any(out[-50:])           # floor has caught up, no false speech
    assert vad.noise_floor_db > -62.0


def test_adaptive_absolute_minimum():
    vad = EnergyVAD(threshold_db=-50.0, adaptive=True, margin_db=6.0,
                    noise_init_db=-80.0)
    assert vad.current_threshold_db == -50.0


def test_normalize_segment_gain_and_limits():
    rng = np.random.default_rng(0)
    a = (10 ** (-50 / 20) * rng.standard_normal(16000)).astype(np.float32)
    y, g = normalize_segment(a, target_db=-20.0, max_gain_db=40.0, peak_db=-1.0)
    assert 25.0 < g <= 40.0
    assert np.max(np.abs(y)) <= 10 ** (-1 / 20) + 1e-6
    # gain cap
    b = (1e-5 * rng.standard_normal(16000)).astype(np.float32)
    _, g2 = normalize_segment(b, target_db=-20.0, max_gain_db=40.0, peak_db=-1.0)
    assert math.isclose(g2, 40.0, abs_tol=1e-6)
    # empty
    e, g3 = normalize_segment(np.zeros(0, np.float32), -20.0, 40.0, -1.0)
    assert e.size == 0 and g3 == 0.0
