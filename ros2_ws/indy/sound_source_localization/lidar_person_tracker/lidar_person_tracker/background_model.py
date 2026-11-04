"""Background subtraction for LaserScan data.

Learns a static background model during a calibration phase, then
filters out scan points that match the background (static objects).
Only points that differ significantly from the background are kept.
"""

import numpy as np


class BackgroundModel:
    """Per-ray background model using median + deviation threshold."""

    def __init__(self, learning_scans: int = 30, threshold: float = 0.15):
        """Initialize background model.

        Args:
            learning_scans: Number of scans to accumulate during calibration.
            threshold: Distance threshold (m) — a ray is foreground if its
                range differs from the background median by more than this.
        """
        self.learning_scans = learning_scans
        self.threshold = threshold

        self._scans: list[np.ndarray] = []
        self._background: np.ndarray | None = None
        self._calibrated = False

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    def update(self, ranges: np.ndarray) -> None:
        """Feed a scan during calibration phase."""
        if self._calibrated:
            return
        self._scans.append(np.array(ranges, dtype=np.float64))
        if len(self._scans) >= self.learning_scans:
            self._build_model()

    def _build_model(self) -> None:
        """Build background model from accumulated scans."""
        stacked = np.stack(self._scans, axis=0)  # (N_scans, N_rays)
        # Use median to be robust to occasional foreground objects during calibration
        self._background = np.nanmedian(stacked, axis=0)
        self._calibrated = True
        self._scans = []  # free memory

    def filter_foreground(self, ranges) -> list[float]:
        """Return ranges with background points replaced by inf.

        Points whose range is close to the learned background are considered
        static and replaced with inf so the clustering step ignores them.

        Args:
            ranges: Raw range values from LaserScan.

        Returns:
            Filtered range list (same length as input).
        """
        if not self._calibrated:
            return list(ranges)

        r = np.array(ranges, dtype=np.float64)
        bg = self._background

        # A point is foreground if:
        #  - the background was inf/nan (no static object) and now something appeared
        #  - or the range differs from background by more than threshold
        bg_valid = np.isfinite(bg)
        r_valid = np.isfinite(r)

        is_background = np.zeros(len(r), dtype=bool)

        # Both valid: compare ranges
        both_valid = bg_valid & r_valid
        is_background[both_valid] = np.abs(r[both_valid] - bg[both_valid]) <= self.threshold

        # Background was inf and current is also inf: still background
        both_inf = ~bg_valid & ~r_valid
        is_background[both_inf] = True

        # Replace background points with inf
        result = r.copy()
        result[is_background] = float('inf')
        return result.tolist()
