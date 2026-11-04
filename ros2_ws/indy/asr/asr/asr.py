#!/usr/bin/python3
# coding: utf-8

import json
import os
import re
import socket
import struct
import warnings
from collections import defaultdict
from functools import partial
from io import BytesIO
from itertools import compress
from typing import Callable, Dict, Tuple

import numpy as np
import rclpy.logging
import torch  # type: ignore
from common_msgs.msg import StringStamped  # type: ignore
from faster_whisper import WhisperModel  # type: ignore
from human_tracker_msgs.msg import AudioInfoList  # type: ignore
from pydub import AudioSegment  # type: ignore
from pyindy.param_manager import ParamManager
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.logging import LoggingSeverity as LS
from rclpy.node import Node
from rclpy.timer import Timer
from std_msgs.msg import String

from .util import (
    LimitedDict,
    ParamDesc,
    TimeLimitedDict,
    get_current_ts,
    get_ros_param,
    get_ts_from_headerstamp,
)

os.environ["OMP_NUM_THREADS"] = "1"

MAXSPEECHLEN = 320000

REJECT_WORDS = [
    "ご視聴",
    "ご覧",
    "また見てね",
    "by H.",
    "次回お話ししましょう",
    "次回へ続く",
    "見てくれてありがとう",
    "はじめしゃちょー",
    "ありがとうございました",
    "お疲れ様でした",
    "お疲れさまでした",
    "おつかれさまでした",
    "あーっと",
    "ご利用いただきありがとうございます",
    "ご清聴",
    "ファイターキー",
    "カンカンカン",
    "ギャルギャル",
    "レインボーワンキー",
    "次の動画で",
    "字幕作成",
    "はーい",
    "よろしくお願いいたします",
    "ビッグタイムアップ",
    "ハニマス",
    "おやすみなさい",
    "最後まで視聴してくださって",
]  # TODO move to database?


def force_cudnn_initialization():
    s = 32
    dev = torch.device("cuda")
    torch.nn.functional.conv2d(
        torch.zeros(s, s, s, s, device=dev),
        torch.zeros(s, s, s, s, device=dev),
    )


force_cudnn_initialization()


# ASR wrapper
class ASR(object):
    def __init__(self, model_name, device):
        self.model_name = model_name
        self.device = device
        compute_type = "float16"
        if device == "cpu":
            compute_type = "int16"
        if self.model_name == "whisper_large_v1":
            self.model = WhisperModel(
                "large-v1", device=device, compute_type=compute_type
            )
        elif self.model_name == "whisper_large_v2":
            self.model = WhisperModel(
                "large-v2", device=device, compute_type=compute_type
            )
        elif self.model_name == "whisper_medium":
            self.model = WhisperModel(
                "medium", device=device, compute_type=compute_type
            )
        elif self.model_name == "whisper_base":
            self.model = WhisperModel(
                "base", device=device, compute_type=compute_type
            )
        elif self.model_name == "whisper_small":
            self.model = WhisperModel(
                "small", device=device, compute_type=compute_type
            )
        elif self.model_name == "whisper_tiny":
            self.model = WhisperModel(
                "tiny", device=device, compute_type=compute_type
            )

        else:
            print(
                f"The specified ASR model ({self.model_name}) was not found. Loading "
                + "the default model (whisper_base) for this session."
            )
            self.model_name = "whisper_base"
            self.model = WhisperModel(
                "base", device=device, compute_type=compute_type
            )

    # For wisper
    def whisper_transcribe(self, raw_audio, verbose=True):
        all_output = self.model.transcribe(
            raw_audio, language="ja", word_timestamps=True, vad_filter=False
        )  # Able to recognize Einglish if wee DON'T set language
        # all_output = self.model.transcribe(raw_audio, word_timestamps=True)
        segments, info = all_output
        average_confidence = []
        final_text = []
        if verbose:
            print("info:", info)
            print("segments:")
        for segment in segments:
            if verbose:
                print(
                    "[%.2fs -> %.2fs] %s"
                    % (segment.start, segment.end, segment.text)
                )
            average_confidence.extend([_.probability for _ in segment.words])
            final_text.append(segment.text)
        average_confidence = np.mean(average_confidence)

        final_text = " ".join(final_text)
        if verbose:
            print("final_text: %s" % final_text)
            print("confidence: %.2f" % average_confidence)
        return final_text, average_confidence, all_output

    # transcribe
    def transcribe(self, raw_audio, verbose=True):
        # if "whisper_" in self.model_name:
        return self.whisper_transcribe(raw_audio, verbose=verbose)


class ASRNode(Node):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(node_name="asr_node", *args, **kwargs)
        self.pub = self.create_publisher(StringStamped, "asr/raw_text", 10)

        # 1.get mongo_uri and mongo_port from launch arguments
        self.declare_parameters(
            namespace=self.get_namespace(),
            parameters=[
                ("mongo_uri", "", ParamDesc.String.value),
                ("mongo_port", 0, ParamDesc.Int.value),
            ],
        )
        mongo_uri = get_ros_param(self, "mongo_uri", ParamDesc.String)
        mongo_port = get_ros_param(self, "mongo_port", ParamDesc.Int)

        # (optional) Default values
        debug_msgs = False
        self.adin_server = "localhost"
        self.adin_ports = [5562]
        self.ports_priority = {5562: 0}
        self.device = "cuda"
        self.ignore_short_pause = 0.5
        self.asr_model = "whisper_large_v2"
        self.socket_keepalive = [60, 10, 6]
        self.always_respond = True

        # 2.get parameters from MongoDB (robot_config database)
        pm = ParamManager(mongo_uri, mongo_port)
        params = pm.get_param("asr")

        if params is None:
            self.get_logger().warning(
                "Parameters for ASR not in Params DB. "
                + "Using Default Parameters (This may cause errors)."
            )
        else:
            debug_msgs = (
                params["debug_msgs"] if "debug_msgs" in params else debug_msgs
            )
            self.adin_server = (
                params["adin_server"]
                if "adin_server" in params
                else self.adin_server
            )
            self.adin_ports = (
                params["adin_ports"]
                if "adin_ports" in params
                else self.adin_ports
            )

            self.adin_ports_db = self.adin_ports.copy()

            self.ports_priority = (
                {
                    int(p): int(v)
                    for p, v in params["adin_ports_priority"].items()
                }
                if "adin_ports_priority" in params
                else self.ports_priority
            )

            max_p = self.max_priority

            for p in self.adin_ports:
                if p not in self.ports_priority:
                    self.ports_priority[p] = max_p + 1
            self.curr_port_priority = self.min_priority
            self.get_logger().info(
                f"Priority set to {self.curr_port_priority} (init)"
            )

            self.device = (
                params["device"] if "device" in params else self.device
            )
            self.ignore_short_pause = (
                params["ignore_short_pause"]
                if "ignore_short_pause" in params
                else self.ignore_short_pause
            )
            self.asr_model = (
                params["asr_model"]
                if "asr_model" in params
                else self.asr_model
            )
            self.socket_keepalive = (
                params["socket_keepalive"]
                if "socket_keepalive" in params
                else self.socket_keepalive
            )
            self.always_respond = (
                params["always_respond"]
                if "always_respond" in params
                else self.always_respond
            )

        # Set up node
        self.get_logger().set_level(LS.DEBUG if debug_msgs else LS.INFO)
        self.asr = ASR(self.asr_model, self.device)

        self.port_instanceid_d = defaultdict(lambda: -1)
        self.atr_sub = self.create_subscription(
            AudioInfoList, "human_tracker/audio_info", self.callback_atr, 10
        )

        self.person2looking = LimitedDict(max_size=100, default_value=0)
        self.looking_sub = self.create_subscription(
            StringStamped, "recog/person/looking_at", self.callback_looking, 10
        )

        self.asr_ctrl_sub = self.create_subscription(
            String, "asr/asr_ctl", self.callback_asr_ctl, 10
        )

        if len(self.socket_keepalive) != 3:
            self.get_logger().warn(
                "Invalid length for keepalive_vals, "
                + "using default values of [60, 10, 6]"
            )
            self.socket_keepalive = [60, 10, 6]

        self.__last_whisper_restart = get_current_ts(self)

        self.server_sockets: Dict[int, socket.socket] = {}
        self.client_sockets: Dict[int, Tuple[socket.socket, str]] = {}

        self.connectflag: Dict[int, bool] = {p: False for p in self.adin_ports}

        self.socket_ts: Dict[int, float] = {}
        self.audio_callbacks: Dict[int, Callable] = {}
        self.audio_timers: Dict[int, Timer] = {}

        self.initiate_callback_ports()

    @property
    def is_debugging(self) -> bool:
        return (
            self.get_logger().get_effective_level()
            == rclpy.logging.LoggingSeverity.DEBUG
        )

    @property
    def max_priority(self) -> int:
        return max(self.ports_priority.values())

    @property
    def min_priority(self) -> int:
        return min(self.ports_priority.values())

    def clear_callback_ports(self):
        self.shutdown_all_sockets()
        for p in self.adin_ports:
            if p in self.audio_timers:
                self.audio_timers[p].destroy()
                del self.audio_timers[p]
            if p in self.audio_callbacks:
                del self.audio_callbacks[p]
            if p in self.socket_ts:
                del self.socket_ts[p]
                del self.server_sockets[p]
            if p in self.client_sockets:
                del self.client_sockets[p]
            del self.connectflag[p]

    def initiate_callback_ports(self):
        for p in self.adin_ports:
            # Create timer callback functions using partialmethod
            self.audio_callbacks[p] = partial(self.socket_callback, p)

            # Create timers each with its own MutuallyExclusiveCallbackGroup
            self.audio_timers[p] = self.create_timer(
                timer_period_sec=self.ignore_short_pause,
                callback=self.audio_callbacks[p],
                callback_group=MutuallyExclusiveCallbackGroup(),
            )

            self.server_sockets[p] = self.create_server_socket(p)
            self.socket_ts[p] = get_current_ts(self)

    def restart_whisper(self) -> None:
        now = get_current_ts(self)
        if now - self.__last_whisper_restart > 1:
            self.asr = ASR(self.asr_model, self.device)
            self.get_logger().debug("Whisper Reset (Test).")
            self.__last_whisper_restart = now

    def ros_talker(self, port: int, asr_text: dict) -> None:
        asr_text["recog_time"] = str(get_current_ts(self))
        asr_text["sep_port"] = port

        if self.is_debugging:
            text = json.dumps(asr_text, ensure_ascii=False, indent=2)
            self.get_logger().info(
                f"[PORT {port}] ACCEPTED:\n{self.pprint_recog(asr_text, False)}"
            )
        else:
            text = json.dumps(asr_text, ensure_ascii=False)
            self.get_logger().info(
                f"[PORT {port}] {self.pprint_recog(asr_text)}"
            )

        msg = StringStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.data = text
        self.pub.publish(msg)

    def callback_atr(self, data):
        atrresults = data
        for atrresult in atrresults.info:
            port = int(atrresult.port)
            if port not in self.adin_ports:
                continue
            if atrresult.instance_id != -1:
                self.port_instanceid_d[port] = atrresult.instance_id

    def callback_looking(self, looking_at):
        d = json.loads(looking_at.data)
        for inst_id, status in d.items():
            self.person2looking[int(inst_id)] = status

    def callback_asr_ctl(self, msg):
        try:
            d = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"asr_ctl error: {str(e)}")
            return
        if "sep_ports" in d and isinstance(d["sep_ports"], list):
            self.reset_ports(d["sep_ports"])
        elif "reset_ports" in d and d["reset_ports"]:
            self.reset_ports(self.adin_ports_db)
        else:
            self.get_logger().warn(f"asr_ctl invalid json: {msg.data}")

    def reset_ports(self, new_ports: list[int]):
        self.get_logger().info("[asr_ctl] Resetting ports...")
        self.clear_callback_ports()
        self.curr_port_priority = 0
        self.get_logger().info(
            f"Priority set to {self.curr_port_priority} (reset)"
        )
        self.adin_ports = new_ports.copy()
        self.get_logger().debug(
            "[asr_ctl] Resetting ports: "
            + f"[{', '.join(str(x) for x in self.adin_ports)}]"
        )
        self.connectflag = {p: False for p in self.adin_ports}
        self.initiate_callback_ports()
        self.get_logger().info(
            "[asr_ctl] Listening on "
            + f"[{', '.join(str(x) for x in self.adin_ports)}]"
        )
        max_p = self.max_priority
        for p in self.adin_ports:
            if p not in self.ports_priority:
                self.ports_priority[p] = max_p + 1

    def set_socket_keepalive(self, s: socket.socket) -> None:
        # Activate Keepalive packets
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # Start sending Keepalives after N sec of being idle
        s.setsockopt(
            socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, self.socket_keepalive[0]
        )
        # Frequency in secs of keepalive packets
        s.setsockopt(
            socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, self.socket_keepalive[1]
        )
        # Number of failed packets to consider a connection errror
        s.setsockopt(
            socket.IPPROTO_TCP, socket.TCP_KEEPCNT, self.socket_keepalive[2]
        )
        # For default values:
        # If no data after 60 sec --> start sending keepalives
        # 1 keep alive every 10 sec
        # server disconnects after 6 failed KAs (60 sec)

    def create_server_socket(self, port: int) -> socket.socket:
        # SERVER SOCKET
        self.get_logger().info(
            f"[PORT {port}] Creating socket on {self.adin_server}:{port}."
        )
        while True:
            try:

                adinserversock = socket.create_server(
                    (self.adin_server, port),
                    reuse_port=True,
                    backlog=0,
                )
                self.set_socket_keepalive(adinserversock)
                break
            except OSError as e:
                self.get_logger().error(
                    f"[PORT {port}] Socket Error: {e}",
                    throttle_duration_sec=1.0,
                )
                continue

        adinserversock.listen(0)

        self.get_logger().info(
            f"[PORT {port}] Waiting for audio data connections on "
            + f"{self.adin_server}:{port}"
        )

        return adinserversock

    def connect_client_socket(self, port: int) -> socket.socket:
        # CLIENT SOCKET (receives data)
        # If client socket is connected, return it.
        if self.connectflag[port]:
            return self.client_sockets[port][0]

        adinserversock = self.server_sockets[port]

        adinclientsock, adinclient_address = adinserversock.accept()

        output_new_data = True
        if port in self.client_sockets:
            old_address = self.client_sockets[port][1]
            output_new_data = old_address != adinclient_address

        if output_new_data:
            self.get_logger().info(
                f"[PORT {port}] Connected to new audio client "
                + f"{adinclient_address[0]}:{adinclient_address[1]}",
            )

        self.connectflag[port] = True
        self.client_sockets[port] = (adinclientsock, adinclient_address)

        self.update_priority()

        return adinclientsock

    def disconnect_client(self, port: int) -> None:
        if port not in self.connectflag or not self.connectflag[port]:
            return
        try:
            self.client_sockets[port][0].close()
        except Exception as e:
            self.get_logger().error(
                f"[PORT {port}] Error while disconnecting "
                + f"{self.client_sockets[port][1]}: {e}"
            )
        self.connectflag[port] = False

        self.update_priority()

    def update_priority(self):
        min_p = self.get_min_alive_priority()
        if self.curr_port_priority != min_p:
            self.curr_port_priority = min_p
            self.get_logger().info(
                f"Priority set to {self.curr_port_priority} (update)"
            )

    def get_min_alive_priority(self) -> int:
        ports = list(self.connectflag.keys())
        return min(
            compress(
                (self.ports_priority[k] for k in ports),
                (self.connectflag[k] for k in ports),
            )
        )

    def is_client_connected(self, port: int) -> bool:
        return self.connectflag[port]

    def shutdown_all_sockets(self):
        for k, scket in self.client_sockets.items():
            if not self.connectflag[k]:
                continue
            try:
                scket[0].close()
            except Exception as e:
                self.get_logger().error(
                    f"Error while disconnecting {scket[1]}: {e}"
                )
        for scket in self.server_sockets.values():
            try:
                scket.close()
            except Exception as e:
                self.get_logger().error(
                    "Error while disconnecting server socket "
                    + f"{scket.getsockname()}: {e}"
                )

    def print_elapsed(self, port: int, msg: str):
        now = get_current_ts(self)
        elapsed = now - self.socket_ts[port]
        self.socket_ts[port] = now
        self.get_logger().debug(f"[PORT {port}] {msg}: {elapsed:.4f}s")

    def socket_callback(self, port: int):
        # If port's priority is different from current priority, just return

        buffer = b""
        audio = AudioSegment.silent(duration=1, frame_rate=16000)

        self.get_logger().debug(
            f"[PORT {port}] Start of Callback",
        )

        nbytes = 0
        while True:
            try:
                adinclientsock = self.connect_client_socket(port)
                # Waiting for the next speech
                # TIMEOUT MODE
                adinclientsock.settimeout(self.ignore_short_pause)
                data = adinclientsock.recv(4)
                adinclientsock.settimeout(None)  # BLOCKING MODE
            except socket.timeout:  # Timeout
                data = None
                continue
            except ConnectionResetError:
                self.get_logger().debug(f"[PORT {port}] Connection Reset.")
                self.disconnect_client(port)
                return
            except Exception as e:
                self.get_logger().debug(f"[PORT {port}] Connection Error: {e}")
                self.disconnect_client(port)
                return

            # data integration
            if data and len(data) >= 4:
                nbytes = struct.unpack("<i", data)[0]

                if nbytes == 0:
                    if buffer != b"":
                        self.get_logger().debug(
                            f"[PORT {port}] nbytes = 0, buffer has data, doing recog."
                        )
                        audio = audio + AudioSegment.from_raw(
                            BytesIO(buffer),
                            sample_width=2,
                            frame_rate=16000,
                            channels=1,
                        )
                        self.send_audio(audio, port)
                        return
                    else:
                        self.get_logger().debug(
                            f"[PORT {port}] nbytes = 0, buffer is empty."
                        )
                        if audio.duration_seconds > 0.4:
                            self.get_logger().debug(
                                f"[PORT {port}] Recognition possible."
                            )
                            self.send_audio(audio, port)
                            return

                elif nbytes < 0 or nbytes > MAXSPEECHLEN:
                    self.get_logger().debug(
                        f"[PORT {port}] invalid nbytes value ({nbytes})."
                    )

                    if buffer:
                        audio = audio + AudioSegment.from_raw(
                            BytesIO(buffer),
                            sample_width=2,
                            frame_rate=16000,
                            channels=1,
                        )

                    if audio.duration_seconds > 0.1:

                        if self.send_audio(audio, port):
                            self.get_logger().debug(
                                f"[PORT {port}] Recognition Successful."
                            )
                        else:
                            self.get_logger().debug(
                                f"[PORT {port}] Recognition Failure."
                            )
                    return
                else:
                    subbuff = b""
                    subsize = nbytes
                    while subsize > 0:
                        try:
                            audio_data = adinclientsock.recv(subsize)
                            subsize -= len(audio_data)
                        except Exception as e:
                            self.get_logger().error(
                                f"[PORT {port}] Error receiving audio data: {e}"
                            )
                            audio_data = b""

                        if audio_data == b"":
                            break

                        subbuff += audio_data
                    # self.get_logger().debug(
                    #     f"[PORT {port}] Added {len(audio_data)}bytes to buffer "
                    #     + f"({len(buffer)}/{nbytes})",
                    # )

                    if len(subbuff) >= 0:
                        buffer += subbuff

                    to_disconnect = True
                    if len(subbuff) > nbytes:
                        self.get_logger().debug(
                            f"[PORT {port}] !! Audio Buffer overflow !! "
                        )
                        audio_data = b""
                        # TEST: What if we send a restart signal?
                        adinclientsock.send(bytes([2]))
                        adinclientsock.send(bytes([1]))
                        to_disconnect = False

                    if audio_data == b"":  # Disconnection, must process
                        audio = audio + AudioSegment.from_raw(
                            BytesIO(buffer),
                            sample_width=2,
                            frame_rate=16000,
                            channels=1,
                        )
                        self.send_audio(audio, port)

                        # Data is null bytes -> Client has disconnected
                        if to_disconnect:
                            self.get_logger().debug(
                                f"[PORT {port}] Disconnecting from Client."
                            )
                            self.disconnect_client(port)

                        return
                    data = None

            # New data was not observed args.ignore_short_pause seconds?
            elif buffer:
                audio = audio + AudioSegment.from_raw(
                    BytesIO(buffer),
                    sample_width=2,
                    frame_rate=16000,
                    channels=1,
                )
                self.send_audio(audio, port)
                buffer = b""
                audio = AudioSegment.silent(duration=1, frame_rate=16000)
                if data == b"":
                    # Data is null bytes -> Client has disconnected
                    self.get_logger().debug(
                        f"[PORT {port}] Client Disconnected."
                    )
                    self.disconnect_client(port)
                    return
                else:
                    self.get_logger().error(
                        f"[PORT {port}] Unknown/Unexpected connection state. Resetting."
                    )
                    self.get_logger().debug(
                        f"Data size: {len(data)}, Buffer size: {len(buffer)}, "
                        + f"Processed audio data length: {audio.duration_seconds}s. "
                    )
                    adinclientsock.send(bytes([2]))
                    adinclientsock.send(bytes([1]))
            elif data == b"":
                # Data is null bytes -> Client has disconnected
                self.get_logger().debug(f"[PORT {port}] Client Disconnected.")
                self.disconnect_client(port)
                return
            else:
                self.get_logger().error(
                    f"[PORT {port}] Unknown/Unexpected connection state. Resetting."
                )
                self.get_logger().debug(
                    f"Data size: {len(data)}, Buffer size: {len(buffer)}, "
                    + f"Processed audio data length: {audio.duration_seconds}s. "
                )
                adinclientsock.send(bytes([2]))
                adinclientsock.send(bytes([1]))
                return

    def send_audio(self, audio: AudioSegment, port: int):
        self.update_priority()

        if self.ports_priority[port] != self.curr_port_priority:
            self.get_logger().debug(
                f"[PORT {port}] (Ignored): "
                + f"instance_id: {self.get_instanceid_d(port, get_current_ts(self))}"
            )
            return False

        try:
            if audio.duration_seconds < 0.4:
                return False

            ts = get_current_ts(self)

            audio_data = (
                np.frombuffer(audio.raw_data, np.int16)  # type: ignore
                .flatten()
                .astype(np.float32)
                / 32768.0
            )
            self.get_logger().debug(
                f"[PORT {port}] recognizing... {audio.duration_seconds:f}s"
            )
            with warnings.catch_warnings():
                # For numpy warnings in transcription
                warnings.simplefilter("ignore")
                final_text, score, all_output = self.asr.transcribe(
                    audio_data, verbose=True
                )

            final_text = final_text.strip()

            instance_id = self.get_instanceid_d(port, ts)
            looking = self.get_person2looking(instance_id, ts)

            # should_response = asr.addressee_recognition(audio_data, looking)
            should_response = self.always_respond or looking > 0
            self.port_instanceid_d[port] = -1

            # """
            # Send results to ROS
            ros_data = {
                "words": final_text,
                "scores": json.dumps(score),
                "duration": audio.duration_seconds * 1000,
                "num_frame": -1,
                "should_response": should_response,
                "asr_model": self.asr.model_name,
            }

            if not final_text or re.compile("|".join(REJECT_WORDS)).search(
                final_text
            ):
                self.get_logger().debug(
                    f"[PORT {port}] !!REJECTED!!: "
                    + f"{self.pprint_recog(ros_data)}"
                )
            else:
                self.get_logger().info(
                    f"[PORT {port}] instance_id: {instance_id}  |  "
                    + f"looking at: {looking} | Timestamp: {ts}"
                )
                self.ros_talker(port, ros_data)

            return True  #

        except Exception as e:
            self.get_logger().error(
                f"[PORT {port}] Recognition Exception: {e}"
            )

        return False

    def pprint_recog(
        self,
        recog: dict,
        single_line=True,
        excl_fields=["words", "should_response", "sep_port", "num_frame"],
    ) -> str:
        sep = ", " if single_line else "\n  "
        pp = ""
        pp += f"Utterance: \"{recog['words']}\"" + sep
        pp += sep.join(
            f"{k}:{v}" for k, v in recog.items() if k not in excl_fields
        )
        return pp

    def get_instanceid_d(self, port: int, ts: float) -> int:
        return int(self.port_instanceid_d[port])

    def get_person2looking(self, instance_id: int, ts: float) -> int:
        return int(self.person2looking.get(instance_id))


class ASRNodeTT(ASRNode):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.port_instance_timed = TimeLimitedDict()
        self.person2looking_timed = TimeLimitedDict()

    def callback_atr(self, data):
        atr_dict = defaultdict(lambda: -1)
        ts = get_ts_from_headerstamp(data.header)
        for atr_result in data.info:
            port = int(atr_result.port)
            if port not in self.adin_ports:
                continue
            if atr_result.instance_id != -1:
                atr_dict[port] = atr_result.instance_id
        self.port_instance_timed[ts] = atr_dict
        self.port_instanceid_d.update(atr_dict)
        if atr_dict:
            self.get_logger().debug(
                f"[ATR] Audio Tracking: {dict.__repr__(atr_dict)}",
                throttle_duration_sec=60.0,
            )

    def callback_looking(self, data: StringStamped):
        looking_dict = defaultdict(lambda: -1)
        ts = get_ts_from_headerstamp(data.header)
        d = json.loads(data.data)
        for inst_id, status in d.items():
            looking_dict[int(inst_id)] = status
        self.person2looking.update(looking_dict)
        self.person2looking_timed[ts] = looking_dict
        if looking_dict:
            self.get_logger().debug(
                f"[P2L] People Looking: {dict.__repr__(looking_dict)}",
                throttle_duration_sec=60.0,
            )

    def get_instanceid_d(self, port: int, ts: float) -> int:
        return int(
            self.port_instance_timed[ts][port]
            if len(self.port_instance_timed) > 0
            else self.port_instanceid_d[port]
        )

    def get_person2looking(self, instance_id: int, ts: float) -> int:
        return int(
            self.person2looking_timed[ts][instance_id]
            if len(self.person2looking_timed) > 0
            else self.person2looking.get(instance_id)
        )


def main():
    rclpy.init()

    node = ASRNodeTT()

    executor = MultiThreadedExecutor()
    executor.add_node(node)

    try:
        executor.spin()
    finally:
        node.shutdown_all_sockets()
        node.destroy_node()
        rclpy.try_shutdown()
