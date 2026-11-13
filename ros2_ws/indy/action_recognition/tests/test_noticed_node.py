from action_recognition.noticed_node import NoticedRecognizer


def run(rec, ids, t0, t1, dt=0.1, looking=None, waving=None, raising=None, dist=None):
    """Feed cues every dt seconds in [t0, t1) and return the last evaluation."""
    t = t0
    out = None
    while t < t1 - 1e-9:
        for i in ids:
            if looking is not None:
                rec.update_looking(i, looking, t)
            if waving is not None:
                rec.update_waving(i, waving, t)
            if raising is not None:
                rec.update_raising(i, raising, t)
            d = dist(t) if dist is not None else 3.0
            rec.update_distance(i, [0.0, 0.0, d], t)
        out = rec.evaluate(ids, t)
        t += dt
    return out


def test_not_noticed_without_cues():
    rec = NoticedRecognizer()
    out = run(rec, [1], 0.0, 3.0)
    assert out[1]["noticed"] == 0


def test_waving_or_raising_is_noticed():
    rec = NoticedRecognizer()
    assert run(rec, [1], 0.0, 0.2, waving=True)[1]["noticed"] == 1
    rec = NoticedRecognizer()
    assert run(rec, [2], 0.0, 0.2, raising=True)[2]["noticed"] == 1


def test_looking_needs_duration():
    rec = NoticedRecognizer(looking_min_sec=1.0)
    assert run(rec, [1], 0.0, 0.5, looking=True)[1]["noticed"] == 0
    out = run(rec, [1], 0.5, 1.2, looking=True)
    assert out[1]["noticed"] == 1
    assert out[1]["looking_duration"] >= 1.0


def test_looking_interrupted_resets_duration():
    rec = NoticedRecognizer(looking_min_sec=1.0)
    run(rec, [1], 0.0, 0.8, looking=True)
    run(rec, [1], 0.8, 1.0, looking=False)
    assert run(rec, [1], 1.0, 1.6, looking=True)[1]["noticed"] == 0


def test_approaching_while_looking():
    rec = NoticedRecognizer(looking_min_sec=10.0)
    out = run(rec, [1], 0.0, 1.6, looking=True, dist=lambda t: 4.0 - 0.5 * t)
    assert out[1]["approaching"]
    assert out[1]["noticed"] == 1


def test_approaching_without_looking_is_not_noticed():
    rec = NoticedRecognizer()
    out = run(rec, [1], 0.0, 1.6, dist=lambda t: 4.0 - 0.5 * t)
    assert out[1]["approaching"]
    assert out[1]["noticed"] == 0


def test_hold_and_stale():
    rec = NoticedRecognizer(hold_sec=2.0, stale_sec=1.0)
    run(rec, [1], 0.0, 0.2, waving=True)
    # cue stops; noticed is held for hold_sec, then released
    assert run(rec, [1], 0.2, 1.5)[1]["noticed"] == 1
    assert run(rec, [1], 1.5, 3.5)[1]["noticed"] == 0


def test_far_person_ignored():
    rec = NoticedRecognizer(max_distance=6.0)
    out = run(rec, [1], 0.0, 0.2, waving=True, dist=lambda t: 8.0)
    assert out[1]["noticed"] == 0


def test_stale_distance_is_unknown():
    rec = NoticedRecognizer(max_distance=6.0, stale_sec=1.0)
    # the person was far away, then the depth became invalid
    run(rec, [1], 0.0, 0.5, dist=lambda t: 8.0)
    rec.update_distance(1, [0.0, 0.0, 0.0], 2.0)
    rec.update_waving(1, True, 2.0)
    out = rec.evaluate([1], 2.0)
    # 8 m sample is 1.5 s old -> unknown distance -> regarded as in range
    assert out[1]["distance"] == -1.0
    assert out[1]["noticed"] == 1


def test_fresh_far_distance_still_ignored():
    rec = NoticedRecognizer(max_distance=6.0, stale_sec=1.0)
    run(rec, [1], 0.0, 0.5, dist=lambda t: 8.0)
    rec.update_waving(1, True, 1.0)
    out = rec.evaluate([1], 1.0)
    assert out[1]["distance"] == 8.0
    assert out[1]["noticed"] == 0


def test_negative_ids_are_ignored():
    rec = NoticedRecognizer()
    rec.update_looking(-1, True, 0.0)
    rec.update_waving(-1, True, 0.0)
    rec.update_raising(-1, True, 0.0)
    rec.update_distance(-1, [0.0, 0.0, 2.0], 0.0)
    assert rec.states == {}
    assert rec.evaluate([-1], 0.0) == {}
    assert rec.states == {}


def test_approach_speed_matches_polyfit():
    import numpy as np

    rec = NoticedRecognizer(approach_window_sec=1.5, approach_min_samples=5)
    rng = np.random.default_rng(0)
    samples = []

    def dist(t):
        d = 4.0 - 0.3 * t + rng.normal(0, 0.05)
        samples.append((t, d))
        return d

    out = run(rec, [1], 0.0, 3.0, dist=dist)
    # reference: polyfit over the samples within the window of the last time
    now = samples[-1][0]
    pts = [(t, d) for t, d in samples if now - t <= 1.5]
    t = np.array([p[0] for p in pts])
    d = np.array([p[1] for p in pts])
    ref = -np.polyfit(t - t[0], d, 1)[0]
    assert abs(out[1]["approach_speed"] - ref) < 1e-9
