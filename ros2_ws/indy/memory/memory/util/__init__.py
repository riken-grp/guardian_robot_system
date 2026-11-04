from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from . import memory_func, memory_query, episode_tracker
from .settings import (
    ROBOT_NAME,
    ForgettingSettings,
    MemoryLevel,
    get_default_params
)
from .alt_param_manager import ParamManager

__all__ = [
    "memory_query",
    "memory_func",
    "ROBOT_NAME",
    "ForgettingSettings",
    "MemoryLevel",
    "get_default_params",
    "episode_tracker",
    "ParamManager"
]

import math
from collections import OrderedDict
from enum import Enum
from typing import Any, Dict, Generator, List, Mapping, MutableMapping, Tuple

import numpy as np
from rcl_interfaces.msg import ParameterDescriptor, ParameterType
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo
from std_msgs.msg import Header


class LimitedDict(MutableMapping):
    def __init__(self, max_size=100, default_value: Any = 0):
        self.max_size = max_size
        self.default_value = default_value
        self.data = OrderedDict()

    def update(self, *args, **kwargs):
        updates = {}
        if len(args) == 1 and isinstance(args[0], Mapping):
            updates.update(args[0])
        updates.update(kwargs)

        for key, value in updates.items():
            if key in self.data:
                # 既存のキーを更新して最後に移動
                self.data.move_to_end(key)
            self.data[key] = value
            if len(self.data) > self.max_size:
                # 最も古いキーを削除
                self.data.popitem(last=False)

    def get(self, key):
        return self.data.get(key, self.default_value)

    def __repr__(self):
        return str(self.data)

    def __str__(self):
        elems = (f"({k}, {v})" for k, v in self.data.items())
        return f"{{{', '.join(elems)}}}"

    def __len__(self):
        return len(self.data)

    def __getitem__(self, key: Any) -> Any:
        return self.data.get(key, self.default_value)

    def __setitem__(self, key: Any, val: Any) -> None:
        self.update({key: val})

    def __delitem__(self, key: Any) -> None:
        del self.data[key]

    def __iter__(self) -> Generator[Tuple[Any, Any], None, None]:
        for k, v in self.data.items():
            yield k, v


class ParamDesc(Enum):
    """Enumerator for ROS's Parameter Descriptors.
    Used to declare and retrieve parameters."""

    String = ParameterDescriptor(type=ParameterType.PARAMETER_STRING)
    Float = ParameterDescriptor(type=ParameterType.PARAMETER_DOUBLE)
    Bool = ParameterDescriptor(type=ParameterType.PARAMETER_BOOL)
    Int = ParameterDescriptor(type=ParameterType.PARAMETER_INTEGER)
    IntArray = ParameterDescriptor(type=ParameterType.PARAMETER_INTEGER_ARRAY)
    DblArray = ParameterDescriptor(type=ParameterType.PARAMETER_DOUBLE_ARRAY)


def get_ros_param(node: Node, name: str, type_: ParamDesc) -> Any:
    """Convenience method to retrieve a ROS parameter.
    It's shorter than the full syntax"""
    ns = node.get_namespace()
    p_value = node.get_parameter(
        f"{ns}.{name}" if ns else name
    ).get_parameter_value()

    if type_ == ParamDesc.String:
        return p_value.string_value
    elif type_ == ParamDesc.Float:
        return p_value.double_value
    elif type_ == ParamDesc.Bool:
        return p_value.bool_value
    elif type_ == ParamDesc.Int:
        return p_value.integer_value
    elif type_ == ParamDesc.IntArray:
        return p_value.integer_array_value
    elif type_ == ParamDesc.DblArray:
        return p_value.double_array_value
    else:
        raise TypeError("Unknown/Unsupported ROS Param Type")


def get_current_ts(n: Node) -> float:
    return n.get_clock().now().nanoseconds * 1e-9


def get_time_from_header(h: Header) -> float:
    return Time.from_msg(h.stamp).nanoseconds * 1e-9


def corner_est(dist: float, xywh: List[float], cinfo: CameraInfo):
    """Estimation of an Visual Bounding Box to Real World Coordinates"""
    xy = [
        [xywh[0], xywh[1]],
        [xywh[0] + xywh[2], xywh[1]],
        [xywh[0] + xywh[2], xywh[1] + xywh[3]],
        [xywh[0], xywh[1] + xywh[3]],
    ]
    xy = np.array(xy, dtype=float)

    real_scale = dist * (
        (xy - np.array([cinfo.k[2], cinfo.k[5]]))
        / np.array([cinfo.k[0], cinfo.k[4]])
    )

    return real_scale


def box_est(
    rob_loc: List[float],
    target_centroid: List[float],
    xywh: List[float],
    cinfo: CameraInfo,
):
    """Estimation of an 3D Interval Box to Real World Coordinates (WIP)"""
    dist = math.dist(rob_loc[:2], target_centroid[:2])
    angle = math.atan2(
        target_centroid[1] - rob_loc[1], target_centroid[0] - rob_loc[0]
    )

    # Compute the RL size
    xy = [
        [xywh[0], xywh[1]],
        [xywh[0] + xywh[2], xywh[1]],
        [xywh[0] + xywh[2], xywh[1] + xywh[3]],
        [xywh[0], xywh[1] + xywh[3]],
    ]
    xy = np.array(xy, dtype=float)

    xy = dist * (
        (xy - np.array([cinfo.k[2], cinfo.k[5]]))
        / np.array([cinfo.k[0], cinfo.k[4]])
    )

    # Proportional width and height est
    prop_wh = (xy[1] - xy[0]) + (xy[2] - xy[1])

    # To compute the xy points:

    # Perpendicular angle
    perp_ang = -1 / angle if angle != 0 else math.pi / 2

    if perp_ang > math.pi / 2:
        perp_ang = perp_ang - math.pi
    elif perp_ang < -math.pi / 2:
        perp_ang = perp_ang + math.pi

    # Displacement across the perpendicular line (width)
    dx = 0.5 * prop_wh[0] * math.cos(perp_ang)
    dy = 0.5 * prop_wh[0] * math.sin(perp_ang)
    # dz = prop_wh[1] / 2

    return [
        sorted([target_centroid[0] + dx, target_centroid[0] - dx]),
        sorted([target_centroid[1] + dy, target_centroid[1] - dy]),
        # sorted([target_centroid[2] + dz, target_centroid[2] - dz]),
    ]


def normalize_dict(
    d: Dict[Any, float], lb: float, ub: float
) -> Dict[Any, float]:
    """Given a dictionary with floats and two bounds, normalize the values"""
    minf, maxf = min(d.values()), max(d.values())
    if minf != maxf:
        range_ratio = (ub - lb) / (maxf - minf)
        return {k: (v - minf) * range_ratio + lb for k, v in d.items()}
    else:
        return {k: ub for k, _ in d.items()}


def top_x_values(d: Dict[Any, float], x: int) -> Dict[Any, float]:
    """Create a new Dict with the top X values of a Dict"""
    x = min(x, len(d))
    return dict(list(sorted(d.items(), key=lambda x: x[1], reverse=True))[:x])


def f_logistic(x: float, x0: float, logv: float, k: float) -> float:
    """Logistic Function"""
    return logv / (1 + math.exp(-k * (x - x0)))


def get_forgetcurve(mu: float, a: float, t: float, d: float) -> float:
    """Forgetting Curve (Weibull-based)"""
    return mu * math.exp(-math.pow((a * t) / d, d))


def estimate_forgetting_t(
    mu: float, a: float, t: float, d: float, fline: float
) -> float:
    """Create future timestamp for estimated forgetting time"""
    # If the curve is entirely below fline...
    if mu <= fline:
        # It must be schedule to forget NOW (or ASAP)
        # (otherwise estimation would be an imaginary domain)
        return t

    try:
        tdelta = (d / a) * math.pow(-math.log(fline / mu), 1 / d)
    except OverflowError as exc:
        raise OverflowError(
            f"For params: {mu}, {a}, {t}, {d}, {fline}"
        ) from exc
    except ValueError as exc:
        # Usually a Domain error.
        raise ValueError(f"For params: {mu}, {a}, {t}, {d}, {fline}") from exc

    return t + tdelta


def substitute(text: str, subdict: dict) -> str:
    """From text, substitutes the values in subdict based on the keys.
    For example, if the prompt text has a variable `<actor>`, then
    `subdict` needs to have a `"actor":"name of actor"` key-value pair
    that will replace`<actor>` in the prompt with `"name of actor"`.
    """
    # Partially inspired by:
    # https://stackoverflow.com/questions/51102201/replace-a-string-using-dictionary-regex
    return re.sub(
        # r"(?<=\<)(" + "|".join(re.escape(k) for k in subdict) + r")(?=\>)",
        r"\<(" + "|".join(re.escape(k) for k in subdict) + r")\>",
        lambda x: str(subdict[x.group(1)]),
        text,
    )


JST = ZoneInfo("Asia/Tokyo")


def jst_ts(t: float) -> datetime:
    return datetime.fromtimestamp(t, JST)
