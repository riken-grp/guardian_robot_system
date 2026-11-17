"""ROS2 側: ロボットのトピックの受信・送信と, Web 側への受け渡し"""
import asyncio
import json
import math
import struct
import threading
import time
from collections import OrderedDict, deque
from contextlib import contextmanager
from datetime import datetime

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped, Twist
from rclpy import qos
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import BatteryState, CompressedImage

try:
    # Indy ワークスペースのメッセージ (source <Indy>/install/setup.bash が必要)
    from ssl_msgs.msg import SpeechSegment
except ImportError:
    SpeechSegment = None
try:
    from ssl_msgs.msg import SpeakerFaceSegment
except ImportError:
    SpeakerFaceSegment = None
try:
    from common_msgs.msg import StringStamped
except ImportError:
    StringStamped = None

QOS_PROFILES = {
    "system_default": qos.qos_profile_system_default,
    "sensor_data": qos.qos_profile_sensor_data,
}

HEARD_TEXT_COUNT = 5  # 覚えておく聞き取った言葉の数
POSE_TIMEOUT = 10  # この秒数より古い位置は使わない
SPEECH_QUEUE_SIZE = 20  # クライアントごとに溜める発話の最大数 (超えたら古いものを捨てる)
SPEECH_CLIP_COUNT = 30  # 聞き取った言葉から再生できるよう覚えておく発話音声の数
SPEAKER_FACE_COUNT = 30  # 聞き取った言葉の横に出すため覚えておく発話者の顔画像の数
INDY_SOURCE_HINT = "Indy の install/setup.bash を source してください"


class Broadcaster:
    """ROSスレッドで受け取ったデータを, 接続中の全クライアント (asyncio) へ配る"""

    def __init__(self, queue_size):
        self._queue_size = queue_size
        self._loop = None
        self._queues = set()

    def start(self, loop):
        self._loop = loop

    @contextmanager
    def subscribe(self):
        queue = asyncio.Queue(maxsize=self._queue_size)
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)

    def publish(self, data):
        """ROSスレッドから呼ばれる"""
        if self._loop is None:
            return
        for queue in list(self._queues):
            self._loop.call_soon_threadsafe(self._put, queue, data)

    @staticmethod
    def _put(queue, data):
        if queue.full():  # 遅いクライアントの分は古いものから捨てる
            queue.get_nowait()
        queue.put_nowait(data)


class RobotState:
    """ROS2から受信した最新の状態 (ROSスレッドから書き込み, Webから読み出し)"""

    def __init__(self):
        self.jpeg = None  # 最新フレーム (JPEGバイト列)
        self.battery = 100
        self.is_charging = False
        self.pose = None  # (x, y, yaw, 受信時刻)
        self.heard = deque(maxlen=HEARD_TEXT_COUNT)  # 聞き取った言葉 (新しい順)
        self._clips = OrderedDict()  # 発話音声 ID -> (サンプリング周波数, float32 のバイト列)
        self._faces = OrderedDict()  # 発話音声 ID -> 発話者の顔画像 (JPEGバイト列)
        self._clips_lock = threading.Lock()
        self.frames = Broadcaster(queue_size=1)  # カメラ映像 (最新の1枚だけ送る)
        self.speech = Broadcaster(queue_size=SPEECH_QUEUE_SIZE)  # 発話音声

    def start(self, loop):
        self.frames.start(loop)
        self.speech.start(loop)

    def add_clip(self, clip_id, sample_rate, samples):
        """ROSスレッドから呼ばれる. 古いものから捨てる"""
        with self._clips_lock:
            self._clips[clip_id] = (sample_rate, samples)
            while len(self._clips) > SPEECH_CLIP_COUNT:
                self._clips.popitem(last=False)

    def clip(self, clip_id):
        with self._clips_lock:
            return self._clips.get(clip_id)

    def add_face(self, clip_id, jpeg):
        """ROSスレッドから呼ばれる. 古いものから捨てる"""
        with self._clips_lock:
            self._faces[clip_id] = jpeg
            while len(self._faces) > SPEAKER_FACE_COUNT:
                self._faces.popitem(last=False)

    def face(self, clip_id):
        with self._clips_lock:
            return self._faces.get(clip_id)

    def current_heard(self):
        """聞き取った言葉. 音声が残っているものには clip, 発話者の顔画像があるものには face (どちらも音声の ID) を付ける"""
        with self._clips_lock:
            return [
                {"time": item["time"], "text": item["text"],
                 "clip": item["clip"] if item["clip"] in self._clips else None,
                 "face": item["clip"] if item["clip"] in self._faces else None}
                for item in list(self.heard)
            ]

    def current_pose(self):
        if self.pose is None or time.monotonic() - self.pose[3] >= POSE_TIMEOUT:
            return None
        x, y, yaw, _ = self.pose
        return {"x": x, "y": y, "yaw": yaw}


def clip_id(person_id, speech_start_ns):
    """発話音声と, それを聞き取った結果を結びつける ID"""
    return f"{int(person_id)}-{int(speech_start_ns)}"


def to_jpeg(msg):
    """CompressedImage を JPEG バイト列にする. JPEGならそのまま返し, デコード/再エンコードを省く"""
    data = bytes(msg.data)
    fmt = msg.format.lower()
    if "jpeg" in fmt or "jpg" in fmt:
        return data
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return None
    ok, buffer = cv2.imencode(".jpg", frame)
    return buffer.tobytes() if ok else None


class RobotNode(Node):
    def __init__(self, robot_name, state, battery_qos):
        super().__init__("indyxe_viewer")
        self._state = state
        topic = f"/{robot_name}"
        default_qos = qos.qos_profile_system_default
        self.create_subscription(
            CompressedImage, f"{topic}/local_recog/color/image_raw/compressed", self._image_callback, default_qos)
        self.create_subscription(BatteryState, f"{topic}/rover/battery", self._battery_callback, battery_qos)
        self.create_subscription(PoseStamped, f"{topic}/rover/pose", self._pose_callback, 10)
        self._cmd_vel = self.create_publisher(Twist, f"{topic}/rover/cmd_vel", 10)
        if StringStamped is not None:
            self.create_subscription(
                StringStamped, f"{topic}/recog/ssl/asr/raw_text", self._asr_callback, default_qos)
        else:
            self.get_logger().warning(f"common_msgs が見つからないため聞き取った言葉の表示は無効です ({INDY_SOURCE_HINT})")
        if SpeechSegment is not None:
            self.create_subscription(
                SpeechSegment, f"{topic}/recog/ssl/identified_speech_segments", self._speech_callback, default_qos)
        else:
            self.get_logger().warning(f"ssl_msgs が見つからないため発話音声の再生は無効です ({INDY_SOURCE_HINT})")
        if SpeakerFaceSegment is not None:
            self.create_subscription(
                SpeakerFaceSegment, f"{topic}/recog/ssl/speaker_face_segments", self._face_callback, default_qos)
        else:
            self.get_logger().warning(f"ssl_msgs/SpeakerFaceSegment が見つからないため発話者の顔の表示は無効です ({INDY_SOURCE_HINT})")

    def _image_callback(self, msg):
        data = to_jpeg(msg)
        if data is None:
            return
        self._state.jpeg = data
        self._state.frames.publish(data)

    def _speech_callback(self, msg):
        # ヘッダ (サンプリング周波数 uint32, 人物ID int32) + float32 リトルエンディアンのサンプル列
        header = struct.pack("<Ii", msg.sample_rate, msg.person_id)
        samples = np.asarray(msg.audio_data, dtype="<f4").tobytes()
        self._state.speech.publish(header + samples)
        self._state.add_clip(clip_id(msg.person_id, msg.speech_start_ns), msg.sample_rate, samples)

    def _face_callback(self, msg):
        if not msg.face_found or not msg.face_image.data:
            return
        jpeg = to_jpeg(msg.face_image)
        if jpeg is not None:
            self._state.add_face(clip_id(msg.segment.person_id, msg.segment.speech_start_ns), jpeg)

    def _pose_callback(self, msg):
        q = msg.pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        self._state.pose = (msg.pose.position.x, msg.pose.position.y, yaw, time.monotonic())

    def _asr_callback(self, msg):
        # ssl_asr は JSON ({person_id, text, speech_start_ns, ...}) を送る. ただの文字列にも対応する
        data = msg.data.strip()
        clip = None
        try:
            result = json.loads(data)
        except ValueError:
            result = None
        if isinstance(result, dict):
            data = str(result.get("text", "")).strip()
            if "person_id" in result and "speech_start_ns" in result:
                clip = clip_id(result["person_id"], result["speech_start_ns"])
        if data:
            self._state.heard.appendleft(
                {"time": datetime.now().strftime("%H:%M:%S"), "text": data, "clip": clip})

    def _battery_callback(self, msg):
        self._state.battery = msg.percentage
        self._state.is_charging = msg.current < 0.01

    def publish_velocity(self, linear, angular):
        twist = Twist()
        twist.linear.x = linear
        twist.angular.z = angular
        self._cmd_vel.publish(twist)


@contextmanager
def run_ros(robot_name, state, battery_qos, domain_id):
    """ROS2ノードを別スレッドで動かし, ブロックを抜けたら止める"""
    rclpy.init(domain_id=domain_id)
    node = RobotNode(robot_name, state, battery_qos)
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def spin():
        try:
            executor.spin()
        except ExternalShutdownException:
            pass  # Ctrl+C などで rclpy が先にシャットダウンした

    threading.Thread(target=spin, daemon=True).start()
    try:
        yield node
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()
