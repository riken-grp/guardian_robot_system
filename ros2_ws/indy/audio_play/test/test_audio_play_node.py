import numpy as np
import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("ssl_msgs.msg")

from ssl_msgs.msg import SpeechSegment  # noqa: E402

from audio_play.rosAudioPlay import AudioPlayNode  # noqa: E402


class FakePlayObj:
    def __init__(self):
        self.playing = True

    def is_playing(self):
        return self.playing

    def stop(self):
        self.playing = False


class FakePlayer:
    def __init__(self):
        self.calls = []
        self.objs = []

    def __call__(self, pcm, channels, width, rate):
        self.calls.append((pcm, channels, width, rate))
        self.objs.append(FakePlayObj())
        return self.objs[-1]


@pytest.fixture
def node():
    rclpy.init()
    player = FakePlayer()
    n = AudioPlayNode(player=player)
    n.player = player
    yield n
    n.destroy_node()
    rclpy.shutdown()


def msg(n=1600, rate=16000, value=0.1):
    m = SpeechSegment()
    m.sample_rate = rate
    m.audio_data = [value] * n
    return m


def test_plays_one_by_one(node):
    node.on_audio(msg())
    node.on_audio(msg())
    assert len(node.player.calls) == 1
    pcm, ch, width, rate = node.player.calls[0]
    assert (ch, width, rate, len(pcm)) == (1, 2, 16000, 3200)
    node.on_timer()
    assert len(node.player.calls) == 1  # still playing
    node.player.objs[0].playing = False
    node.on_timer()
    assert len(node.player.calls) == 2


def test_invalid_audio_is_ignored(node):
    node.on_audio(msg(n=0))
    node.on_audio(msg(rate=0))
    m = msg()
    m.audio_data[3] = float("nan")
    node.on_audio(m)
    assert node.player.calls == []


def test_queue_overflow(node):
    node.on_audio(msg(value=0.0))  # playing
    for v in (0.1, 0.2, 0.3, 0.4):
        node.on_audio(msg(value=v))
    played = []
    for _ in range(5):
        node.player.objs[-1].playing = False
        node.on_timer()
    for pcm, *_ in node.player.calls[1:]:
        played.append(int(np.frombuffer(pcm, dtype="<i2")[0]))
    assert played == [round(v * 32767) for v in (0.2, 0.3, 0.4)]
