"""Recognize whether each person is looking at the robot (camera).

Input: recog/person/face/associated (Persons), where ``face_orientation`` is
the head pose [yaw, pitch, roll] in degrees estimated by Hopenet, and
``face_location_sensor`` is the 3D face position in the camera optical frame
(x right, y down, z forward).

The facing direction of the head is converted to a unit vector in the camera
frame (same convention as ``scene_understanding.utils.draw_axis``):

    f = (-sin(yaw), -cos(yaw) * sin(pitch), -cos(yaw) * cos(pitch))

(yaw = pitch = 0 faces the camera, i.e. -z).  A person is looking at the robot
when the angle between ``f`` and the direction from the face to the camera
(``-face_location_sensor``) is small.  When the 3D face position is not
available, the optical axis is used instead of the face-to-camera direction.

To suppress the jitter of the head pose estimation, per instance_id:

1. the angle is smoothed by an exponential moving average
   (``smoothing_alpha``; 1.0 disables the smoothing), and
2. a hysteresis is applied to the smoothed angle: the state turns on below
   ``looking_degree_threshold`` and turns off above
   ``looking_release_degree_threshold``.

The per-instance state is kept for ``state_timeout_sec`` after the last frame
with a valid head pose, so that a short track / face loss does not reset it.
In frames where the head pose of a known person is missing, the previous
state is output (until the timeout).  Persons with instance_id < 0 have no
state (raw angle and the on-threshold are used).  Times are ROS time (node
clock); the recognizer itself takes explicit timestamps for testing.

Output: recog/person/looking_at (StringStamped), json {instance_id: 0/1}
"""

import math
import time

import numpy as np
from rcl_interfaces.msg import ParameterDescriptor

from action_recognition.base_recognition_node import (BaseRecognitionNode,
                                                      recognition_node_main)


def facing_vector(yaw_deg, pitch_deg):
    """Unit facing direction of the head in the camera optical frame."""
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    return np.array(
        [
            -math.sin(yaw),
            -math.cos(yaw) * math.sin(pitch),
            -math.cos(yaw) * math.cos(pitch),
        ]
    )


def looking_angle(face_orientation, face_location_sensor=None, use_face_position=True):
    """Angle [deg] between the facing direction and the direction to the camera.

    Returns None when the head pose is not available.
    """
    if face_orientation is None or len(face_orientation) < 2:
        return None
    yaw, pitch = float(face_orientation[0]), float(face_orientation[1])
    if not (math.isfinite(yaw) and math.isfinite(pitch)):
        return None
    f = facing_vector(yaw, pitch)

    to_camera = np.array([0.0, 0.0, -1.0])  # optical axis (fallback)
    if (
        use_face_position
        and face_location_sensor is not None
        and len(face_location_sensor) >= 3
        and face_location_sensor[2] > 0  # valid depth
    ):
        p = np.asarray(face_location_sensor[:3], dtype=float)
        to_camera = -p / np.linalg.norm(p)

    cos = float(np.clip(np.dot(f, to_camera), -1.0, 1.0))
    return math.degrees(math.acos(cos))


class _LookingState:
    __slots__ = ("angle", "looking", "last_seen")

    def __init__(self, angle, looking, last_seen):
        self.angle = angle  # smoothed angle [deg]
        self.looking = looking
        self.last_seen = last_seen  # time of the last valid head pose [s]


class LookingAtRecognizerSimple:
    def __init__(
        self,
        threshold_deg=20.0,
        release_threshold_deg=30.0,
        use_face_position=True,
        alpha=0.5,
        timeout_sec=1.0,
        clock=None,
    ):
        self.threshold = float(threshold_deg)
        self.release_threshold = max(float(release_threshold_deg), self.threshold)
        self.use_face_position = use_face_position
        self.alpha = min(max(float(alpha), 1e-3), 1.0)
        self.timeout = float(timeout_sec)
        # clock(): current time [s], used when ``now`` is not given
        self.clock = clock if clock is not None else time.monotonic
        self.states = {}  # instance_id -> _LookingState

    def _expired(self, s, now):
        dt = now - s.last_seen
        return dt < 0 or dt > self.timeout  # dt < 0: time jumped back

    def __call__(self, persons, now=None):
        if now is None:
            now = self.clock()
        results = []
        for p in persons.persons:
            angle = looking_angle(
                list(p.face_orientation),
                list(p.face_location_sensor),
                self.use_face_position,
            )
            instance_id = int(p.instance_id)

            if instance_id < 0:
                # no track: no state, no smoothing
                results.append(int(angle is not None and angle <= self.threshold))
                continue

            s = self.states.get(instance_id)
            if s is not None and self._expired(s, now):
                del self.states[instance_id]
                s = None

            if angle is None:
                # head pose missing in this frame: keep the previous state
                results.append(int(s.looking) if s is not None else 0)
                continue

            if s is None:
                s = _LookingState(angle, False, now)
                self.states[instance_id] = s
            else:
                s.angle = self.alpha * angle + (1.0 - self.alpha) * s.angle
                s.last_seen = now

            if s.looking:
                s.looking = s.angle <= self.release_threshold
            else:
                s.looking = s.angle <= self.threshold
            results.append(int(s.looking))

        # forget persons that have not been observed for a while
        for instance_id in [k for k, s in self.states.items() if self._expired(s, now)]:
            del self.states[instance_id]
        return results


class LookingAtSimpleNode(BaseRecognitionNode):
    def __init__(self, name="LookingAtSimpleNode"):
        super().__init__(
            node_name=name,
            image_topic="in_topic",
            persons_topic="in_person_topic",
            output_topic="out_topic",
            vis_topic="vis_topic",
        )

    def _create_recognizer(self):
        # Declare specific parameters for this node here, after super().__init__ has run
        # dynamic_typing: accept both int (e.g. 20) and float (e.g. 20.0) in yaml
        any_number = ParameterDescriptor(dynamic_typing=True)
        self.declare_parameter("looking_degree_threshold", 20.0, any_number)
        self.declare_parameter("looking_release_degree_threshold", 30.0, any_number)
        self.declare_parameter("use_face_position", True)
        self.declare_parameter("smoothing_alpha", 0.5, any_number)
        self.declare_parameter("state_timeout_sec", 1.0, any_number)

        threshold = float(self.get_parameter("looking_degree_threshold").value)
        release = float(self.get_parameter("looking_release_degree_threshold").value)
        use_face_position = bool(self.get_parameter("use_face_position").value)
        alpha = float(self.get_parameter("smoothing_alpha").value)
        timeout = float(self.get_parameter("state_timeout_sec").value)
        self.get_logger().info(
            f"Looking threshold: {threshold} deg (release: {release} deg), "
            f"use_face_position: {use_face_position}, "
            f"smoothing_alpha: {alpha}, state_timeout_sec: {timeout}"
        )

        self.state_recognizer = LookingAtRecognizerSimple(
            threshold_deg=threshold,
            release_threshold_deg=release,
            use_face_position=use_face_position,
            alpha=alpha,
            timeout_sec=timeout,
            clock=lambda: self.get_clock().now().nanoseconds * 1e-9,
        )


def main():
    recognition_node_main(LookingAtSimpleNode)
