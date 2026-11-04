#!/usr/bin/env python
# coding: utf-8 -*-

"""Sensor Memory for Object Recognition"""

import message_filters
from geometry_msgs.msg import PoseStamped
from pymongo import GEO2D
from rclpy.exceptions import NameValidationException
from rclpy.node import Subscription
from recognition_msgs.msg import Objects  # type: ignore
from sensor_msgs.msg import CameraInfo

from ..util import ROBOT_NAME, LimitedDict, box_est, get_time_from_header
from .sensor_memory_base import SensorMemoryBase


class SensorMemoryObject(SensorMemoryBase):
    def __post_init__(self):
        super().__post_init__()
        self.setup_index(
            self.sm_coll, "location_global", GEO2D, min=-10000.0, max=10000.0
        )
        try:
            if isinstance(self.subscriber, Subscription):
                # Destroy subscription created in constructor
                self.node.destroy_subscription(self.subscriber)

            self.subscriber = message_filters.Subscriber(
                self.node,
                self.topic_info.t_type,
                self.topic_info.name,
                qos_profile=self.topic_info.qos,
            )
            self.subcam = message_filters.Subscriber(
                self.node,
                CameraInfo,
                f"{ROBOT_NAME}_camera/color/camera_info",
                qos_profile=self.topic_info.qos,
            )
            self.subloc = message_filters.Subscriber(
                self.node,
                PoseStamped,
                "rover/pose",
                qos_profile=self.topic_info.qos,
            )
            self.sub_ts = message_filters.ApproximateTimeSynchronizer(
                [self.subscriber, self.subcam, self.subloc], 10, 0.01
            )
            target_cb = (
                self.sync_callback_wrapper
                if self.eval_coll is not None
                else self.sync_callback
            )
            self.sub_ts.registerCallback(target_cb)

        except NameValidationException as e:
            self.logger.error(
                "[SENSOR] Could not Subscribe to Topic "
                + f"'{self.topic_info.name}'. REASON: '{str(e)}'. "
                + "Related functionality will not be included inthis session."
            )
        self.seen_obj = LimitedDict(max_size=20, default_value="")

    def callback(self, data: str) -> None:
        return

    def sync_callback(
        self, data: Objects, cinfo: CameraInfo, loc: PoseStamped
    ) -> None:
        """Callback for the Objects + Camera data subscriptions"""
        rob_loc = [
            loc.pose.position.x,
            loc.pose.position.y,
            loc.pose.position.z,
        ]

        for obj in data.objects:
            try:
                out = {}
                tstamp = get_time_from_header(obj.header)

                out["instance_id"] = obj.instance_id

                out["name"] = obj.name
                out["class_id"] = obj.class_id
                out["confidence"] = obj.confidence

                out["attributes"] = []
                for label in obj.attributes:
                    out["attributes"].append(
                        (label.type, label.label_id, label.name)
                    )

                out["recog_results"] = []
                for rec_results in obj.recog_results:
                    recog_db = {}
                    recog_db["name"] = rec_results.name  # str
                    recog_db["type"] = rec_results.type  # str
                    recog_db["value"] = rec_results.value  # float
                    recog_db["label"] = rec_results.label  # string
                    recog_db["vector"] = list(rec_results.vector)  # float[]
                    out["recog_results"].append(recog_db)

                out["location_img"] = list(obj.location)
                out["location_sensor"] = list(obj.location_sensor)
                out["location_global"] = list(obj.location_global)[:2]

                # dist = math.dist(out["location_global"], rob_loc)
                # out["location_plane"] = SensorMemoryObject.corner_est(
                #     dist, out["location_img"], cinfo).tolist()
                out["location_box"] = box_est(
                    rob_loc, out["location_global"], out["location_img"], cinfo
                )

                out["camera_res"] = [cinfo.width, cinfo.height]

                # Check if this is still necessary
                # out["name_alias"] = self.get_alias(obj.class_id)
                out["nearby"] = ""  # Pending for now?
                out["created_at_ts"] = tstamp

                self.__insertdoc__(out)

            except NameValidationException as e:
                self.logger.error(
                    f"[SENSOR] Could not Subscribe to Topic '{self.topic_info.name}'. "
                    + f'REASON: "{str(e)}". '
                    + "Related functionality will not be included in this session."
                )
            except KeyError as e:
                self.logger.error(
                    f"[SENSOR] Error Inserting '{self.topic_info.name}'. "
                    + f'Object not found in Object Name Alias List. Details: "{str(e)}"'
                )

    # def get_alias(self, class_id: int) -> str:
    #     if class_id not in self.seen_obj:

    #         known_obj = self.sm_coll.database.dictionary.object_names.find_one(
    #             {"class_id": class_id}
    #         )

    #         if known_obj is None:
    #             self.seen_obj[class_id] = ""
    #         else:
    #             self.seen_obj[class_id] = known_obj["name_alias"]

    #     return self.seen_obj[class_id]

    def sync_callback_wrapper(
        self, data: Objects, cinfo: CameraInfo, loc: PoseStamped
    ) -> None:
        """Callback Wrapper, to evaluate execution info."""
        # 1. Record Starting Time
        start_ts = self.node.get_clock().now().nanoseconds * 1e-9
        # 2. Call original Callback
        self.sync_callback(data, cinfo, loc)
        # 3. Record Ending Time
        end_ts = self.node.get_clock().now().nanoseconds * 1e-9
        # 4. Get DB Storage Size

        db_info = self.sm_coll.database.command(
            {"dbStats": 1, "freeStorage": 1}
        )
        db_size = (db_info["storageSize"] - db_info["freeStorageSize"]) / 1024
        # 5. Save to different database
        db_doc = {
            "process": f"stm_{self.sm_coll.name}",
            "start": start_ts,
            "end": end_ts,
            "size": db_size,
        }
        if self.eval_coll is not None:
            self.eval_coll.insert_one(db_doc)
