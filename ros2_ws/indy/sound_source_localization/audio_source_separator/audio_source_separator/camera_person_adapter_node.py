"""ROS2 node that converts camera person detections into ssl_msgs/TrackedPersonArray.

Subscribes recognition_msgs/Persons (``recog/person/pose/associated``), whose
``body_location_sensor`` is the 3D body position in the camera (optical) frame,
transforms the positions into ``output_frame`` with tf2 and publishes them as
``ssl_msgs/TrackedPersonArray`` so that separator_node can associate DOA peaks
with camera-detected persons.

mode:
  camera  publish camera persons only (published on every camera message)
  merge   camera persons + LiDAR tracks that are outside the camera FOV or
          farther than ``lidar_match_distance`` from every camera person
          (published on every LiDAR message, so LiDAR keeps working when the
          camera stream stops)
"""

import math
import os

import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.time import Time

from recognition_msgs.msg import Persons
from ssl_msgs.msg import TrackedPerson, TrackedPersonArray

from .tf_utils import transform_points

try:
    from tf2_ros import Buffer, TransformListener
except ImportError:  # pragma: no cover - tf2_ros is part of ROS 2 desktop
    Buffer = None
    TransformListener = None


def _default_output_frame() -> str:
    robot = os.getenv('ROBOT_NAME', '')
    return f'{robot}_body_link' if robot else 'body_link'


class CameraPersonAdapterNode(Node):

    def __init__(self):
        super().__init__('camera_person_adapter_node')
        self.declare_parameter('mode', 'merge')                 # 'camera' | 'merge'
        self.declare_parameter('output_frame', _default_output_frame())
        self.declare_parameter('persons_frame', '')             # fallback if header has no frame_id
        self.declare_parameter('min_distance', 0.2)             # m, in the output x-y plane
        self.declare_parameter('max_distance', 5.0)             # m
        self.declare_parameter('camera_hfov_deg', 90.0)         # horizontal FOV of the color camera (indy3e: 2*atan(640/644) = 89.6 deg)
        self.declare_parameter('fov_margin_deg', 5.0)           # LiDAR tracks this close to the FOV edge are dropped
        self.declare_parameter('camera_timeout', 1.0)           # s; camera persons older than this are ignored (merge)
        self.declare_parameter('lidar_match_distance', 0.5)     # m; LiDAR track this close to a camera person is dropped
        self.declare_parameter('lidar_min_distance', 0.5)       # m; LiDAR tracks closer than this are dropped (robot parts, dock)
        self.declare_parameter('lidar_id_offset', 1000000000)   # added to LiDAR person_id to avoid ID collisions
        self.declare_parameter('velocity_alpha', 0.5)           # EMA weight of the velocity estimate

        self._tf_buffer = Buffer() if Buffer is not None else None
        self._tf_listener = (TransformListener(self._tf_buffer, self)
                             if self._tf_buffer is not None else None)

        self._cam_persons = []       # list of (id, x, y) in output_frame
        self._cam_stamp = None       # builtin_interfaces/Time of the camera message
        self._cam_recv = None        # receive time [s]
        self._cam_axis_az = 0.0      # azimuth of the camera optical axis in output_frame [rad]
        self._prev = {}              # id -> (t, x, y, vx, vy)

        self.create_subscription(Persons, 'in_persons', self._on_persons, 10)
        if self._mode() == 'merge':
            self.create_subscription(TrackedPersonArray, 'in_lidar_persons', self._on_lidar, 10)
        self._pub = self.create_publisher(TrackedPersonArray, 'out_tracked_persons', 10)
        self.get_logger().info(
            f'CameraPersonAdapterNode started (mode={self._mode()}, '
            f'output_frame={self._out_frame()})')

    # ------------------------------------------------------------------
    def _mode(self) -> str:
        return self.get_parameter('mode').value

    def _out_frame(self) -> str:
        return self.get_parameter('output_frame').value

    def _lookup(self, target: str, source: str, stamp=None):
        if self._tf_buffer is None:
            return None
        for t in ((Time.from_msg(stamp),) if stamp is not None else ()) + (Time(),):
            try:
                return self._tf_buffer.lookup_transform(
                    target, source, t, timeout=Duration(seconds=0.0))
            except Exception:  # noqa: BLE001 (tf2 raises several types)
                continue
        self.get_logger().warn(f'TF {source} -> {target} unavailable',
                               throttle_duration_sec=5.0)
        return None

    def _velocity(self, pid: int, t: float, x: float, y: float):
        alpha = self.get_parameter('velocity_alpha').value
        vx = vy = 0.0
        prev = self._prev.get(pid)
        if prev is not None and 0.0 < t - prev[0] < 2.0:
            dt = t - prev[0]
            vx = alpha * (x - prev[1]) / dt + (1.0 - alpha) * prev[3]
            vy = alpha * (y - prev[2]) / dt + (1.0 - alpha) * prev[4]
        self._prev[pid] = (t, x, y, vx, vy)
        return vx, vy

    @staticmethod
    def _make_person(pid: int, x: float, y: float, vx: float, vy: float) -> TrackedPerson:
        p = TrackedPerson()
        p.person_id = int(pid)
        p.x, p.y, p.vx, p.vy = float(x), float(y), float(vx), float(vy)
        p.azimuth = float(math.atan2(y, x))
        p.distance = float(math.hypot(x, y))
        return p

    # ------------------------------------------------------------------
    def _on_persons(self, msg: Persons) -> None:
        frame = msg.header.frame_id or self.get_parameter('persons_frame').value
        cands = [p for p in msg.persons
                 if p.instance_id >= 0 and len(p.body_location_sensor) >= 3
                 and all(math.isfinite(v) for v in p.body_location_sensor[:3])
                 and p.body_location_sensor[2] > 0.0]
        persons = []
        if frame and cands:
            tf = self._lookup(self._out_frame(), frame, msg.header.stamp)
            if tf is not None:
                pts = transform_points(
                    tf, np.array([list(p.body_location_sensor[:3]) for p in cands]))
                axis = transform_points(tf, np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]))
                self._cam_axis_az = math.atan2(axis[1, 1] - axis[0, 1], axis[1, 0] - axis[0, 0])
                dmin = self.get_parameter('min_distance').value
                dmax = self.get_parameter('max_distance').value
                for p, (x, y, _z) in zip(cands, pts):
                    if dmin <= math.hypot(x, y) <= dmax:
                        persons.append((p.instance_id, float(x), float(y)))
        self._cam_persons = persons
        self._cam_stamp = msg.header.stamp
        self._cam_recv = self.get_clock().now().nanoseconds * 1e-9
        if self._mode() == 'camera':
            self._publish(msg.header.stamp, persons, [])

    def _on_lidar(self, msg: TrackedPersonArray) -> None:
        now = self.get_clock().now().nanoseconds * 1e-9
        cam = []
        if self._cam_recv is not None and now - self._cam_recv <= self.get_parameter('camera_timeout').value:
            cam = self._cam_persons
        lidar = []
        if msg.persons:
            tf = self._lookup(self._out_frame(), msg.header.frame_id, msg.header.stamp)
            if tf is not None:
                pts = transform_points(tf, np.array([[p.x, p.y, 0.0] for p in msg.persons]))
                half = math.radians(self.get_parameter('camera_hfov_deg').value / 2.0
                                    - self.get_parameter('fov_margin_deg').value)
                match_d = self.get_parameter('lidar_match_distance').value
                offset = self.get_parameter('lidar_id_offset').value
                cam_ok = bool(cam) or (self._cam_recv is not None
                                       and now - self._cam_recv <= self.get_parameter('camera_timeout').value)
                lmin = self.get_parameter('lidar_min_distance').value
                for p, (x, y, _z) in zip(msg.persons, pts):
                    if math.hypot(x, y) < lmin:
                        continue
                    az = math.atan2(y, x)
                    in_fov = abs(math.atan2(math.sin(az - self._cam_axis_az),
                                            math.cos(az - self._cam_axis_az))) <= half
                    near_cam = any(math.hypot(x - cx, y - cy) <= match_d for _, cx, cy in cam)
                    # Inside the FOV the camera is trusted while it is alive:
                    # LiDAR-only tracks there are treated as false positives.
                    if near_cam or (in_fov and cam_ok):
                        continue
                    lidar.append((p.person_id + offset, float(x), float(y)))
        self._publish(msg.header.stamp, cam, lidar)

    def _publish(self, stamp, cam, lidar) -> None:
        out = TrackedPersonArray()
        out.header.stamp = stamp
        out.header.frame_id = self._out_frame()
        t = Time.from_msg(stamp).nanoseconds * 1e-9
        for pid, x, y in list(cam) + list(lidar):
            vx, vy = self._velocity(pid, t, x, y)
            out.persons.append(self._make_person(pid, x, y, vx, vy))
        # Forget velocity history of IDs not seen for a while
        self._prev = {k: v for k, v in self._prev.items() if t - v[0] < 5.0}
        self._pub.publish(out)


def main(args=None):
    rclpy.init(args=args)
    node = CameraPersonAdapterNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
