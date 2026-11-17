"""ROS2 node that attaches the speaker's face image to each separated speech segment.

Inputs:
  - ``in_speech_segments`` (ssl_msgs/SpeechSegment): separated speech
    (``person_id`` is the camera ``instance_id`` when the speaker was a camera
    person, e.g. camera_person_adapter_node in camera mode)
  - ``in_faces`` (recognition_msgs/Persons): faces with ``instance_id`` and
    ``face_location`` [x, y, w, h] in the camera image
    (association_node: ``recog/person/face/associated``).  The header is the
    one of the camera image the faces were detected in.
  - ``in_image`` (sensor_msgs/CompressedImage): the camera color image.

Output:
  - ``out_speaker_faces`` (ssl_msgs/SpeakerFaceSegment): the segment, and
    the best face of ``person_id`` during the utterance (largest and most
    frontal), cropped from the camera frame it was detected in.
    ``face_found`` is false when no such face was seen.

The faces come from the recognition PC and arrive some 0.4 s after the
images.  To avoid keeping seconds of full images, every face (with an
instance_id) is cropped and JPEG-encoded as soon as it arrives, and only the
crops are kept.  A segment is published once faces newer than its end have
arrived, or after ``max_wait`` seconds.
"""

from __future__ import annotations

import bisect
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from recognition_msgs.msg import Persons
from sensor_msgs.msg import CompressedImage
from ssl_msgs.msg import SpeakerFaceSegment, SpeechSegment

try:
    import cv2
except ImportError:  # pragma: no cover - python3-opencv is an exec_depend
    cv2 = None


def stamp_ns(stamp) -> int:
    return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)


def face_score(location, orientation) -> float:
    """Larger and more frontal faces score higher.

    ``location`` is [x, y, w, h]; ``orientation`` is [yaw, pitch, roll] in
    degrees (may be empty: then only the size counts, at half weight).
    """
    if len(location) < 4 or location[2] <= 0 or location[3] <= 0:
        return 0.0
    area = float(location[2]) * float(location[3])
    if len(orientation) >= 2:
        off = abs(float(orientation[0])) + abs(float(orientation[1]))
        frontal = max(0.1, 1.0 - off / 90.0)
    else:
        frontal = 0.5
    return area * frontal


def crop_box(location, width: int, height: int, margin: float):
    """Face box [x, y, w, h] enlarged by ``margin`` (fraction of the size on
    each side) and clipped to the image; (x0, y0, x1, y1) or None if empty."""
    if len(location) < 4:
        return None
    x, y, w, h = (float(v) for v in location[:4])
    if w <= 0 or h <= 0:
        return None
    x0 = int(max(0, round(x - margin * w)))
    y0 = int(max(0, round(y - margin * h)))
    x1 = int(min(width, round(x + w + margin * w)))
    y1 = int(min(height, round(y + h + margin * h)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, x1, y1


@dataclass
class FaceCrop:
    stamp_ns: int
    instance_id: int
    location: list
    orientation: list
    score: float
    jpeg: bytes
    image_header: object


@dataclass
class _Pending:
    msg: SpeechSegment
    arrival: float          # time.monotonic()


class SpeakerFaceNode(Node):
    """Publish speech segments together with the speaker's face image."""

    def __init__(self) -> None:
        super().__init__('speaker_face_node')

        # Camera images kept to crop the (late) faces from [s]
        self.declare_parameter('image_buffer_sec', 3.0)
        # Face crops kept [s] (> max_speech_duration + delays)
        self.declare_parameter('face_buffer_sec', 15.0)
        # Max |face stamp - image stamp| for the face to be cropped from the image [s]
        self.declare_parameter('image_stamp_tolerance', 0.005)
        # Faces searched in [speech_start - pre_margin, speech_end + post_margin]
        self.declare_parameter('pre_margin', 0.3)
        self.declare_parameter('post_margin', 0.2)
        # Publish without waiting longer than this for the faces [s]
        self.declare_parameter('max_wait', 2.0)
        # Crop: margin around the face box (fraction of the face size per side)
        self.declare_parameter('crop_margin', 0.4)
        self.declare_parameter('min_face_size', 16)     # px (w and h)
        self.declare_parameter('jpeg_quality', 90)

        p = self.get_parameter
        self._image_buf_ns = int(p('image_buffer_sec').value * 1e9)
        self._face_buf_ns = int(p('face_buffer_sec').value * 1e9)
        self._tol_ns = int(p('image_stamp_tolerance').value * 1e9)
        self._pre_ns = int(p('pre_margin').value * 1e9)
        self._post_ns = int(p('post_margin').value * 1e9)
        self._max_wait = float(p('max_wait').value)
        self._margin = float(p('crop_margin').value)
        self._min_size = float(p('min_face_size').value)
        self._quality = int(p('jpeg_quality').value)

        # images sorted by stamp: parallel lists for bisect
        self._img_stamps: list[int] = []
        self._imgs: list[CompressedImage] = []
        self._faces: deque[FaceCrop] = deque()
        self._latest_face_ns: int | None = None
        self._pending: list[_Pending] = []

        if cv2 is None:
            self.get_logger().error('OpenCV (cv2) not available: no face images')

        self.create_subscription(
            CompressedImage, 'in_image', self._on_image, qos_profile_sensor_data)
        self.create_subscription(Persons, 'in_faces', self._on_faces, 10)
        self.create_subscription(
            SpeechSegment, 'in_speech_segments', self._on_speech, 10)
        self._pub = self.create_publisher(
            SpeakerFaceSegment, 'out_speaker_faces', 10)
        self.create_timer(0.1, self._on_timer)

        self.get_logger().info('SpeakerFaceNode started')

    # ---- inputs ----
    def _on_image(self, msg: CompressedImage) -> None:
        t = stamp_ns(msg.header.stamp)
        i = bisect.bisect_right(self._img_stamps, t)
        self._img_stamps.insert(i, t)
        self._imgs.insert(i, msg)
        cutoff = self._img_stamps[-1] - self._image_buf_ns
        k = bisect.bisect_left(self._img_stamps, cutoff)
        if k:
            del self._img_stamps[:k]
            del self._imgs[:k]

    def _find_image(self, t: int) -> CompressedImage | None:
        i = bisect.bisect_left(self._img_stamps, t)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(self._img_stamps):
                d = abs(self._img_stamps[j] - t)
                if d <= self._tol_ns and (best is None or d < best[0]):
                    best = (d, j)
        return self._imgs[best[1]] if best is not None else None

    def _on_faces(self, msg: Persons) -> None:
        t = stamp_ns(msg.header.stamp)
        self._latest_face_ns = t if self._latest_face_ns is None else max(
            self._latest_face_ns, t)
        faces = [f for f in msg.persons
                 if f.instance_id >= 0 and len(f.face_location) >= 4
                 and f.face_location[2] >= self._min_size
                 and f.face_location[3] >= self._min_size]
        if faces and cv2 is not None:
            img_msg = self._find_image(t)
            img = None
            if img_msg is not None:
                img = cv2.imdecode(np.frombuffer(bytes(img_msg.data), np.uint8),
                                   cv2.IMREAD_COLOR)
            if img is None:
                self.get_logger().debug(
                    'No camera image for the faces', throttle_duration_sec=10.0)
            else:
                h, w = img.shape[:2]
                for f in faces:
                    box = crop_box(list(f.face_location), w, h, self._margin)
                    if box is None:
                        continue
                    x0, y0, x1, y1 = box
                    ok, buf = cv2.imencode(
                        '.jpg', img[y0:y1, x0:x1],
                        [int(cv2.IMWRITE_JPEG_QUALITY), self._quality])
                    if not ok:
                        continue
                    self._faces.append(FaceCrop(
                        stamp_ns=t, instance_id=int(f.instance_id),
                        location=[float(v) for v in f.face_location[:4]],
                        orientation=[float(v) for v in f.face_orientation],
                        score=face_score(f.face_location, f.face_orientation),
                        jpeg=buf.tobytes(), image_header=img_msg.header))
        cutoff = self._latest_face_ns - self._face_buf_ns
        while self._faces and self._faces[0].stamp_ns < cutoff:
            self._faces.popleft()

    def _on_speech(self, msg: SpeechSegment) -> None:
        self._pending.append(_Pending(msg, time.monotonic()))

    # ---- output ----
    def _on_timer(self) -> None:
        now = time.monotonic()
        keep = []
        for p in self._pending:
            complete = (self._latest_face_ns is not None
                        and self._latest_face_ns >= p.msg.speech_end_ns + self._post_ns)
            if complete or now - p.arrival >= self._max_wait:
                self._publish(p.msg)
            else:
                keep.append(p)
        self._pending = keep

    def best_face(self, seg: SpeechSegment) -> FaceCrop | None:
        t0 = seg.speech_start_ns - self._pre_ns
        t1 = seg.speech_end_ns + self._post_ns
        best = None
        for f in self._faces:
            if (f.instance_id == seg.person_id and t0 <= f.stamp_ns <= t1
                    and (best is None or f.score > best.score)):
                best = f
        return best

    def _publish(self, seg: SpeechSegment) -> None:
        out = SpeakerFaceSegment()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = seg.header.frame_id
        out.segment = seg
        face = self.best_face(seg)
        if face is not None:
            out.face_found = True
            out.face_image.header = face.image_header
            out.face_image.format = 'jpeg'
            out.face_image.data = face.jpeg
            out.face_location = face.location
            out.face_orientation = face.orientation
            out.face_stamp_ns = face.stamp_ns
        self._pub.publish(out)
        self.get_logger().info(
            f'Speaker face: person={seg.person_id}, duration={seg.duration:.2f}s, '
            + (f'face at {(face.stamp_ns - seg.speech_start_ns) / 1e9:+.2f}s '
               f'(size {face.location[2]:.0f}x{face.location[3]:.0f})'
               if face is not None else 'no face'))


def main(args=None):
    rclpy.init(args=args)
    node = SpeakerFaceNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
