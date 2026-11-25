import numpy as np
import pytest

from audio_play.audio_utils import AudioQueue, resample_linear, to_pcm16, validate_audio


def test_to_pcm16_converts_and_clips():
    pcm = np.frombuffer(to_pcm16([0.0, 0.5, -0.5, 1.0, -1.0, 2.0, -3.0]), dtype="<i2")
    assert pcm.tolist() == [0, 16384, -16384, 32767, -32767, 32767, -32767]


def test_to_pcm16_length():
    assert len(to_pcm16(np.zeros(16000, dtype=np.float32))) == 32000


def test_validate_ok():
    samples, error = validate_audio([0.1] * 160, 16000, 30.0)
    assert error is None
    assert samples.dtype == np.float32 and samples.size == 160


@pytest.mark.parametrize(
    "audio, rate",
    [
        ([], 16000),
        ([0.1], 0),
        ([0.1], -16000),
        ([0.1, float("nan")], 16000),
        ([0.1, float("inf")], 16000),
    ],
)
def test_validate_rejects_invalid(audio, rate):
    samples, error = validate_audio(audio, rate, 30.0)
    assert samples is None and error


def test_validate_rejects_too_long():
    samples, error = validate_audio(np.zeros(16000 * 31, dtype=np.float32), 16000, 30.0)
    assert samples is None and "too long" in error
    samples, error = validate_audio(np.zeros(16000 * 30, dtype=np.float32), 16000, 30.0)
    assert error is None


def test_queue_drops_oldest():
    q = AudioQueue(3)
    assert [q.push(i) for i in range(5)] == [0, 0, 0, 1, 1]
    assert len(q) == 3
    assert [q.pop(), q.pop(), q.pop(), q.pop()] == [2, 3, 4, None]


def test_resample_linear():
    x = np.sin(2 * np.pi * 440 * np.arange(16000) / 16000).astype(np.float32)
    y = resample_linear(x, 16000, 48000)
    assert y.size == 48000 and y.dtype == np.float32
    assert np.allclose(y[::3], x, atol=1e-6)
    assert resample_linear(x, 16000, 16000) is not None
