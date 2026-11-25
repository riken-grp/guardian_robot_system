"""ROS-independent helpers of rosAudioPlay (conversion, validation, queue).

These are kept apart from the node so that they can be unit-tested without
rclpy or an audio device.
"""

from collections import deque

import numpy as np


def validate_audio(audio_data, sample_rate, max_duration=None):
    """Check a received audio.

    Returns (samples, error): ``samples`` is a float32 numpy array when the
    audio is valid (``error`` is None), otherwise ``samples`` is None and
    ``error`` is the reason.
    """
    try:
        sample_rate = int(sample_rate)
    except (TypeError, ValueError):
        return None, f"invalid sample_rate: {sample_rate!r}"
    if sample_rate <= 0:
        return None, f"invalid sample_rate: {sample_rate}"
    samples = np.asarray(audio_data, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return None, "empty audio_data"
    if not np.all(np.isfinite(samples)):
        return None, "audio_data contains NaN or Inf"
    duration = samples.size / sample_rate
    if max_duration is not None and max_duration > 0 and duration > max_duration:
        return None, f"too long: {duration:.2f} s > max_duration {max_duration:.2f} s"
    return samples, None


def resample_linear(samples, src_rate, dst_rate):
    """Resample with linear interpolation (no-op when the rates are equal)."""
    samples = np.asarray(samples, dtype=np.float32)
    if src_rate == dst_rate or samples.size == 0:
        return samples
    n_out = max(1, int(round(samples.size * dst_rate / src_rate)))
    t_out = np.arange(n_out) * (src_rate / dst_rate)
    t_in = np.arange(samples.size)
    return np.interp(t_out, t_in, samples).astype(np.float32)


def to_pcm16(samples):
    """float32 (-1..1) -> little-endian int16 bytes (out-of-range values are clipped)."""
    x = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (x * 32767.0).round().astype("<i2").tobytes()


class AudioQueue:
    """FIFO of audios waiting to be played; the oldest ones are dropped on overflow."""

    def __init__(self, max_size):
        self.max_size = max(1, int(max_size))
        self._q = deque()

    def push(self, item):
        """Add an item, return the number of items dropped to make room."""
        self._q.append(item)
        dropped = 0
        while len(self._q) > self.max_size:
            self._q.popleft()
            dropped += 1
        return dropped

    def pop(self):
        """Oldest item, or None when empty."""
        return self._q.popleft() if self._q else None

    def __len__(self):
        return len(self._q)
