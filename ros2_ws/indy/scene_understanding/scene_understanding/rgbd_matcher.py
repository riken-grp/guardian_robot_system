"""Matching of color and depth frames by stamp (replaces ApproximateTimeSynchronizer).

ApproximateTimeSynchronizer keeps a fixed *number* of messages per topic.  When
the depth stream arrives later than the color stream by more than
``queue_size / fps`` (e.g. 5 frames = 0.33 s at 15 fps, easily reached over
the zenoh bridge since depth images are larger), the matching color frame has
already been dropped and almost no pair is produced any more.

Here both streams are buffered for a *duration* (``buffer_sec``) and matched by
stamp, as in association_node:

* a color frame matches the depth frame with the same stamp at once;
* otherwise the nearest depth frame within ``slop_sec`` is taken once it is
  final, i.e. a depth frame with a stamp >= the color stamp has arrived (no
  closer one can come any more, stamps of a stream increase);
* a color frame whose nearest depth frame is farther than ``slop_sec`` can
  never be matched and is dropped.

The recognition nodes are slower than the camera, so only the *newest* matched
pair is returned; older color frames are dropped (as the small BEST_EFFORT
queue did before).  Messages are kept as they are (compressed); only the
returned pair is decoded by the caller.
"""

import bisect
from dataclasses import dataclass, field

import numpy as np

STAT_KEYS = ("color_in", "depth_in", "exact", "approx", "superseded", "no_depth", "expired")


@dataclass
class _Frame:
    stamp: int  # ns
    msg: object
    arrival: float  # s


@dataclass
class RgbdStats:
    cnt: dict = field(default_factory=lambda: dict.fromkeys(STAT_KEYS, 0))
    # arrival(depth) - arrival(color) of the matched pairs [s]
    lag: list = field(default_factory=list)
    # |stamp(depth) - stamp(color)| of the approximate matches [s]
    diff: list = field(default_factory=list)

    @staticmethod
    def _summary(values, scale=1e3):
        if not values:
            return "-"
        return f"avg={np.mean(values) * scale:+.0f}ms max={np.max(values) * scale:+.0f}ms"

    def format(self, elapsed, n_color, n_depth):
        c = self.cnt
        return (
            f"[rgbd {elapsed:.0f}s] color in={c['color_in']} depth in={c['depth_in']} | "
            f"pairs={c['exact'] + c['approx']} (exact={c['exact']} approx={c['approx']}) "
            f"dropped: superseded={c['superseded']} no_depth={c['no_depth']} "
            f"expired={c['expired']} | "
            f"depth lag {self._summary(self.lag)} stamp diff {self._summary(self.diff)} | "
            f"buffered color={n_color} depth={n_depth}"
        )


class RgbdMatcher:
    def __init__(self, slop_sec=0.1, buffer_sec=2.0, max_frames=200):
        self.slop_ns = int(slop_sec * 1e9)
        self.buffer_ns = int(buffer_sec * 1e9)
        self.max_frames = max_frames
        self.colors = []  # sorted by stamp
        self.depths = []  # sorted by stamp
        self.stats = RgbdStats()

    def reset_stats(self):
        stats, self.stats = self.stats, RgbdStats()
        return stats

    # ------------------------------------------------------------ input
    def add_color(self, stamp_ns, msg, arrival):
        """Add a color frame; returns (color_msg, depth_msg) to process, or None."""
        self.stats.cnt["color_in"] += 1
        self._insert(self.colors, _Frame(stamp_ns, msg, arrival))
        return self._match()

    def add_depth(self, stamp_ns, msg, arrival):
        """Add a depth frame; returns (color_msg, depth_msg) to process, or None."""
        self.stats.cnt["depth_in"] += 1
        self._insert(self.depths, _Frame(stamp_ns, msg, arrival))
        return self._match()

    @staticmethod
    def _insert(frames, frame):
        # stamps normally increase; insort keeps the order if the transport
        # reorders frames (BEST_EFFORT)
        bisect.insort(frames, frame, key=lambda f: f.stamp)

    # ------------------------------------------------------------ matching
    def _nearest_depth(self, stamp):
        """(depth frame, final) nearest to ``stamp``; final: no closer one can come."""
        stamps = [d.stamp for d in self.depths]
        i = bisect.bisect_left(stamps, stamp)
        after = self.depths[i] if i < len(self.depths) else None
        before = self.depths[i - 1] if i > 0 else None
        if after is not None and after.stamp == stamp:
            return after, True
        if after is None:
            # only older depth frames so far: a closer one may still come
            return before, False
        if before is None or after.stamp - stamp <= stamp - before.stamp:
            return after, True
        return before, True

    def _match(self):
        self._prune()
        # newest color frame first: the node only processes the latest pair
        for ci in range(len(self.colors) - 1, -1, -1):
            color = self.colors[ci]
            depth, final = self._nearest_depth(color.stamp)
            if depth is None:
                continue
            diff = abs(depth.stamp - color.stamp)
            if diff > self.slop_ns:
                if final:
                    # never matched: drop it (and keep looking at older ones)
                    self.stats.cnt["no_depth"] += 1
                    del self.colors[ci]
                continue
            if not final:
                continue
            # matched: drop this and the older color frames, and older depth frames
            self.stats.cnt["exact" if diff == 0 else "approx"] += 1
            if diff:
                self.stats.diff.append(diff / 1e9)
            self.stats.lag.append(depth.arrival - color.arrival)
            self.stats.cnt["superseded"] += ci
            del self.colors[: ci + 1]
            self.depths = [d for d in self.depths if d.stamp >= depth.stamp]
            return color.msg, depth.msg
        return None

    def _prune(self):
        latest = max(
            (frames[-1].stamp for frames in (self.colors, self.depths) if frames),
            default=None,
        )
        if latest is None:
            return
        oldest = latest - self.buffer_ns
        n = len(self.colors)
        self.colors = [c for c in self.colors if c.stamp >= oldest][-self.max_frames:]
        self.stats.cnt["expired"] += n - len(self.colors)
        self.depths = [d for d in self.depths if d.stamp >= oldest][-self.max_frames:]
