"""Unit tests for SourceManager (VAD pre-roll, max-duration split)."""

import numpy as np

from audio_source_separator.source_manager import SourceManager

FS = 16000
BLK = 512
BLK_NS = BLK * 1_000_000_000 // FS


class _Clock:
    t = 0.0

    def __call__(self):
        return self.t


def _mgr(**kw):
    clock = _Clock()
    args = dict(vad_threshold_db=-30.0, vad_hangover_frames=3,
                vad_min_speech_frames=3, min_speech_duration=0.0,
                max_speech_duration=10.0, sample_rate=FS, time_func=clock,
                vad_preroll_frames=2)
    args.update(kw)
    m = SourceManager(**args)
    m.associate_persons_with_doa([7], [0.0], [1.0], [0.0], [1.0])
    return m, clock


def _blocks(levels, seed=0):
    rng = np.random.default_rng(seed)
    return [lvl * rng.standard_normal(BLK).astype(np.float32) for lvl in levels]


def _feed(m, blocks, pid=7, t0=0):
    segs = []
    for i, b in enumerate(blocks):
        segs += m.process_audio(pid, b, t0 + i * BLK_NS)
    return segs


def test_preroll_keeps_onset_blocks():
    m, _ = _mgr()
    quiet, loud = 1e-4, 0.3
    levels = [quiet] * 4 + [loud] * 6 + [quiet] * 5
    blocks = _blocks(levels)
    segs = _feed(m, blocks)
    assert len(segs) == 1
    seg = segs[0]
    # Onset confirmed at the 3rd loud block (index 6); pre-roll = max(2,
    # min_speech_frames-1=2) blocks -> starts at the first loud block (4).
    assert seg.speech_start_ns == 4 * BLK_NS
    np.testing.assert_array_equal(seg.audio_data[:BLK], blocks[4])
    # loud blocks + hangover (3 quiet blocks, offset on the 3rd)
    assert len(seg.audio_data) == (6 + 3) * BLK
    assert seg.speech_end_ns == (4 + 6 + 3) * BLK_NS


def test_max_duration_split_loses_nothing():
    max_dur = 10 * BLK / FS
    m, _ = _mgr(max_speech_duration=max_dur)
    levels = [0.3] * 25 + [1e-4] * 5
    blocks = _blocks(levels, seed=1)
    segs = _feed(m, blocks)
    assert len(segs) >= 3
    total = sum(len(s.audio_data) for s in segs)
    # All loud blocks (and the hangover) are covered, contiguous in time
    assert total == (25 + 3) * BLK
    for a, b in zip(segs, segs[1:]):
        assert a.speech_end_ns == b.speech_start_ns
    joined = np.concatenate([s.audio_data for s in segs])
    np.testing.assert_array_equal(joined[:25 * BLK], np.concatenate(blocks[:25]))


def test_gap_resets_preroll():
    m, _ = _mgr()
    b = _blocks([0.3] * 4)
    # two loud blocks, then a gap of several blocks, then two loud blocks
    m.process_audio(7, b[0], 0)
    m.process_audio(7, b[1], BLK_NS)
    assert m.process_audio(7, b[2], 10 * BLK_NS) == []
    assert not m.sources[7].is_speaking  # onset counter was reset by the gap


def test_speaking_sources_and_stale_cleanup():
    m, clock = _mgr(stale_timeout=1.0)
    _feed(m, _blocks([0.3] * 5))
    assert m.speaking_sources() == {7: 0.0}
    # Feeding audio does not refresh the association time
    clock.t = 2.0
    _feed(m, _blocks([0.3] * 2), t0=5 * BLK_NS)
    segs = m.cleanup_stale()
    assert len(segs) == 1 and 7 not in m.sources
    assert segs[0].speech_end_ns == 7 * BLK_NS


def test_one_to_one_association():
    m, _ = _mgr()
    assoc = m.associate_persons_with_doa(
        [1, 2], [0.0, 0.05], [1.0, 1.0], [0.02], [1.0])
    assert len(assoc) == 1
