"""Unit tests for the delay-and-sum / MVDR beamformer (synthetic signals)."""

import math

import numpy as np
from scipy.fft import rfft

from audio_source_separator.beamformer import MVDRBeamformer

FS = 16000
C = 343.0


def _mic_positions():
    # 8-mic circular array, radius 10 cm, plus a centre mic (non-zero centroid
    # offset to check that the centroid is used as phase reference)
    ang = np.arange(8) * 2 * np.pi / 8
    pos = np.stack([0.1 * np.cos(ang), 0.1 * np.sin(ang), np.zeros(8)], axis=1)
    return pos + np.array([0.3, -0.2, 0.5])


def _plane_wave(pos, src, az, extra=256):
    """x_m(t) = s(t - tau_m), tau_m = -(p_m - centroid).d / c."""
    rel = pos - pos.mean(axis=0)
    d = np.array([math.cos(az), math.sin(az), 0.0])
    tau = -(rel @ d) / C
    n = len(src)
    nfft = 1
    while nfft < n + 2 * extra:
        nfft <<= 1
    S = np.fft.rfft(src, nfft)
    f = np.fft.rfftfreq(nfft, 1 / FS)
    X = S[:, None] * np.exp(-2j * np.pi * f[:, None] * tau[None, :])
    return np.fft.irfft(X, nfft, axis=0)[:n]  # (n, M)


def _bandlimited_noise(rng, n, lo=300, hi=3500):
    s = rng.standard_normal(n + 512)
    S = np.fft.rfft(s)
    f = np.fft.rfftfreq(len(s), 1 / FS)
    S[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(S, len(s))[256:256 + n]


def test_steering_vector_sign_matches_plane_wave():
    pos = _mic_positions()
    bf = MVDRBeamformer(pos, FS, fft_size=512)
    az = math.radians(60)
    # Pure tone at an FFT bin: X_m / X_ref must equal a_m
    k = 40
    t = np.arange(512) / FS
    src = np.cos(2 * np.pi * bf.freqs[k] * t)
    x = _plane_wave(pos, np.tile(src, 8), az)[1024:1536]
    X = rfft(x, axis=0)[k]
    a = bf.compute_steering_vector(az)[k]
    ratio = X / a
    assert np.allclose(ratio, ratio[0], rtol=1e-2, atol=1e-6 * np.abs(ratio[0]))


def test_das_aligns_target_and_attenuates_other_direction():
    rng = np.random.default_rng(0)
    pos = _mic_positions()
    bf = MVDRBeamformer(pos, FS)
    src = _bandlimited_noise(rng, 8192, 2000, 3500)
    x = _plane_wave(pos, src, math.radians(90))
    y = bf.apply_das_multi(x, [math.radians(90), math.radians(270)])
    lat = bf.das_latency_samples
    # Target beam reproduces the source delayed by the constant latency
    ref = _plane_wave(np.zeros((1, 3)), src, 0.0)[:, 0]  # no delay
    n = np.arange(len(src))
    S = np.fft.rfft(ref)
    f = np.fft.rfftfreq(len(ref))
    ref_delayed = np.fft.irfft(S * np.exp(-2j * np.pi * f * lat), len(ref))
    sl = slice(512, -512)
    err = np.sqrt(np.mean((y[0, sl] - ref_delayed[sl]) ** 2)) / np.std(src)
    assert err < 0.05, err
    # Opposite beam is clearly weaker at 2-3.5 kHz
    p_target = np.mean(y[0, sl] ** 2)
    p_other = np.mean(y[1, sl] ** 2)
    assert 10 * math.log10(p_target / p_other) > 3.0
    del n


def test_das_streaming_is_seamless():
    """Block-wise processing must equal one-shot processing (no edge clicks)."""
    rng = np.random.default_rng(1)
    pos = _mic_positions()
    src = _bandlimited_noise(rng, 512 * 12)
    x = _plane_wave(pos, src, math.radians(30))
    az = [math.radians(30), math.radians(150)]

    bf_one = MVDRBeamformer(pos, FS)
    y_one = bf_one.apply_das_multi(x, az)

    bf_blk = MVDRBeamformer(pos, FS)
    blocks = [bf_blk.apply_das_multi(x[i:i + 512], az)
              for i in range(0, len(x), 512)]
    y_blk = np.concatenate(blocks, axis=1)
    sl = slice(512, None)
    err = np.max(np.abs(y_one[:, sl] - y_blk[:, sl])) / np.std(src)
    assert err < 0.02, err


def test_das_different_directions_give_different_signals():
    rng = np.random.default_rng(2)
    pos = _mic_positions()
    bf = MVDRBeamformer(pos, FS)
    x = (_plane_wave(pos, _bandlimited_noise(rng, 4096), math.radians(0))
         + _plane_wave(pos, _bandlimited_noise(rng, 4096), math.radians(180)))
    y = bf.apply_das_multi(x, [0.0, math.pi])
    assert not np.allclose(y[0], y[1])


def test_push_context_and_empty_directions():
    pos = _mic_positions()
    bf = MVDRBeamformer(pos, FS)
    out = bf.apply_das_multi(np.zeros((512, 8)), [])
    assert out.shape == (0, 512)
    bf.push_context(np.ones((4, 8)))
    assert bf._das_tail.shape == (bf._das_ctx, 8)
