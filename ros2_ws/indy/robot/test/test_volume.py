from robot.rosVolume import (VolumeController, clamp_volume, parse_sinks,
                             parse_volume_percent)

USB = "alsa_output.usb-0c76_USB_PnP_Audio_Device-00.analog-stereo"
SINKS = (
    "2\talsa_output.pci-0000_00_1f.3.iec958-stereo\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tRUNNING\n"
    f"5\t{USB}\tmodule-alsa-card.c\ts16le 2ch 48000Hz\tIDLE\n"
)
VOLUME = ("Volume: front-left: 32768 /  50% / -18.06 dB,   "
          "front-right: 32768 /  50% / -18.06 dB\n        balance 0.00\n")


class FakePactl:
    def __init__(self, sinks=SINKS, fail=()):
        self.sinks = sinks
        self.fail = fail
        self.calls = []
        self.volume = 30

    def __call__(self, cmd, timeout=None):
        self.calls.append(cmd)
        if cmd[1] in self.fail:
            return 1, "", "error"
        if cmd[1:] == ["list", "short", "sinks"]:
            return 0, self.sinks, ""
        if cmd[1] == "set-sink-volume":
            self.volume = int(cmd[3].rstrip("%"))
            return 0, "", ""
        if cmd[1] == "get-sink-volume":
            return 0, VOLUME.replace("50%", f"{self.volume}%"), ""
        return 0, "", ""


def test_parsers():
    assert parse_sinks(SINKS)[1] == USB
    assert parse_volume_percent(VOLUME) == 50
    assert parse_volume_percent("Volume: front-left: 1 / 40% / x, front-right: 1 / 61% / x") == 50
    assert parse_volume_percent("") is None
    assert clamp_volume(-5) == 0 and clamp_volume(150) == 100 and clamp_volume(90, 80) == 80


def test_set_volume_uses_percent_and_default_sink():
    fake = FakePactl()
    c = VolumeController(USB, runner=fake)
    assert c.set_volume(70) == 70
    assert ["pactl", "set-default-sink", USB] in fake.calls
    # "%" is required: a bare number is a raw volume (65536 = 100 %)
    assert ["pactl", "set-sink-volume", USB, "70%"] in fake.calls


def test_missing_sink_falls_back_to_default():
    fake = FakePactl(sinks=SINKS.splitlines()[0] + "\n")
    c = VolumeController(USB, runner=fake)
    assert c.set_volume(40) == 40
    assert ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "40%"] in fake.calls
    assert not any(cmd[1] == "set-default-sink" for cmd in fake.calls)


def test_missing_sink_without_fallback_is_rejected():
    fake = FakePactl(sinks="")
    c = VolumeController(USB, fallback_to_default_sink=False, runner=fake)
    assert c.set_volume(40) is None
    assert not any(cmd[1] == "set-sink-volume" for cmd in fake.calls)


def test_pactl_failure_returns_none():
    c = VolumeController(USB, runner=FakePactl(fail=("set-sink-volume",)))
    assert c.set_volume(40) is None


def test_play_uses_the_sink():
    fake = FakePactl()
    VolumeController(USB, runner=fake).play("/tmp/x.wav")
    assert fake.calls[-1] == ["paplay", f"--device={USB}", "/tmp/x.wav"]
