"""ROS2 node for LiDAR-based person tracking."""

import math
import struct

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan, PointCloud2, PointField
from std_msgs.msg import ColorRGBA, Header
from geometry_msgs.msg import Point, Vector3
from visualization_msgs.msg import Marker, MarkerArray
from ssl_msgs.msg import TrackedPerson, TrackedPersonArray

from lidar_person_tracker.background_model import BackgroundModel
from lidar_person_tracker.clustering import extract_person_positions
from lidar_person_tracker.kalman_tracker import PersonTracker

# Distinct colours for up to 10 persons (reused cyclically)
_COLORS = [
    (1.0, 0.2, 0.2), (0.2, 0.6, 1.0), (0.2, 1.0, 0.2),
    (1.0, 0.8, 0.0), (0.8, 0.2, 1.0), (1.0, 0.5, 0.0),
    (0.0, 1.0, 0.8), (0.6, 0.4, 0.2), (1.0, 0.4, 0.7),
    (0.4, 0.4, 1.0),
]


class TrackerNode(Node):

    def __init__(self):
        super().__init__('tracker_node')

        # Declare parameters
        self.declare_parameter('cluster_distance_threshold', 0.15)
        self.declare_parameter('min_cluster_size', 3)
        self.declare_parameter('max_cluster_size', 50)
        self.declare_parameter('min_cluster_width', 0.1)
        self.declare_parameter('max_cluster_width', 0.6)
        self.declare_parameter('max_cluster_depth', 0.40)
        self.declare_parameter('min_detection_range', 0.3)
        self.declare_parameter('max_detection_range', 2.0)
        self.declare_parameter('tracking_distance_threshold', 1.0)
        self.declare_parameter('person_timeout', 2.0)
        self.declare_parameter('process_noise', 0.5)
        self.declare_parameter('measurement_noise', 0.1)
        self.declare_parameter('bg_learning_scans', 30)
        self.declare_parameter('bg_threshold', 0.15)
        self.declare_parameter('bg_enabled', True)

        # Read parameters
        self._cluster_dist = self.get_parameter('cluster_distance_threshold').value
        self._min_cluster_size = self.get_parameter('min_cluster_size').value
        self._max_cluster_size = self.get_parameter('max_cluster_size').value
        self._min_cluster_width = self.get_parameter('min_cluster_width').value
        self._max_cluster_width = self.get_parameter('max_cluster_width').value
        self._max_cluster_depth = self.get_parameter('max_cluster_depth').value
        self._min_range = self.get_parameter('min_detection_range').value
        self._max_range = self.get_parameter('max_detection_range').value
        tracking_dist = self.get_parameter('tracking_distance_threshold').value
        person_timeout = self.get_parameter('person_timeout').value
        process_noise = self.get_parameter('process_noise').value
        measurement_noise = self.get_parameter('measurement_noise').value

        # Initialize background model
        self._bg_enabled = self.get_parameter('bg_enabled').value
        self._bg_model = BackgroundModel(
            learning_scans=self.get_parameter('bg_learning_scans').value,
            threshold=self.get_parameter('bg_threshold').value,
        )

        # Initialize tracker
        self._tracker = PersonTracker(
            tracking_distance_threshold=tracking_dist,
            person_timeout=person_timeout,
            process_noise=process_noise,
            measurement_noise=measurement_noise,
        )

        # Publishers
        self._pub = self.create_publisher(TrackedPersonArray, 'out_tracked_persons', 10)
        self._pub_markers = self.create_publisher(MarkerArray, 'out_viz_markers', 10)
        self._pub_cluster_cloud = self.create_publisher(PointCloud2, 'out_viz_clusters', 10)

        # Subscriber: main scan (remapped via launch for sim/real)
        self._sub = self.create_subscription(
            LaserScan, 'in_scan', self._scan_callback, qos_profile_sensor_data,
        )

        self.get_logger().info('TrackerNode started.')

    def _has_viz_subscribers(self) -> bool:
        return (self._pub_markers.get_subscription_count() > 0
                or self._pub_cluster_cloud.get_subscription_count() > 0)

    def _scan_callback(self, msg: LaserScan):
        # Background subtraction
        if self._bg_enabled:
            if not self._bg_model.calibrated:
                self._bg_model.update(msg.ranges)
                if self._bg_model.calibrated:
                    self.get_logger().info(
                        f'Background model calibrated '
                        f'({self._bg_model.learning_scans} scans)'
                    )
                return
            filtered_ranges = self._bg_model.filter_foreground(msg.ranges)
        else:
            filtered_ranges = list(msg.ranges)

        need_viz = self._has_viz_subscribers()

        # Extract person candidates from filtered scan
        if need_viz:
            centroids, person_clusters = extract_person_positions(
                ranges=filtered_ranges,
                angle_min=msg.angle_min,
                angle_increment=msg.angle_increment,
                max_range=self._max_range,
                min_range=self._min_range,
                cluster_distance_threshold=self._cluster_dist,
                min_cluster_size=self._min_cluster_size,
                max_cluster_size=self._max_cluster_size,
                min_cluster_width=self._min_cluster_width,
                max_cluster_width=self._max_cluster_width,
                max_cluster_depth=self._max_cluster_depth,
                return_clusters=True,
            )
        else:
            centroids = extract_person_positions(
                ranges=filtered_ranges,
                angle_min=msg.angle_min,
                angle_increment=msg.angle_increment,
                max_range=self._max_range,
                min_range=self._min_range,
                cluster_distance_threshold=self._cluster_dist,
                min_cluster_size=self._min_cluster_size,
                max_cluster_size=self._max_cluster_size,
                min_cluster_width=self._min_cluster_width,
                max_cluster_width=self._max_cluster_width,
                max_cluster_depth=self._max_cluster_depth,
            )

        # Use message timestamp so rosbag playback and simulation work correctly
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        tracks = self._tracker.update(centroids, timestamp=stamp)

        # Build and publish tracking message
        out_msg = TrackedPersonArray()
        out_msg.header = msg.header

        for track in tracks:
            person = TrackedPerson()
            person.person_id = track.person_id
            x, y = track.position
            person.x = float(x)
            person.y = float(y)
            vx, vy = track.velocity
            person.vx = float(vx)
            person.vy = float(vy)
            person.azimuth = float(track.azimuth)
            person.distance = float(track.distance)
            out_msg.persons.append(person)

        self._pub.publish(out_msg)

        # Publish visualization only when subscribers exist
        if need_viz:
            self._publish_viz(msg.header, tracks, person_clusters)

    def _publish_viz(self, header: Header, tracks, person_clusters):
        marker_array = MarkerArray()
        marker_id = 0

        for i, track in enumerate(tracks):
            color = _COLORS[track.person_id % len(_COLORS)]
            x, y = track.position
            vx, vy = track.velocity

            # Cylinder marker for person position
            m = Marker()
            m.header = header
            m.ns = 'person'
            m.id = marker_id
            marker_id += 1
            m.type = Marker.CYLINDER
            m.action = Marker.ADD
            m.pose.position = Point(x=float(x), y=float(y), z=0.5)
            m.scale = Vector3(x=0.3, y=0.3, z=1.0)
            m.color = ColorRGBA(r=color[0], g=color[1], b=color[2], a=0.6)
            m.lifetime.sec = 0
            m.lifetime.nanosec = 500_000_000
            marker_array.markers.append(m)

            # Text marker for person ID
            t = Marker()
            t.header = header
            t.ns = 'person_id'
            t.id = marker_id
            marker_id += 1
            t.type = Marker.TEXT_VIEW_FACING
            t.action = Marker.ADD
            t.pose.position = Point(x=float(x), y=float(y), z=1.2)
            t.scale.z = 0.3
            t.color = ColorRGBA(r=1.0, g=1.0, b=1.0, a=1.0)
            t.text = f'ID:{track.person_id}'
            t.lifetime.sec = 0
            t.lifetime.nanosec = 500_000_000
            marker_array.markers.append(t)

            # Arrow marker for velocity
            speed = math.sqrt(vx * vx + vy * vy)
            if speed > 0.05:
                a = Marker()
                a.header = header
                a.ns = 'velocity'
                a.id = marker_id
                marker_id += 1
                a.type = Marker.ARROW
                a.action = Marker.ADD
                a.points = [
                    Point(x=float(x), y=float(y), z=0.5),
                    Point(x=float(x + vx), y=float(y + vy), z=0.5),
                ]
                a.scale = Vector3(x=0.05, y=0.1, z=0.0)
                a.color = ColorRGBA(r=color[0], g=color[1], b=color[2], a=0.8)
                a.lifetime.sec = 0
                a.lifetime.nanosec = 500_000_000
                marker_array.markers.append(a)

        # Detection range circle
        r_marker = Marker()
        r_marker.header = header
        r_marker.ns = 'detection_range'
        r_marker.id = marker_id
        marker_id += 1
        r_marker.type = Marker.LINE_STRIP
        r_marker.action = Marker.ADD
        r_marker.scale.x = 0.02
        r_marker.color = ColorRGBA(r=0.5, g=0.5, b=0.5, a=0.3)
        r_marker.lifetime.sec = 0
        r_marker.lifetime.nanosec = 500_000_000
        n_pts = 64
        for j in range(n_pts + 1):
            angle = 2.0 * math.pi * j / n_pts
            r_marker.points.append(Point(
                x=self._max_range * math.cos(angle),
                y=self._max_range * math.sin(angle),
                z=0.0,
            ))
        marker_array.markers.append(r_marker)

        self._pub_markers.publish(marker_array)

        # Cluster point cloud (coloured per person)
        if self._pub_cluster_cloud.get_subscription_count() > 0:
            self._publish_cluster_cloud(header, tracks, person_clusters)

    def _publish_cluster_cloud(self, header, tracks, person_clusters):
        points_data = bytearray()
        n_points = 0
        for i, cluster in enumerate(person_clusters):
            if i < len(tracks):
                color = _COLORS[tracks[i].person_id % len(_COLORS)]
            else:
                color = _COLORS[i % len(_COLORS)]
            r_byte = int(color[0] * 255)
            g_byte = int(color[1] * 255)
            b_byte = int(color[2] * 255)
            rgb_packed = struct.unpack('f', struct.pack('I',
                (255 << 24) | (r_byte << 16) | (g_byte << 8) | b_byte))[0]
            for pt in cluster:
                points_data.extend(struct.pack('ffff', pt[0], pt[1], 0.0, rgb_packed))
                n_points += 1

        cloud = PointCloud2()
        cloud.header = header
        cloud.height = 1
        cloud.width = n_points
        cloud.fields = [
            PointField(name='x', offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name='y', offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name='z', offset=8, datatype=PointField.FLOAT32, count=1),
            PointField(name='rgb', offset=12, datatype=PointField.FLOAT32, count=1),
        ]
        cloud.is_bigendian = False
        cloud.point_step = 16
        cloud.row_step = 16 * n_points
        cloud.data = bytes(points_data)
        cloud.is_dense = True
        self._pub_cluster_cloud.publish(cloud)


def main(args=None):
    rclpy.init(args=args)
    node = TrackerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
