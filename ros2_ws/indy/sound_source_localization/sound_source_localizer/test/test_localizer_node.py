"""Smoke test of SoundSourceLocalizerNode with a synthetic audio message."""

import math

import numpy as np
import pytest

rclpy = pytest.importorskip('rclpy')
mic_msgs = pytest.importorskip('microphone_array.msg')
pytest.importorskip('ssl_msgs.msg')

from sound_source_localizer.localizer_node import SoundSourceLocalizerNode  # noqa: E402

from test_srp_phat import _mic_positions, _plane_wave  # noqa: E402


def test_publishes_doa_for_source_and_nothing_for_silence():
    rclpy.init()
    node = SoundSourceLocalizerNode()
    try:
        out = []
        node.pub_doa.publish = out.append
        pos = _mic_positions()
        info = mic_msgs.MicrophoneArrayInfo()
        info.header.frame_id = 'mic'
        info.num_channels = len(pos)
        info.sample_rate = 16000.0
        info.positions = pos.reshape(-1).tolist()
        node._array_info_callback(info)

        rng = np.random.default_rng(0)
        x = _plane_wave(pos, 0.2 * rng.standard_normal(512), math.radians(-60))
        for block in (x, np.zeros_like(x)):
            msg = mic_msgs.AudioDataMultiChannel()
            msg.sample_rate = 16000
            msg.channels = len(pos)
            msg.frames_per_block = 512
            msg.data = (block.T * 32767).astype(np.int16).reshape(-1).tolist()
            node._audio_callback(msg)
        assert out[0].header.frame_id == 'mic'
        assert abs(math.degrees(out[0].estimates[0].azimuth) + 60) <= 5
        assert 0.0 < out[0].estimates[0].power <= 1.0
        assert len(out[1].estimates) == 0
    finally:
        node.destroy_node()
        rclpy.shutdown()
