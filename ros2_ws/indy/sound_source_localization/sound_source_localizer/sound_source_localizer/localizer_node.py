"""ROS2 node for SRP-PHAT sound source localisation."""

import math

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy, qos_profile_sensor_data

from builtin_interfaces.msg import Duration
from geometry_msgs.msg import Point, Vector3
from microphone_array.msg import AudioDataMultiChannel, MicrophoneArrayInfo
from ssl_msgs.msg import DOAEstimate, DOAEstimateArray
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray

from .srp_phat import SrpPhat

# Distinct colours for DOA markers (R, G, B)
_COLORS = [
    (1.0, 0.2, 0.2),
    (0.2, 1.0, 0.2),
    (0.2, 0.4, 1.0),
    (1.0, 0.8, 0.0),
    (1.0, 0.0, 1.0),
    (0.0, 1.0, 1.0),
    (1.0, 0.5, 0.0),
    (0.5, 0.0, 1.0),
]


class SoundSourceLocalizerNode(Node):
    """Subscribe to multi-channel audio and publish DOA estimates."""

    def __init__(self) -> None:
        super().__init__('sound_source_localizer')

        # Declare parameters
        self.declare_parameter('num_sources', 3)
        self.declare_parameter('search_resolution_deg', 5.0)
        self.declare_parameter('frequency_range', [300.0, 3500.0])
        # Minimum normalised SRP (0..1, 1 = all mic pairs perfectly coherent)
        # for a peak to be reported.  Silence -> no estimates.
        self.declare_parameter('power_threshold', 0.05)
        # Oversampling factor of the GCC inverse FFT (fractional-lag resolution)
        self.declare_parameter('interp_factor', 4)

        self.srp = None
        self._array_frame_id = 'microphone_array_base'

        # Publishers
        self.pub_doa = self.create_publisher(
            DOAEstimateArray, 'out_doa_estimates', 10
        )
        self._pub_viz_markers = self.create_publisher(
            MarkerArray, 'out_viz_doa_markers', 10
        )

        # Subscriber: latched array info (received once at startup)
        latched_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
        )
        self.sub_array_info = self.create_subscription(
            MicrophoneArrayInfo,
            'audio/array_info',
            self._array_info_callback,
            latched_qos,
        )

        # Subscriber: audio data
        self.sub_audio = self.create_subscription(
            AudioDataMultiChannel,
            'audio/multichannel',
            self._audio_callback,
            qos_profile_sensor_data,
        )

        self.get_logger().info(
            'SoundSourceLocalizer node started. Waiting for audio/array_info ...'
        )

    def _array_info_callback(self, msg: MicrophoneArrayInfo) -> None:
        """Initialize SRP-PHAT from received array geometry."""
        n = msg.num_channels
        mic_positions = np.array(msg.positions, dtype=np.float64).reshape(n, 3)
        self._array_frame_id = msg.header.frame_id
        self.get_logger().info(
            f'Received MicrophoneArrayInfo: {n} channels, frame_id={self._array_frame_id}'
        )

        freq_range_param = (
            self.get_parameter('frequency_range').get_parameter_value().double_array_value
        )
        self.srp = SrpPhat(
            mic_positions=mic_positions,
            num_sources=self.get_parameter('num_sources').get_parameter_value().integer_value,
            resolution_deg=self.get_parameter('search_resolution_deg').get_parameter_value().double_value,
            frequency_range=(freq_range_param[0], freq_range_param[1]),
            power_threshold=self.get_parameter('power_threshold').value,
            interp_factor=self.get_parameter('interp_factor').value,
        )
        self.get_logger().info('SRP-PHAT initialized.')

    def _audio_callback(self, msg: AudioDataMultiChannel) -> None:
        """Process incoming multi-channel audio block."""
        if self.srp is None:
            self.get_logger().warn(
                'Array info not yet received, skipping audio block',
                throttle_duration_sec=5.0,
            )
            return

        n_channels = msg.channels
        n_frames = msg.frames_per_block

        # Deinterleave int16 data into (C, N) float array (zero-copy view)
        raw = np.frombuffer(msg.data, dtype=np.int16)
        if len(raw) != n_channels * n_frames:
            self.get_logger().warn(
                f'Unexpected data length: {len(raw)} '
                f'(expected {n_channels * n_frames})'
            )
            return

        # Normalise to [-1, 1]
        channels = raw.reshape(n_frames, n_channels).T * (1.0 / 32768.0)

        # Update sample rate if changed
        if msg.sample_rate != self.srp.sample_rate:
            self.srp.sample_rate = msg.sample_rate
            self.srp._precompute_delays()

        # Run SRP-PHAT
        peaks = self.srp.locate(channels)

        # Publish results
        out = DOAEstimateArray()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = self._array_frame_id
        for az_rad, el_rad, power in peaks:
            est = DOAEstimate()
            # Normalize azimuth to [-pi, pi] to match tracker convention
            az_norm = float(az_rad)
            if az_norm > math.pi:
                az_norm -= 2.0 * math.pi
            est.azimuth = az_norm
            est.elevation = float(el_rad)
            est.power = float(power)
            out.estimates.append(est)

        self.pub_doa.publish(out)

        # Publish visualisation only when subscribers exist (lazy publishing)
        if self._pub_viz_markers.get_subscription_count() > 0:
            self._publish_viz_markers(out)

    # ------------------------------------------------------------------
    # Visualisation helpers
    # ------------------------------------------------------------------

    def _publish_viz_markers(self, doa_msg: DOAEstimateArray) -> None:
        """Build and publish MarkerArray for current DOA estimates."""
        marker_array = MarkerArray()
        marker_id = 0
        lifetime = Duration(sec=0, nanosec=500_000_000)

        for i, est in enumerate(doa_msg.estimates):
            color_rgb = _COLORS[i % len(_COLORS)]

            az = est.azimuth
            el = est.elevation
            power = est.power

            # Arrow length proportional to power (clamp to reasonable range)
            arrow_length = max(0.3, min(float(power) * 2.0, 5.0))

            # Direction unit vector from spherical (azimuth, elevation)
            dx = math.cos(el) * math.cos(az)
            dy = math.cos(el) * math.sin(az)
            dz = math.sin(el)

            tip_x = dx * arrow_length
            tip_y = dy * arrow_length
            tip_z = dz * arrow_length

            # ARROW marker (start -> end points)
            m = Marker()
            m.header = doa_msg.header
            m.ns = 'doa_arrow'
            m.id = marker_id
            marker_id += 1
            m.type = Marker.ARROW
            m.action = Marker.ADD
            m.points = [
                Point(x=0.0, y=0.0, z=0.0),
                Point(x=tip_x, y=tip_y, z=tip_z),
            ]
            # shaft diameter / head diameter / head length
            m.scale = Vector3(x=0.05, y=0.10, z=0.12)
            m.color = ColorRGBA(
                r=color_rgb[0], g=color_rgb[1], b=color_rgb[2], a=0.9
            )
            m.lifetime = lifetime
            marker_array.markers.append(m)

            # TEXT_VIEW_FACING showing azimuth in degrees near the arrow tip
            t = Marker()
            t.header = doa_msg.header
            t.ns = 'doa_label'
            t.id = marker_id
            marker_id += 1
            t.type = Marker.TEXT_VIEW_FACING
            t.action = Marker.ADD
            t.pose.position = Point(
                x=tip_x * 1.1, y=tip_y * 1.1, z=tip_z * 1.1 + 0.15
            )
            t.scale.z = 0.18  # text height
            t.color = ColorRGBA(
                r=color_rgb[0], g=color_rgb[1], b=color_rgb[2], a=1.0
            )
            t.text = f'{math.degrees(az):.0f}°'
            t.lifetime = lifetime
            marker_array.markers.append(t)

        self._pub_viz_markers.publish(marker_array)


def main(args=None):
    rclpy.init(args=args)
    node = SoundSourceLocalizerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
