#!/usr/bin/env python
# coding: utf-8 -*-

"""Module for Interval manipulation (i.e. Box Enclosures)"""

from typing import Dict, List

Point = List[float]
Intv = Point
Box = Dict[str, Intv]


class IntvBoxer:
    """Interface Class to manipulate Box Enclosures of 3 dimensions (x, y, z).
    Preferably, other classes must inherit this class to use its functions."""

    def intv_width(self, intv: Intv) -> float:
        """Returns the width of a given interval."""
        return intv[1] - intv[0]

    def check_value_in_interval(self, intv: Intv, val: float) -> bool:
        """Returns true if a given value is contained inside an interval"""
        return intv[0] <= val <= intv[-1]

    def check_point_in_box(self, box: Box, point: Point) -> bool:
        """Returns true if a given 3D point is contained inside a Box"""
        coords = "xyz" if "z" in box else "xy"

        return all(
            self.check_value_in_interval(intv, val)
            for intv, val in zip([box[k] for k in coords], point)
        )

    def join_intervals(self, intv1: Intv, intv2: Intv) -> Intv:
        """Creates an interval that encloses the two input intervals"""
        joined = sorted(intv1 + intv2)
        return [joined[0], joined[-1]]

    def join_boxes(self, box1: Box, box2: Box) -> Box:
        """Creates a Box that encloses the two input Boxes"""
        coords = "xyz" if "z" in box1 and "z" in box2 else "xy"
        return {k: self.join_intervals(box1[k], box2[k]) for k in coords}

    def shift_box(
        self, p_old: Point, p_new: Point, box_old: Box, box_new: Box
    ) -> Box:
        """Shifts the position of a box based on the displacement between two points"""

        coords = "xyz" if "z" in box_old and "z" in box_new else "xy"

        shifts = [p_new[i] - p_old[i] for i in range(len(coords))]

        box_old_shifted: Box = {
            k: [box + shift for box, shift in zip(box_old[k], shifts)]
            for k in coords
        }

        return self.join_boxes(box_old_shifted, box_new)
