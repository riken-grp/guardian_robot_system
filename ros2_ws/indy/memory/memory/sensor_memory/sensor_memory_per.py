#!/usr/bin/env python
# coding: utf-8 -*-

"""Sensor Memory for Persons Recognition"""

import message_filters
from geometry_msgs.msg import PoseStamped
from pymongo import GEO2D
from rclpy.exceptions import NameValidationException
from rclpy.node import Subscription
from recognition_msgs.msg import Persons  # type: ignore
from sensor_msgs.msg import CameraInfo

from ..util import ROBOT_NAME, LimitedDict, box_est, get_time_from_header
from .sensor_memory_base import SensorMemoryBase


class SensorMemoryPerson(SensorMemoryBase):
    def __post_init__(self):
        super().__post_init__()
        self.setup_index(
            self.sm_coll, "body_location", GEO2D, min=-10000.0, max=10000.0
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
        self.seen_per = LimitedDict(max_size=20, default_value="")

    def callback(self, data: str) -> None:
        return

    def sync_callback(
        self, data: Persons, cinfo: CameraInfo, loc: PoseStamped
    ) -> None:
        """Callback for the Persons + Camera data subscriptions"""
        rob_loc = [
            loc.pose.position.x,
            loc.pose.position.y,
            loc.pose.position.z,
        ]

        for per in data.persons:

            out = dict({})
            tstamp = get_time_from_header(per.header)

            out["name"] = per.name
            out["instance_id"] = per.instance_id
            out["class_id"] = per.class_id

            per_name_aliased = self.get_alias(per.class_id)

            if per_name_aliased:
                out["name_alias"] = per_name_aliased
            else:
                out["name_alias"] = "知らない人"
                out["name"] = "unknown"
                out["class_id"] = -1

            out["body_location"] = list(per.body_location_global)[:2]
            out["body_location_img"] = list(per.body_location)

            out["face_location"] = list(per.face_location_global)
            out["face_location_img"] = list(per.face_location)
            out["face_orientation"] = list(per.face_orientation)

            out["attributes"] = dict(
                zip(per.attributes, per.attribute_confidences)
            )

            out["pose"] = list(zip(per.pose.keypoints, per.pose.confidences))
            out["pose_sensor"] = list(
                zip(per.pose_sensor.keypoints, per.pose_sensor.confidences)
            )
            out["pose_global"] = list(
                zip(per.pose_global.keypoints, per.pose_global.confidences)
            )

            out["location_box"] = box_est(
                rob_loc, out["body_location"], out["body_location_img"], cinfo
            )

            out["camera_res"] = [cinfo.width, cinfo.height]

            out["created_at_ts"] = tstamp

            self.__insertdoc__(out)

    def get_alias(self, class_id: int) -> str:
        if class_id not in self.seen_per:

            known_obj = self.sm_coll.database.dictionary.person_names.find_one(
                {"class_id": class_id}
            )

            if known_obj is None:
                self.seen_per[class_id] = ""
            else:
                self.seen_per[class_id] = known_obj["name_alias"]

        return self.seen_per[class_id]

    def sync_callback_wrapper(
        self, data: Persons, cinfo: CameraInfo, loc: PoseStamped
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
