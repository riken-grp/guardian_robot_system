"""ROS2 node for audio source separation using MVDR beamforming and VAD."""

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy, qos_profile_sensor_data

from microphone_array.msg import AudioDataMultiChannel, MicrophoneArrayInfo
from ssl_msgs.msg import DOAEstimateArray, TrackedPersonArray, SpeechSegment

from .beamformer import MVDRBeamformer
from .source_manager import SourceManager


class SeparatorNode(Node):
    """Audio source separator node.

    Subscribes to multi-channel audio, DOA estimates, and tracked persons.
    Associates persons with DOA directions, applies MVDR beamforming to
    extract per-person audio, runs VAD, and publishes speech segments.

    Extensibility: Additional subscribers (e.g., face orientation for
    improved speaker identification) can be added in _create_subscribers().
    """

    def __init__(self):
        super().__init__('separator_node')

        self._declare_parameters()
        self._init_components()
        self._create_subscribers()
        self._create_publishers()
        self._create_timers()

        self.get_logger().info(
            'SeparatorNode initialized. Waiting for audio/array_info ...'
        )

    def _declare_parameters(self):
        """Declare all ROS parameters."""
        # Beamforming
        self.declare_parameter('fft_size', 512)
        self.declare_parameter('speed_of_sound', 343.0)
        self.declare_parameter('diagonal_loading', 1e-4)
        self.declare_parameter('forget_factor', 0.9)

        # VAD
        self.declare_parameter('vad_threshold_db', -40.0)
        self.declare_parameter('vad_hangover_frames', 10)
        self.declare_parameter('vad_min_speech_frames', 3)

        # Segmentation
        self.declare_parameter('min_speech_duration', 0.3)
        self.declare_parameter('max_speech_duration', 10.0)

        # Association
        self.declare_parameter('association_angle_threshold', 0.35)
        self.declare_parameter('stale_association_timeout', 3.0)

        # Synchronisation: drop audio if DOA or person data is older than this (seconds)
        self.declare_parameter('max_sync_age', 0.5)

    def _init_components(self):
        """Initialize beamformer and source manager."""
        self._mic_positions = None
        self._n_mics = 0
        self._sample_rate = 0  # Set on first audio message
        self._beamformer = None  # Initialized on first audio message
        self._max_sync_age = self.get_parameter('max_sync_age').value

        self._source_manager = SourceManager(
            association_angle_threshold=self.get_parameter(
                'association_angle_threshold').value,
            stale_timeout=self.get_parameter(
                'stale_association_timeout').value,
            min_speech_duration=self.get_parameter(
                'min_speech_duration').value,
            max_speech_duration=self.get_parameter(
                'max_speech_duration').value,
            vad_threshold_db=self.get_parameter('vad_threshold_db').value,
            vad_hangover_frames=self.get_parameter('vad_hangover_frames').value,
            vad_min_speech_frames=self.get_parameter(
                'vad_min_speech_frames').value,
            time_func=lambda: self.get_clock().now().nanoseconds * 1e-9,
        )

        # Latest DOA and person data (manual sync)
        self._latest_doa = None
        self._latest_persons = None
        self._doa_recv_time = 0.0
        self._persons_recv_time = 0.0

    def _create_subscribers(self):
        """Create topic subscribers.

        Extensibility point: Add additional subscribers here, e.g.:
            self._face_orientation_sub = self.create_subscription(
                FaceOrientation, 'face_orientation',
                self._on_face_orientation, 10)
        """
        latched_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
        )
        self._array_info_sub = self.create_subscription(
            MicrophoneArrayInfo,
            'audio/array_info',
            self._on_array_info,
            latched_qos,
        )
        self._audio_sub = self.create_subscription(
            AudioDataMultiChannel,
            'audio/multichannel',
            self._on_audio,
            qos_profile_sensor_data,
        )
        self._doa_sub = self.create_subscription(
            DOAEstimateArray,
            'in_doa_estimates',
            self._on_doa,
            10,
        )
        self._persons_sub = self.create_subscription(
            TrackedPersonArray,
            'in_tracked_persons',
            self._on_tracked_persons,
            10,
        )

    def _create_publishers(self):
        """Create topic publishers."""
        self._segment_pub = self.create_publisher(
            SpeechSegment,
            'out_speech_segments',
            10,
        )

    def _create_timers(self):
        """Create periodic timers."""
        # Cleanup stale associations every 1 second
        self._cleanup_timer = self.create_timer(1.0, self._on_cleanup_timer)

    def _on_array_info(self, msg: MicrophoneArrayInfo) -> None:
        """Store microphone positions from array info topic."""
        n = msg.num_channels
        self._mic_positions = np.array(msg.positions, dtype=np.float64).reshape(n, 3)
        self._n_mics = n
        self._beamformer = None  # Reset beamformer so it re-initializes with new positions
        self.get_logger().info(f'Received MicrophoneArrayInfo: {n} channels')

    def _on_doa(self, msg: DOAEstimateArray):
        """Handle incoming DOA estimates."""
        if self._latest_doa is None:
            self.get_logger().info(
                f'First DOA message received: {len(msg.estimates)} estimates'
            )
        self._latest_doa = msg
        self._doa_recv_time = self.get_clock().now().nanoseconds * 1e-9

    def _on_tracked_persons(self, msg: TrackedPersonArray):
        """Handle incoming tracked person data."""
        if self._latest_persons is None:
            self.get_logger().info(
                f'First tracked persons message received: '
                f'{len(msg.persons)} persons'
            )
        self._latest_persons = msg
        self._persons_recv_time = self.get_clock().now().nanoseconds * 1e-9

    def _on_audio(self, msg: AudioDataMultiChannel):
        """Handle incoming multi-channel audio and run the separation pipeline."""
        if self._mic_positions is None:
            self.get_logger().warn(
                'Array info not yet received, skipping audio block',
                throttle_duration_sec=5.0,
            )
            return

        # Initialize beamformer on first message
        if self._beamformer is None:
            self._sample_rate = msg.sample_rate
            self._source_manager.sample_rate = self._sample_rate
            self._beamformer = MVDRBeamformer(
                mic_positions=self._mic_positions,
                sample_rate=self._sample_rate,
                fft_size=self.get_parameter('fft_size').value,
                speed_of_sound=self.get_parameter('speed_of_sound').value,
                diagonal_loading=self.get_parameter('diagonal_loading').value,
                forget_factor=self.get_parameter('forget_factor').value,
            )
            self.get_logger().info(
                f'Beamformer initialized: sample_rate={self._sample_rate}, '
                f'fft_size={self.get_parameter("fft_size").value}, '
                f'forget_factor={self.get_parameter("forget_factor").value}'
            )

        # Decode interleaved audio to (n_samples, n_channels)
        n_channels = msg.channels
        n_frames = msg.frames_per_block
        raw = np.array(msg.data, dtype=np.int16).reshape(n_frames, n_channels)
        audio_float = raw.astype(np.float64) / 32768.0

        # Compute timestamp in nanoseconds
        timestamp_ns = msg.stamp.sec * 1_000_000_000 + msg.stamp.nanosec
        audio_stamp_sec = msg.stamp.sec + msg.stamp.nanosec * 1e-9

        # Skip if no DOA or person data available
        if self._latest_doa is None or self._latest_persons is None:
            return

        # Drop audio block if DOA or person data hasn't been received recently
        now_sec = self.get_clock().now().nanoseconds * 1e-9
        doa_age = now_sec - self._doa_recv_time
        persons_age = now_sec - self._persons_recv_time
        if doa_age > self._max_sync_age:
            self.get_logger().warn(
                f'DOA data too stale, skipping audio block '
                f'(last received {doa_age:.3f}s ago)',
                throttle_duration_sec=2.0,
            )
            return
        if persons_age > self._max_sync_age:
            self.get_logger().warn(
                f'Person tracking data too stale, skipping audio block '
                f'(last received {persons_age:.3f}s ago)',
                throttle_duration_sec=2.0,
            )
            return

        # Extract DOA data
        doa_azimuths = [e.azimuth for e in self._latest_doa.estimates]
        doa_powers = [e.power for e in self._latest_doa.estimates]

        # Extract person data
        person_ids = [p.person_id for p in self._latest_persons.persons]
        person_azimuths = [p.azimuth for p in self._latest_persons.persons]
        person_distances = [p.distance for p in self._latest_persons.persons]

        if not person_ids or not doa_azimuths:
            self.get_logger().info(
                f'No data to process: persons={len(person_ids)}, '
                f'doa={len(doa_azimuths)}',
                throttle_duration_sec=5.0,
            )
            return

        # Associate persons with DOA estimates (one-to-one via Hungarian algorithm)
        associations = self._source_manager.associate_persons_with_doa(
            person_ids, person_azimuths, person_distances,
            doa_azimuths, doa_powers,
        )

        if not associations:
            return

        # For each associated person, beamform and run VAD
        for pid, target_azimuth in associations.items():
            beamformed = self._beamformer.apply_das(
                audio_float, target_azimuth
            )

            segments = self._source_manager.process_audio(
                pid, beamformed, timestamp_ns
            )

            for segment in segments:
                self._publish_segment(segment)

    def _publish_segment(self, segment):
        """Publish a completed speech segment."""
        msg = SpeechSegment()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.person_id = segment.person_id
        msg.azimuth = float(segment.azimuth)
        msg.distance = float(segment.distance)
        msg.sample_rate = segment.sample_rate
        msg.duration = float(len(segment.audio_data) / segment.sample_rate)
        msg.audio_data = segment.audio_data.astype(np.float32).tolist()
        msg.speech_start_ns = segment.speech_start_ns
        msg.speech_end_ns = segment.speech_end_ns

        self._segment_pub.publish(msg)
        self.get_logger().info(
            f'Published speech segment: person={segment.person_id}, '
            f'duration={msg.duration:.2f}s, azimuth={segment.azimuth:.2f}rad'
        )

    def _on_cleanup_timer(self):
        """Periodically clean up stale source associations."""
        segments = self._source_manager.cleanup_stale()
        for segment in segments:
            self._publish_segment(segment)


def main(args=None):
    rclpy.init(args=args)
    node = SeparatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
