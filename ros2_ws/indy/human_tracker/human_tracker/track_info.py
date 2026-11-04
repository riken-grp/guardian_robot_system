import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, NamedTuple, Optional

import numpy as np

# sep_id / class_id / instance_id などが無効であることを示す値
INVALID_VALUE = -10000

# MongoDBからaudio_portを取得できなかった場合のAudioTracker向けTCPポート
DEFAULT_AUDIO_PORT = 7004


class ViewText(str, Enum):
    """RViz上で人物マーカーに表示するテキストの種類"""
    NAME = "name"
    HUMAN_ID = "human_id"
    SEP_ID = "sep_id"
    DEBUG = "debug"


class MarkerColor(Enum):
    """マーカー色 (r, g, b, a)"""
    AUDIO_ON = (1.0, 0.0, 0.0, 1.0)       # 発話中
    LIDAR_ONLY = (0.0, 0.7, 1.0, 1.0)     # カメラ情報なし
    FUSED = (1.0, 1.0, 0.0, 1.0)          # LiDAR + カメラ
    CAMERA_ONLY = (0.0, 1.0, 0.0, 1.0)    # LiDAR情報なし
    TEXT = (1.0, 1.0, 1.0, 1.0)
    TRANSPARENT = (0.0, 0.0, 0.0, 0.0)

    def apply(self, marker):
        marker.color.r, marker.color.g, marker.color.b, marker.color.a = self.value


@dataclass
class TrackInfo:
    """LiDAR/カメラで追跡中の物体(人物候補)1つ分の情報"""
    last_theta: float                         # 最後に観測した角度[rad]
    last_range: float                         # 最後に観測した距離[m]
    last_time: float                          # 最後に観測した時刻[s]
    human_cnt: List[int] = field(default_factory=list)  # 人判定履歴(1:人, 0:人以外)
    human_rate: Optional[float] = None        # human_cntから求めた人らしさ
    human_time: Optional[float] = None        # 最後に人判定を更新した時刻[s]
    last_human: bool = False                  # 直前のスキャンで人と判定されたか
    trace_human: bool = False                 # 人として確定済みか
    with_accessory: bool = False
    obj_flg: bool = False                     # 現在のスキャンでLiDAR点群と対応しているか
    object_id: Optional[int] = None           # 現在のスキャンでの点群クラスタ番号
    obj_pose: Optional[list] = None           # [中心, 始点エッジ, 終点エッジ] の [x, y]
    edge_theta: Optional[list] = None         # [始点角度, 終点角度]
    human_pose: Optional[list] = None         # 人物位置 [x, y, z][mm]
    human_vel: Optional[list] = None          # 人物速度 [vx, vy] (human_leg_trackerのみ)
    sep_id: Optional[int] = None
    topic_id: float = np.nan                  # 対応するカメラ認識ID(未対応時はnan)
    topic_flg: bool = False                   # カメラ認識と対応付いているか
    current_topic_flg: bool = False           # 現在のスキャンでカメラ認識と対応付いたか
    last_topic_time: Optional[float] = None   # 最後にカメラ認識と対応付いた時刻[s]
    non_human_flg: bool = False               # カメラ視野内なのに認識されない物体か
    face_angle: Optional[float] = None
    human_rpy: list = field(default_factory=list)

    def has_topic_id(self):
        return not math.isnan(self.topic_id)


@dataclass
class PersonRecogInfo:
    """カメラで認識した人物1人分の情報"""
    stamp_time: Optional[float] = None    # 認識結果のタイムスタンプ[s]
    recv_time: Optional[float] = None     # 認識結果を受信した時刻[s]
    pose: Optional[list] = None           # LiDAR座標系での位置 [x, y, z][m]
    theta: Optional[float] = None         # LiDAR座標系での角度[rad]
    distance: Optional[float] = None      # LiDAR座標系での距離[m]
    rpy: Optional[list] = None            # ロボット座標系での顔向き
    face_angle: Optional[float] = None
    name: Optional[str] = None
    class_id: Optional[int] = None
    human_id: Optional[int] = None        # 対応付いたTrackInfoのID


class ObjectPoint(NamedTuple):
    x: float
    y: float
    theta: float


class QueuedObject(NamedTuple):
    """object_queueに保持するスキャン毎の物体情報"""
    human_id: int
    mid: ObjectPoint
    min_edge: ObjectPoint
    max_edge: ObjectPoint

    def points(self):
        return (self.mid, self.min_edge, self.max_edge)


@dataclass
class TrackingInfo:
    """human_tracker_integrationで追跡中の人物1人分の情報"""
    pose: Any
    last_detect_time: float
    instance_id: int
    class_id: int
    name: str
    sep_id: Optional[int] = None


class LidarPerson(NamedTuple):
    """左右LiDARそれぞれのtracker結果"""
    person: Any        # PersonAllInfo
    angle: float       # LiDAR正面からの角度[rad]


class IntegratedPerson(NamedTuple):
    """左右LiDARの結果を統合した人物情報"""
    right_id: int
    left_id: int
    person: Any        # PersonAllInfo
    primary_idx: int   # 0:右, 1:左


def parse_view_text(text, logger):
    try:
        return ViewText(text)
    except ValueError:
        logger.warn('Viewer text:"%s" is not defined.' % text)
        return ViewText.NAME


def build_tcp_record(sec, msec, human_id, pose, sep_id, class_id, instance_id, name):
    """AudioTracker向けTCP送信データ1行分を作成する"""
    z_pose = INVALID_VALUE if pose[2] == 0.0 else pose[2]
    fields = [
        math.floor(sec), round(msec),
        0, 0, 0,
        human_id,
        0,
        round(pose[0]), round(pose[1]), round(z_pose),
        INVALID_VALUE, INVALID_VALUE, INVALID_VALUE, INVALID_VALUE,
        sep_id, class_id, instance_id,
    ]
    return ",".join(str(f) for f in fields) + "," + name + "\n"
