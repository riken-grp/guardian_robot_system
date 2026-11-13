"""ROS2 node for audio source separation using delay-and-sum beamforming and VAD."""

import array
import math

import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy, qos_profile_sensor_data
from rclpy.time import Time

from microphone_array.msg import AudioDataMultiChannel, MicrophoneArrayInfo
from ssl_msgs.msg import DOAEstimateArray, TrackedPersonArray, SpeechSegment

from .beamformer import MVDRBeamformer
from .source_manager import SourceManager
from .tf_utils import transform_points

try:
    from tf2_ros import Buffer, TransformListener
except ImportError:  # pragma: no cover - tf2_ros is part of ROS 2 desktop
    Buffer = None
    TransformListener = None


class SeparatorNode(Node):
    """Audio source separator node.

    Subscribes to multi-channel audio, DOA estimates, and tracked persons.
    Associates persons with DOA directions, applies delay-and-sum
    beamforming toward each distinct direction (once per direction) to
    extract per-person audio, runs VAD, and publishes speech segments.

    LiDAR person positions (TrackedPersonArray, scan frame) are transformed
    into the microphone-array frame with tf2 before they are compared with
    the DOA azimuths (array frame).

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
        # Blocks kept before the VAD onset and prepended to the segment
        self.declare_parameter('vad_preroll_frames', 5)

        # Segmentation
        self.declare_parameter('min_speech_duration', 0.3)
        self.declare_parameter('max_speech_duration', 10.0)

        # Association
        self.declare_parameter('association_angle_threshold', 0.35)
        self.declare_parameter('stale_association_timeout', 3.0)

        # Synchronisation: do not (re-)associate when DOA or person data is
        # older than this (seconds).  Persons already inside an utterance
        # keep being processed with their last known direction.
        self.declare_parameter('max_sync_age', 0.5)

        # Frames: DOA azimuths are in the microphone-array frame.  Empty
        # 'array_frame' = use the frame_id of audio/array_info (or of the DOA
        # message).  Empty 'persons_frame' = use the TrackedPersonArray
        # header frame_id.
        self.declare_parameter('array_frame', '')
        self.declare_parameter('persons_frame', '')
        self.declare_parameter('use_tf', True)

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
            vad_preroll_frames=self.get_parameter('vad_preroll_frames').value,
        )
        self._assoc_threshold = self.get_parameter(
            'association_angle_threshold').value

        # Latest DOA and person data (manual sync)
        self._latest_doa = None
        self._latest_persons = None
        self._doa_recv_time = 0.0
        self._persons_recv_time = 0.0
        # Persons converted to the array frame: (ids, azimuths, distances)
        self._persons_in_array = ([], [], [])

        self._array_frame = self.get_parameter('array_frame').value
        self._array_info_frame = ''
        self._persons_frame_param = self.get_parameter('persons_frame').value
        self._tf_buffer = None
        self._tf_listener = None
        if self.get_parameter('use_tf').value:
            if Buffer is None:
                self.get_logger().warn(
                    'tf2_ros not available; LiDAR azimuths are used without '
                    'frame transformation')
            else:
                self._tf_buffer = Buffer()
                self._tf_listener = TransformListener(self._tf_buffer, self)

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
        self._array_info_frame = msg.header.frame_id
        self.get_logger().info(
            f'Received MicrophoneArrayInfo: {n} channels, '
            f'frame_id={msg.header.frame_id}')

    def _target_frame(self) -> str:
        """Frame in which DOA azimuths are expressed."""
        if self._array_frame:
            return self._array_frame
        if self._latest_doa is not None and self._latest_doa.header.frame_id:
            return self._latest_doa.header.frame_id
        return self._array_info_frame

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
        self._persons_in_array = self._persons_to_array_frame(msg)

    def _persons_to_array_frame(self, msg: TrackedPersonArray):
        """Return (ids, azimuths, distances) of persons in the array frame.

        Falls back to the raw (scan-frame) azimuth/distance with a throttled
        warning when the transform is unavailable.
        """
        ids = [p.person_id for p in msg.persons]
        raw_az = [p.azimuth for p in msg.persons]
        raw_dist = [p.distance for p in msg.persons]
        if not ids or self._tf_buffer is None:
            return ids, raw_az, raw_dist

        source = self._persons_frame_param or msg.header.frame_id
        target = self._target_frame()
        if not source or not target or source == target:
            return ids, raw_az, raw_dist
        try:
            tf = self._tf_buffer.lookup_transform(
                target, source, Time(), timeout=Duration(seconds=0.0))
        except Exception as e:  # noqa: BLE001 (tf2 raises several types)
            self.get_logger().warn(
                f'TF {source} -> {target} unavailable ({e}); using LiDAR '
                f'azimuths without transformation',
                throttle_duration_sec=5.0,
            )
            return ids, raw_az, raw_dist

        pts = np.array([[p.x, p.y, 0.0] for p in msg.persons])
        pts = transform_points(tf, pts)
        az = np.arctan2(pts[:, 1], pts[:, 0])
        dist = np.hypot(pts[:, 0], pts[:, 1])
        return ids, az.tolist(), dist.tolist()

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

        n_channels = msg.channels
        n_frames = msg.frames_per_block
        if len(msg.data) != n_channels * n_frames or n_channels != self._n_mics:
            self.get_logger().warn(
                f'Unexpected audio layout: {len(msg.data)} samples, '
                f'{n_channels} ch x {n_frames} frames (array has '
                f'{self._n_mics} mics); skipping block',
                throttle_duration_sec=5.0,
            )
            return
        # Zero-copy (n_frames, n_channels) int16 view; converted to float
        # only when this block is actually beamformed.
        raw = np.frombuffer(msg.data, dtype=np.int16).reshape(n_frames, n_channels)

        # Timestamp (ns) of the first sample of this block
        timestamp_ns = msg.stamp.sec * 1_000_000_000 + msg.stamp.nanosec

        # ---- (Re-)association, only with fresh DOA / person data ----
        associations: dict[int, float] = {}
        now_sec = self.get_clock().now().nanoseconds * 1e-9
        if self._latest_doa is not None and self._latest_persons is not None:
            doa_age = now_sec - self._doa_recv_time
            persons_age = now_sec - self._persons_recv_time
            if doa_age > self._max_sync_age:
                self.get_logger().warn(
                    f'DOA data too stale, not associating '
                    f'(last received {doa_age:.3f}s ago)',
                    throttle_duration_sec=2.0,
                )
            elif persons_age > self._max_sync_age:
                self.get_logger().warn(
                    f'Person tracking data too stale, not associating '
                    f'(last received {persons_age:.3f}s ago)',
                    throttle_duration_sec=2.0,
                )
            else:
                person_ids, person_azimuths, person_distances = \
                    self._persons_in_array
                doa_azimuths = [e.azimuth for e in self._latest_doa.estimates]
                doa_powers = [e.power for e in self._latest_doa.estimates]
                if person_ids and doa_azimuths:
                    # One-to-one (Hungarian) association: each DOA peak is
                    # assigned to at most one person per block.
                    associations = self._source_manager.associate_persons_with_doa(
                        person_ids, person_azimuths, person_distances,
                        doa_azimuths, doa_powers,
                    )

        # ---- Persons inside an ongoing utterance without fresh association
        # keep being processed with their last known direction, so the audio
        # of the utterance stays contiguous. ----
        continuing = {
            pid: az for pid, az in self._source_manager.speaking_sources().items()
            if pid not in associations
        }

        if not associations and not continuing:
            # Keep the beamformer history contiguous (only the tail is used)
            ctx = self._beamformer.das_context_samples
            self._beamformer.push_context(
                raw[-ctx:].astype(np.float32) * (1.0 / 32768.0))
            return

        # ---- One beam per distinct direction ----
        directions: list[float] = []
        person_beam: dict[int, int | None] = {}
        for pid, az in associations.items():
            person_beam[pid] = self._direction_index(directions, az, 1e-3)
        for pid, az in continuing.items():
            # Direction already taken by another person: do not emit the same
            # audio twice -> feed silence (the VAD then closes the utterance
            # after its hangover, keeping the timing consistent).
            if any(self._angle_diff(az, d) <= self._assoc_threshold
                   for d in directions):
                person_beam[pid] = None
            else:
                person_beam[pid] = self._direction_index(directions, az, 1e-3)

        audio_float = raw.astype(np.float32) * (1.0 / 32768.0)
        beams = self._beamformer.apply_das_multi(audio_float, directions)
        silence = None

        for pid, idx in person_beam.items():
            if idx is None:
                if silence is None:
                    silence = np.zeros(n_frames, dtype=np.float32)
                block = silence
            else:
                block = beams[idx]
            segments = self._source_manager.process_audio(
                pid, block, timestamp_ns
            )
            for segment in segments:
                self._publish_segment(segment)

    @staticmethod
    def _angle_diff(a: float, b: float) -> float:
        return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)

    def _direction_index(self, directions: list, az: float, tol: float) -> int:
        """Index of ``az`` in ``directions`` (appended when new)."""
        for i, d in enumerate(directions):
            if self._angle_diff(az, d) <= tol:
                return i
        directions.append(float(az))
        return len(directions) - 1

    def _publish_segment(self, segment):
        """Publish a completed speech segment."""
        msg = SpeechSegment()
        msg.header.stamp = self.get_clock().now().to_msg()
        # azimuth / distance are expressed in the microphone-array frame
        msg.header.frame_id = self._target_frame()
        msg.person_id = segment.person_id
        msg.azimuth = float(segment.azimuth)
        msg.distance = float(segment.distance)
        msg.sample_rate = segment.sample_rate
        msg.duration = float(len(segment.audio_data) / segment.sample_rate)
        msg.audio_data = array.array(
            'f', np.ascontiguousarray(segment.audio_data, dtype=np.float32).tobytes())
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
