"""Unit tests for SRP-PHAT on synthetic plane-wave signals."""

import math
import os

import numpy as np
import pytest

from sound_source_localizer.array_geometry import (
    SPEED_OF_SOUND, compute_time_delays, load_array_geometry,
)
from sound_source_localizer.srp_phat import SrpPhat

_GEOM = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'microphone_array',
    'config', 'array_geometry.yaml')


def _mic_positions():
    if os.path.exists(_GEOM):
        return load_array_geometry(_GEOM)
    # Fallback: 8-mic circular array, radius 5 cm
    ang = np.arange(8) * 2 * np.pi / 8
    return np.stack([0.05 * np.cos(ang), 0.05 * np.sin(ang),
                     np.zeros(8)], axis=1)


def _plane_wave(pos, src, az, el=0.0, fs=16000, extra=64):
    """Delay a mono source to every mic (fractional delay in freq domain)."""
    n = len(src)
    tau = compute_time_delays(pos, az, el)  # arrival delay rel. centroid (s)
    nfft = 1
    while nfft < n + 2 * extra:
        nfft <<= 1
    S = np.fft.rfft(src, nfft)
    f = np.fft.rfftfreq(nfft, 1 / fs)
    X = S[None, :] * np.exp(-2j * np.pi * f[None, :] * tau[:, None])
    return np.fft.irfft(X, nfft, axis=1)[:, :n]


@pytest.mark.parametrize('az_deg', [0.0, 3.0, 47.0, 135.0, 222.0, 357.0])
def test_single_source_direction(az_deg):
    rng = np.random.default_rng(0)
    pos = _mic_positions()
    src = rng.standard_normal(1024)
    x = _plane_wave(pos, src, math.radians(az_deg))
    x += 0.05 * rng.standard_normal(x.shape)
    srp = SrpPhat(pos, sample_rate=16000, num_sources=3, resolution_deg=5.0)
    peaks = srp.locate(x)
    assert peaks, 'source not detected'
    az = math.degrees(peaks[0][0])
    err = abs((az - az_deg + 180.0) % 360.0 - 180.0)
    assert err <= 5.0, (az, az_deg)
    # No duplicate peak within the suppression radius (incl. 0/360 wrap)
    for a, _, _ in peaks[1:]:
        d = abs((math.degrees(a) - az + 180.0) % 360.0 - 180.0)
        assert d > srp.suppression_deg


def test_silence_yields_no_peaks():
    rng = np.random.default_rng(1)
    pos = _mic_positions()
    # Spatially uncorrelated sensor noise
    x = 1e-3 * rng.standard_normal((len(pos), 1024))
    srp = SrpPhat(pos, num_sources=3)
    assert srp.locate(x) == []
    # Pure digital silence
    assert srp.locate(np.zeros((len(pos), 1024))) == []


def test_band_mask_rejects_out_of_band_source():
    """A coherent source only above the band must not be localised."""
    rng = np.random.default_rng(2)
    pos = _mic_positions()
    fs = 16000
    src = rng.standard_normal(1024)
    S = np.fft.rfft(src)
    f = np.fft.rfftfreq(1024, 1 / fs)
    S[f < 5000] = 0  # energy only at 5-8 kHz (outside 300-3500 Hz)
    src = np.fft.irfft(S, 1024)
    x = _plane_wave(pos, src, math.radians(90))
    # Spatially uncorrelated broadband noise dominates the 300-3500 Hz band
    # (also masks the spectral leakage of the truncated plane wave).
    x += 0.3 * np.std(src) * rng.standard_normal(x.shape)
    srp = SrpPhat(pos, sample_rate=fs, num_sources=1)
    pm_band = srp.compute_power_map(x).max()
    srp_full = SrpPhat(pos, sample_rate=fs, num_sources=1,
                       frequency_range=(0.0, fs / 2))
    pm_full = srp_full.compute_power_map(x).max()
    assert pm_band < 0.1 < pm_full


def test_two_sources():
    rng = np.random.default_rng(3)
    pos = _mic_positions()
    n = 2048
    x = (_plane_wave(pos, rng.standard_normal(n), math.radians(30))
         + _plane_wave(pos, rng.standard_normal(n), math.radians(200)))
    srp = SrpPhat(pos, num_sources=2)
    peaks = srp.locate(x)
    found = sorted(round(math.degrees(p[0])) for p in peaks)
    assert len(found) == 2
    assert abs(found[0] - 30) <= 10 and abs(found[1] - 200) <= 10


def test_wrap_suppression_no_duplicate_near_zero():
    pos = _mic_positions()
    srp = SrpPhat(pos, num_sources=3, power_threshold=-10.0)
    pm = np.full((len(srp.azimuths), len(srp.elevations)), 0.01)
    pm[0, :] = 1.0      # 0 deg
    pm[-1, :] = 0.9     # 355 deg: same source across the wrap
    pm[36, :] = 0.5     # 180 deg: genuine second source
    peaks = srp._find_peaks(pm)
    az = [round(math.degrees(p[0])) for p in peaks]
    assert az[0] == 0 and 355 not in az and 180 in az
