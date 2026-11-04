from collections import OrderedDict, deque
from enum import Enum
from typing import Any, Generator, Mapping, MutableMapping, Tuple

from rcl_interfaces.msg import ParameterDescriptor, ParameterType
from rclpy.node import Node
from rclpy.time import Time


class LimitedDict(MutableMapping):
    def __init__(self, max_size=100, default_value=0):
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


class TimeLimitedDict(MutableMapping):
    def __init__(self, max_size=100):
        self.max_size = max_size
        self.__data = deque(maxlen=max_size)
        self.__keys = deque(maxlen=max_size)

    def get(self, key: float):
        low, mid, high = 0, len(self.__data) // 2, len(self.__data) - 1
        while high - low > 1:
            if key > self.__keys[mid]:
                low, mid = mid, (mid + high) // 2
            elif key < self.__keys[mid]:
                mid, high = (low + mid) // 2, mid
            else:
                low = high = mid
        return (
            self.__data[mid]
            if self.__keys[low] <= key < self.__keys[high]
            else (
                self.__data[high]
                if key >= self.__keys[high]
                else self.__data[low]
            )
        )

    def __repr__(self):
        return str(list(zip(self.__keys, self.__data)))

    def __str__(self):
        elems = (f"({k}, {v})" for k, v in iter(self))
        return f"{{{', '.join(elems)}}}"

    def __len__(self):
        return len(self.__data)

    def __getitem__(self, key: float) -> Any:
        return self.get(key)

    def __setitem__(self, key: float, val: Any) -> None:
        self.__keys.append(key)
        self.__data.append(val)

    def __delitem__(self, key: Any) -> None:
        raise NotImplementedError()

    def __iter__(self) -> Generator[Tuple[Any, Any], None, None]:
        for k, v in zip(self.__keys, self.__data):
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


def get_ts_from_headerstamp(header) -> float:
    return Time.from_msg(header.stamp).nanoseconds * 1e-9
