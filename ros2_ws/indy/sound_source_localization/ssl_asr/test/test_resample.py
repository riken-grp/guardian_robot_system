"""Tests for the 16 kHz resampling helper of the ASR node."""

import numpy as np
import pytest

pytest.importorskip('rclpy')
pytest.importorskip('common_msgs.msg')
pytest.importorskip('ssl_msgs.msg')

from ssl_asr.asr_node import to_whisper_rate  # noqa: E402


def test_passthrough_16k():
    a = np.ones(100, dtype=np.float32)
    assert to_whisper_rate(a, 16000) is a


@pytest.mark.parametrize('fs', [48000, 44100, 8000])
def test_resample_preserves_tone(fs):
    t = np.arange(fs) / fs
    a = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    out = to_whisper_rate(a, fs)
    assert out.dtype == np.float32
    assert abs(len(out) - 16000) <= 1
    spec = np.abs(np.fft.rfft(out))
    assert abs(np.argmax(spec) * 16000 / len(out) - 440) < 2


def test_invalid_rate():
    assert to_whisper_rate(np.zeros(10, dtype=np.float32), 0) is None
