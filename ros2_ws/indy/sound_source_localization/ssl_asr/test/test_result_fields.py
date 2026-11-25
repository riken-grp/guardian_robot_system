"""Tests for the confidence and speaker location of the ASR result."""

import math
from types import SimpleNamespace as NS

import pytest

pytest.importorskip('rclpy')
pytest.importorskip('common_msgs.msg')
pytest.importorskip('ssl_msgs.msg')

from ssl_asr.asr_node import speaker_location, transcript_confidence  # noqa: E402


def seg(avg_logprob, n_tokens=1, words=None):
    return NS(avg_logprob=avg_logprob, tokens=list(range(n_tokens)), words=words)


def test_confidence_word_probability():
    s = seg(-5.0, words=[NS(probability=0.8), NS(probability=0.6)])
    assert transcript_confidence([s]) == pytest.approx(0.7)


def test_confidence_token_weighted_logprob():
    c = transcript_confidence([seg(-0.1, 3), seg(-1.0, 1)])
    assert c == pytest.approx(math.exp((3 * -0.1 + 1 * -1.0) / 4))


def test_confidence_empty():
    assert transcript_confidence([]) == 0.0


def test_location_array_frame():
    x, y, z = speaker_location(math.pi / 2, 2.0)
    assert (x, y, z) == pytest.approx((0.0, 2.0, 0.0))


def test_location_base_frame():
    # array frame rotated by +90 deg (yaw) and shifted 0.1 m forward
    s = math.sin(math.pi / 4)
    tf = NS(transform=NS(rotation=NS(x=0.0, y=0.0, z=s, w=s),
                         translation=NS(x=0.1, y=0.0, z=0.5)))
    x, y, z = speaker_location(0.0, 1.0, tf)
    assert (x, y, z) == pytest.approx((0.1, 1.0, 0.5))
