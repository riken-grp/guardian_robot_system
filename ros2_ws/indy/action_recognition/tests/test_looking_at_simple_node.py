import rclpy
import pytest
from action_recognition.looking_at_simple_node import LookingAtSimpleNode


def test_looking_at_simple_node_initialization():
    rclpy.init()
    try:
        node = LookingAtSimpleNode()
        node.destroy_node()
    finally:
        rclpy.shutdown()

import math
from types import SimpleNamespace

from action_recognition.looking_at_simple_node import (
    LookingAtRecognizerSimple, looking_angle)


def person(yaw, pitch, loc=(), instance_id=1):
    return SimpleNamespace(
        instance_id=instance_id,
        face_orientation=[yaw, pitch, 0.0],
        face_location_sensor=list(loc),
    )


def persons(*ps):
    return SimpleNamespace(persons=list(ps))


def test_frontal_face_at_center_is_looking():
    assert looking_angle([0, 0, 0], [0, 0, 2.0]) < 1e-6


def test_negative_angles_are_not_looking():
    # previous implementation accepted any negative yaw / pitch
    rec = LookingAtRecognizerSimple(20, 30)
    assert rec(persons(person(-60, 0, (0, 0, 2.0)))) == [0]
    assert rec(persons(person(0, -60, (0, 0, 2.0), instance_id=2))) == [0]


def test_off_center_face_turned_to_camera_is_looking():
    # face 1 m to the right at 2 m: it must turn by atan(1/2) to face the camera
    theta = math.degrees(math.atan2(1.0, 2.0))
    loc = (1.0, 0.0, 2.0)
    # facing x component is -sin(yaw), the camera is at -x, so yaw > 0
    assert looking_angle([theta, 0, 0], loc) < 1e-6
    assert looking_angle([-theta, 0, 0], loc) > 2 * theta - 1e-6
    # without the face position, only the optical axis is used
    assert abs(looking_angle([theta, 0, 0], loc, use_face_position=False) - theta) < 1e-6


def test_missing_pose_or_depth():
    assert looking_angle([], [0, 0, 2.0]) is None
    assert looking_angle([5, 0, 0], [0, 0, 0]) == looking_angle([5, 0, 0], None)


def test_hysteresis():
    # alpha = 1.0: no smoothing
    rec = LookingAtRecognizerSimple(20, 30, alpha=1.0)
    loc = (0, 0, 2.0)
    assert rec(persons(person(25, 0, loc)), now=0.0) == [0]  # not yet
    assert rec(persons(person(10, 0, loc)), now=0.1) == [1]  # turn on
    assert rec(persons(person(25, 0, loc)), now=0.2) == [1]  # keep (< release)
    assert rec(persons(person(35, 0, loc)), now=0.3) == [0]  # turn off
    assert rec(persons(person(25, 0, loc)), now=0.4) == [0]


def test_smoothing_suppresses_single_frame_jitter():
    rec = LookingAtRecognizerSimple(20, 30, alpha=0.5)
    loc = (0, 0, 2.0)
    assert rec(persons(person(0, 0, loc)), now=0.0) == [1]
    # a single outlier frame does not turn it off (EMA: 0.5 * 50 = 25 <= 30)
    assert rec(persons(person(50, 0, loc)), now=0.1) == [1]
    assert rec(persons(person(0, 0, loc)), now=0.2) == [1]
    # a sustained turn-away does
    rec(persons(person(60, 0, loc)), now=0.3)
    assert rec(persons(person(60, 0, loc)), now=0.4) == [0]


def test_smoothing_delays_turn_on():
    rec = LookingAtRecognizerSimple(20, 30, alpha=0.5)
    loc = (0, 0, 2.0)
    assert rec(persons(person(60, 0, loc)), now=0.0) == [0]
    assert rec(persons(person(0, 0, loc)), now=0.1) == [0]  # EMA 30
    assert rec(persons(person(0, 0, loc)), now=0.2) == [1]  # EMA 15


def test_state_kept_while_missing_within_timeout():
    rec = LookingAtRecognizerSimple(20, 30, alpha=1.0, timeout_sec=1.0)
    loc = (0, 0, 2.0)
    assert rec(persons(person(10, 0, loc)), now=0.0) == [1]
    # the person is not observed for 0.5 s (other persons only)
    assert rec(persons(person(80, 0, loc, instance_id=2)), now=0.5) == [0]
    # hysteresis state is kept: 25 deg is still looking
    assert rec(persons(person(25, 0, loc)), now=0.6) == [1]


def test_state_dropped_after_timeout():
    rec = LookingAtRecognizerSimple(20, 30, alpha=1.0, timeout_sec=1.0)
    loc = (0, 0, 2.0)
    assert rec(persons(person(10, 0, loc)), now=0.0) == [1]
    assert rec(persons(), now=1.5) == []
    assert 1 not in rec.states
    assert rec(persons(person(25, 0, loc)), now=1.6) == [0]


def test_missing_face_keeps_previous_state_until_timeout():
    rec = LookingAtRecognizerSimple(20, 30, alpha=1.0, timeout_sec=1.0)
    loc = (0, 0, 2.0)
    no_face = SimpleNamespace(instance_id=1, face_orientation=[], face_location_sensor=[])
    assert rec(persons(person(10, 0, loc)), now=0.0) == [1]
    assert rec(persons(no_face), now=0.5) == [1]
    # missing frames do not extend the state
    assert rec(persons(no_face), now=1.2) == [0]
    assert rec(persons(no_face), now=1.3) == [0]


def test_unassociated_persons_have_no_state():
    rec = LookingAtRecognizerSimple(20, 30, alpha=0.5)
    loc = (0, 0, 2.0)
    out = rec(persons(person(10, 0, loc, -1), person(25, 0, loc, -1)), now=0.0)
    assert out == [1, 0]
    assert rec.states == {}


def test_time_jump_back_resets_state():
    rec = LookingAtRecognizerSimple(20, 30, alpha=1.0)
    loc = (0, 0, 2.0)
    assert rec(persons(person(10, 0, loc)), now=10.0) == [1]
    assert rec(persons(person(25, 0, loc)), now=0.0) == [0]
