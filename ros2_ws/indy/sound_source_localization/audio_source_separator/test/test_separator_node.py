"""Integration test of SeparatorNode._on_audio with synthetic messages.

Requires a sourced ROS 2 workspace providing microphone_array / ssl_msgs.
"""

import math

import numpy as np
import pytest

rclpy = pytest.importorskip('rclpy')
mic_msgs = pytest.importorskip('microphone_array.msg')
ssl_msgs = pytest.importorskip('ssl_msgs.msg')

from audio_source_separator.separator_node import SeparatorNode  # noqa: E402

FS = 16000
BLK = 512
C = 343.0


def _positions():
    ang = np.arange(8) * 2 * np.pi / 8
    return np.stack([0.1 * np.cos(ang), 0.1 * np.sin(ang), np.zeros(8)], axis=1)


def _plane_wave(pos, src, az):
    rel = pos - pos.mean(axis=0)
    tau = -(rel @ np.array([math.cos(az), math.sin(az), 0.0])) / C
    n = len(src)
    nfft = 1 << int(np.ceil(np.log2(n + 512)))
    S = np.fft.rfft(src, nfft)
    f = np.fft.rfftfreq(nfft, 1 / FS)
    X = S[:, None] * np.exp(-2j * np.pi * f[:, None] * tau[None, :])
    return np.fft.irfft(X, nfft, axis=0)[:n]


@pytest.fixture
def node():
    rclpy.init()
    n = SeparatorNode()
    yield n
    n.destroy_node()
    rclpy.shutdown()


def _array_info(pos):
    m = mic_msgs.MicrophoneArrayInfo()
    m.header.frame_id = 'mic'
    m.num_channels = len(pos)
    m.sample_rate = float(FS)
    m.positions = pos.reshape(-1).tolist()
    return m


def _doa(azs):
    m = ssl_msgs.DOAEstimateArray()
    m.header.frame_id = 'mic'
    for a in azs:
        e = ssl_msgs.DOAEstimate()
        e.azimuth = float(a)
        e.power = 0.5
        m.estimates.append(e)
    return m


def _persons(items):
    m = ssl_msgs.TrackedPersonArray()
    m.header.frame_id = 'mic'
    for pid, az in items:
        p = ssl_msgs.TrackedPerson()
        p.person_id = pid
        p.azimuth = float(az)
        p.distance = 1.0
        p.x = math.cos(az)
        p.y = math.sin(az)
        m.persons.append(p)
    return m


def _audio(block, t_ns):
    m = mic_msgs.AudioDataMultiChannel()
    m.stamp.sec = t_ns // 1_000_000_000
    m.stamp.nanosec = t_ns % 1_000_000_000
    m.sample_rate = FS
    m.channels = block.shape[1]
    m.frames_per_block = block.shape[0]
    pcm = np.clip(block * 32767, -32768, 32767).astype(np.int16)
    m.data = pcm.reshape(-1).tolist()
    return m


def test_two_talkers_distinct_segments_and_continuation(node):
    pos = _positions()
    published = []
    node._segment_pub.publish = published.append
    node._on_array_info(_array_info(pos))

    rng = np.random.default_rng(0)
    n_blocks = 50
    n = BLK * n_blocks
    env_a = np.zeros(n)
    env_a[BLK * 5:BLK * 25] = 1.0   # talker A: blocks 5..24
    env_b = np.zeros(n)
    env_b[BLK * 15:BLK * 30] = 1.0  # talker B: blocks 15..29
    az_a, az_b = math.radians(30), math.radians(210)
    x = (_plane_wave(pos, 0.1 * env_a * rng.standard_normal(n), az_a)
         + _plane_wave(pos, 0.1 * env_b * rng.standard_normal(n), az_b)
         + 1e-4 * rng.standard_normal((n, len(pos))))

    for i in range(n_blocks):
        # DOA peaks only for active talkers (as SRP-PHAT with a power
        # threshold would report), and none at all during blocks 18..21:
        # the utterances must continue without gaps.
        if 18 <= i <= 21:
            node._doa_recv_time = -100.0
        else:
            active = ([az_a] if 5 <= i < 25 else []) + \
                     ([az_b] if 15 <= i < 30 else [])
            node._on_doa(_doa(active))
            node._on_tracked_persons(_persons([(1, az_a), (2, az_b)]))
        node._on_audio(_audio(x[i * BLK:(i + 1) * BLK], i * BLK * 62500))

    by_person = {}
    for seg in published:
        by_person.setdefault(seg.person_id, []).append(seg)
    assert set(by_person) == {1, 2}
    assert all(len(v) == 1 for v in by_person.values())
    sa, sb = by_person[1][0], by_person[2][0]
    # Contiguous utterances that include the onset (pre-roll)
    blk_ns = BLK * 62500
    assert sa.speech_start_ns == 5 * blk_ns
    assert sb.speech_start_ns == 15 * blk_ns
    for seg in (sa, sb):
        # No dropped blocks: samples == time span
        span = (seg.speech_end_ns - seg.speech_start_ns) * FS // 1_000_000_000
        assert len(seg.audio_data) == span
    assert sa.duration >= 20 * BLK / FS
    assert sb.duration >= 15 * BLK / FS
    assert sa.header.frame_id == 'mic'
    a = np.asarray(sa.audio_data)
    b = np.asarray(sb.audio_data)
    assert not np.allclose(a[:len(b)], b[:len(a)])
