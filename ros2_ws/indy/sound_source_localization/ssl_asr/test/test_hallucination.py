"""Tests for the hallucination / low-confidence filters of the ASR node."""

import pytest

pytest.importorskip('rclpy')
pytest.importorskip('common_msgs.msg')
pytest.importorskip('ssl_msgs.msg')

from ssl_asr.asr_node import (  # noqa: E402
    DEFAULT_HALLUCINATION_PHRASES, is_hallucination, keep_segment)

P = DEFAULT_HALLUCINATION_PHRASES


@pytest.mark.parametrize('text', [
    'ご視聴ありがとうございました',
    'ご視聴ありがとうございました。',
    ' ご視聴ありがとうございました ご視聴ありがとうございました',
    'チャンネル登録よろしくお願いします!',
    '',
    '。',
])
def test_hallucination_detected(text):
    assert is_hallucination(text, P)


@pytest.mark.parametrize('text', [
    'ありがとうございました',
    'こんにちは',
    'ご視聴ありがとうございました、それと道を教えて',
    'お疲れ様でした',
])
def test_real_speech_kept(text):
    assert not is_hallucination(text, P)


def test_keep_segment():
    assert keep_segment(0.1, -0.3, 1.5, 0.6, -1.0, 2.4)
    assert not keep_segment(0.9, -1.5, 1.5, 0.6, -1.0, 2.4)   # silence
    assert keep_segment(0.9, -0.5, 1.5, 0.6, -1.0, 2.4)       # confident despite high no_speech
    assert not keep_segment(0.1, -0.3, 3.0, 0.6, -1.0, 2.4)   # repetitive
