"""Tests for continuous per-person processing (track_persons) and DOA confirmation."""

import numpy as np

from audio_source_separator.source_manager import SourceManager
from audio_source_separator.separator_node import active_level_db

FS = 16000
BLK = 512
BLK_NS = BLK * 1_000_000_000 // FS


def _mgr(**kw):
    args = dict(vad_threshold_db=-70.0, vad_hangover_frames=3,
                vad_min_speech_frames=3, min_speech_duration=0.0,
                max_speech_duration=10.0, sample_rate=FS,
                time_func=lambda: 0.0, vad_preroll_frames=10,
                vad_adaptive=True, vad_margin_db=6.0, vad_noise_init_db=-66.0,
                require_doa_confirmation=True, doa_confirm_frames=10)
    args.update(kw)
    return SourceManager(**args)


def _blk(level_db, rng):
    return (10 ** (level_db / 20) * rng.standard_normal(BLK)).astype(np.float32)


def _run(m, levels, doa_at=(), pid=7, seed=0):
    """Feed blocks via track_persons; associate with a DOA peak at block indices in doa_at."""
    rng = np.random.default_rng(seed)
    segs = []
    for i, lv in enumerate(levels):
        assoc = {}
        if i in doa_at:
            assoc = m.associate_persons_with_doa([pid], [0.0], [1.0], [0.0], [1.0])
        m.track_persons([pid], [0.0], [1.0], exclude=set(assoc))
        segs += m.process_audio(pid, _blk(lv, rng), i * BLK_NS)
    return segs


def test_preroll_kept_when_processing_continuously():
    m = _mgr()
    # 60 noise blocks, 15 speech blocks, 10 noise blocks; DOA only at speech block 3
    levels = [-66] * 60 + [-50] * 15 + [-66] * 10
    segs = _run(m, levels, doa_at={63})
    assert len(segs) == 1
    s = segs[0]
    # pre-roll (10 blocks) + speech: segment starts before the speech onset
    assert s.speech_start_ns <= 60 * BLK_NS
    assert len(s.audio_data) >= 15 * BLK
    assert s.noise_floor_db is not None and s.noise_floor_db < -60


def test_segment_without_doa_is_dropped():
    m = _mgr()
    levels = [-66] * 60 + [-50] * 15 + [-66] * 10
    assert _run(m, levels, doa_at=set()) == []


def test_doa_shortly_before_onset_confirms():
    m = _mgr()
    levels = [-66] * 60 + [-50] * 15 + [-66] * 10
    assert len(_run(m, levels, doa_at={55})) == 1          # 5 blocks before onset
    m2 = _mgr()
    assert _run(m2, levels, doa_at={20}) == []              # too early


def test_confirmation_can_be_disabled():
    m = _mgr(require_doa_confirmation=False)
    levels = [-66] * 60 + [-50] * 15 + [-66] * 10
    assert len(_run(m, levels)) == 1


def test_active_level_db():
    rng = np.random.default_rng(0)
    a = (10 ** (-30 / 20) * rng.standard_normal(16000)).astype(np.float32)
    assert abs(active_level_db(a) + 30.0) < 2.0
    assert active_level_db(np.zeros(0, np.float32)) == -120.0
