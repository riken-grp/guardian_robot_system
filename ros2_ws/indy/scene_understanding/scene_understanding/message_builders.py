import cv2
import numpy as np
import rclpy
from recognition_msgs.msg import Object, Objects, Person, Persons, Pose
from visualization_msgs.msg import Marker, MarkerArray

from . import configs as cfg
from .kana_romanizer import to_hepburn


class MessageBuilder:
    def visualize_image(self, oimg, x, y, w, h, name, cls_id):
        c = cfg.colors[cls_id % len(cfg.colors)].tolist()
        x, y, w, h = map(int, (x, y, w, h))
        oimg = cv2.rectangle(oimg, (x, y), (x + w, y + h), c, 2)
        oimg = cv2.putText(
            oimg,
            name,
            (x, y),
            cv2.FONT_HERSHEY_PLAIN,
            4,
            c,
            2,
            cv2.LINE_AA,
        )
        return oimg

    def to_alphabet(self, name):
        return to_hepburn(name)


class ObjectMessageBuilder(MessageBuilder):
    def __init__(self, names):
        super().__init__()
        self.names = names
        self.colors = cfg.colors

    def build_from_tracklets(self, header, tracklets, img, is_visualize):
        msg = Objects()
        msg.header = header
        oimg = None

        if is_visualize:
            oimg = np.copy(img)

        m_objects = []
        j_objects = []
        m_markers = MarkerArray()
        for t in tracklets:
            x, y, w, h = t[:4]
            lo_sensor = t[cfg.LOCATION_SENSOR_COLUMN]
            lo_global = t[cfg.LOCATION_GLOBAL_COLUMN]
            cls_id = int(t[cfg.CLASS_ID_COLUMN])
            conf = t[cfg.CONFIDENCE_COLUMN]
            instance_id = int(t[cfg.INSTANCE_ID_COLUMN])

            om, oj = self.build_object_2d(msg.header, x, y, w, h, conf, cls_id)
            om.instance_id = instance_id
            om.location_sensor = lo_sensor.tolist()
            om.location_global = lo_global.tolist()
            oj["instance_id"] = instance_id
            oj["location_sensor"] = lo_sensor
            oj["location_global"] = lo_global
            m_objects.append(om)
            j_objects.append(oj)

            if is_visualize:
                oimg = self.visualize_image(oimg, x, y, w, h, om.name, cls_id)

        msg.objects = m_objects

        jsondata = {}
        jsondata["timestamp"] = f"{msg.header.stamp.sec}.{msg.header.stamp.nanosec}"
        jsondata["detections"] = j_objects

        return msg, jsondata, m_markers, oimg

    def set_object_info(self, header, cls_id, location, conf):
        om = Object()
        om.header = header
        om.name = self.names[cls_id]
        om.class_id = cls_id
        om.instance_id = -1
        om.location = list(map(float, location))
        om.confidence = float(conf)
        return om

    def set_object_json(self, header, cls_id, location, conf):
        oj = {}
        oj["name"] = self.names[cls_id]
        oj["class_id"] = cls_id
        oj["instance_id"] = -1
        oj["location"] = location
        oj["confidence"] = conf

        return oj

    def build_object_2d(self, header, x, y, w, h, conf, cls_id):
        om = self.set_object_info(header, cls_id, [x, y, w, h], conf)
        oj = self.set_object_json(header, cls_id, [x, y, w, h], conf)
        return om, oj

    def build_from_detections(self, header, loc, detections, img, is_visualize):
        msg = Objects()
        msg.header = header
        msg.pose = loc.tolist()
        oimg = None

        if is_visualize:
            oimg = np.copy(img)

        m_objects = []
        j_objects = []
        for p in detections:
            x, y, w, h, conf, cls_id = p
            cls_id = int(cls_id)

            om, oj = self.build_object_2d(msg.header, x, y, w, h, conf, cls_id)
            m_objects.append(om)
            j_objects.append(oj)

            if is_visualize:
                oimg = self.visualize_image(oimg, x, y, w, h, om.name, cls_id)

        msg.objects = m_objects

        jsondata = {}
        jsondata["timestamp"] = f"{msg.header.stamp.sec}.{msg.header.stamp.nanosec}"
        jsondata["detections"] = j_objects

        return msg, jsondata, oimg

    def set_marker(self, header, x, y, z, cls_id):
        mm = Marker()
        mm.header = header
        mm.lifetime = rclpy.duration.Duration(seconds=0.1).to_msg()
        mm.type = Marker.SPHERE
        mm.id = cls_id
        c = cfg.colors[cls_id % len(cfg.colors)] / 255
        mm.color.r, mm.color.g, mm.color.b, mm.color.a = c[0], c[1], c[2], 1.0
        mm.scale.x, mm.scale.y, mm.scale.z = 0.1, 0.1, 0.1
        mm.pose.position.x, mm.pose.position.y, mm.pose.position.z = x, y, z
        mm.pose.orientation.w = 1.0
        mm.pose.orientation.x = 0.0
        mm.pose.orientation.y = 0.0
        mm.pose.orientation.z = 0.0

        return mm


class PersonMessageBuilder(MessageBuilder):
    def __init__(self):
        super().__init__()

    def build_from_tracklets(self, header, detections3d, poses3d, img, is_visualize):
        msg = Persons()
        mmsg = MarkerArray()
        msg.header = header
        oimg = None

        if is_visualize:
            oimg = np.copy(img)

        j_persons = []
        for instance_id, (det, pose) in enumerate(zip(detections3d, poses3d)):
            lo_image = det[:4].tolist()
            lo_sensor = det[cfg.POSE_DET_LOCATION_SENSOR_COLUMN].tolist()
            lo_global = det[cfg.POSE_DET_LOCATION_GLOBAL_COLUMN].tolist()
            conf = det[cfg.POSE_DET_CONFIDENCE_COLUMN]
            cls_id = int(det[cfg.POSE_CLASS_ID_COLUMN])
            pm, pj = self.build_person_2d(header, lo_image, conf, cls_id)
            pm.instance_id = -1
            pj["instance_id"] = -1
            pm.body_location_sensor = lo_sensor
            pj["body_location_sensor"] = lo_sensor
            pm.body_location_global = lo_global
            pj["body_location_global"] = lo_global

            ppm, ppj = self.build_pose_2d(pose)
            ppm3, ppj3 = self.build_pose_3d(pose)
            ppm3g, ppj3g = self.build_pose_3d_global(pose)

            pm.pose = ppm
            pm.pose_sensor = ppm3
            pm.pose_global = ppm3g
            pj["pose"] = ppj
            pj["pose_sensor"] = ppj3
            pj["pose_global"] = ppj3g

            pp11 = pose[11, cfg.POSE_KEYPOINT_SENSOR_COLUMN]
            pp12 = pose[12, cfg.POSE_KEYPOINT_SENSOR_COLUMN]
            x, y, z = (pp11 + pp12) / 2
            pmm = self.set_marker(header, x, y, z, instance_id)
            msg.persons.append(pm)
            j_persons.append(pj)
            mmsg.markers.append(pmm)

            if is_visualize:
                x, y, w, h = det[:4]
                oimg = self.visualize_image(oimg, x, y, w, h, "person", 0)
                oimg = self.pose_visualize(oimg, pose)

        jsondata = {}
        jsondata["timestamp"] = f"{msg.header.stamp.sec}.{msg.header.stamp.nanosec}"
        jsondata["detections"] = j_persons

        return msg, jsondata, mmsg, oimg

    def build_pose_2d(self, pose):
        pm = Pose()
        pj = {}
        pm.dim = 2
        pj["dim"] = 2
        pm.keypoints = pose[:, cfg.POSE_KEYPOINT_IMAGE_COLUMN].reshape((-1,)).tolist()
        pj["keypoints"] = pm.keypoints
        pm.confidences = pose[:, cfg.POSE_KEYPOINT_CONF_COLUMN].reshape((-1,)).tolist()
        pj["confidences"] = pm.confidences

        return pm, pj

    def build_pose_3d(self, pose):
        pm = Pose()
        pj = {}
        pm.dim = 3
        pj["dim"] = 3
        pm.keypoints = pose[:, cfg.POSE_KEYPOINT_SENSOR_COLUMN].reshape((-1,)).tolist()
        pj["keypoints"] = pm.keypoints
        pm.confidences = pose[:, cfg.POSE_KEYPOINT_CONF_COLUMN].reshape((-1,)).tolist()
        pj["confidences"] = pm.confidences

        return pm, pj

    def build_pose_3d_global(self, pose):
        pm = Pose()
        pj = {}
        pm.dim = 3
        pj["dim"] = 3
        pm.keypoints = pose[:, cfg.POSE_KEYPOINT_GLOBAL_COLUMN].reshape((-1,)).tolist()
        pj["keypoints"] = pm.keypoints
        pm.confidences = pose[:, cfg.POSE_KEYPOINT_CONF_COLUMN].reshape((-1,)).tolist()
        pj["confidences"] = pm.confidences

        return pm, pj

    def pose_visualize(self, show_img, pose):
        c = (0, 255, 255)
        pdata = pose[:, :2]
        confs = pose[:, 5]

        for d, c in zip(pdata, confs):
            kp = list(map(int, d[:2]))
            if c > 0:
                show_img = cv2.circle(show_img, kp, 4, (255, 255, 0), -1)

        for b in cfg.bones:
            show_img = self.draw_part_line(show_img, pdata, confs, b[0], b[1])

        return show_img

    def set_marker(self, header, x, y, z, cls_id):
        mm = Marker()
        mm.header = header
        mm.lifetime = rclpy.duration.Duration(seconds=0.1).to_msg()
        mm.type = Marker.SPHERE
        mm.id = cls_id
        c = cfg.colors[cls_id % len(cfg.colors)] / 255
        mm.color.r, mm.color.g, mm.color.b, mm.color.a = c[0], c[1], c[2], 1.0
        mm.scale.x, mm.scale.y, mm.scale.z = 0.1, 0.6, 0.1
        mm.pose.position.x, mm.pose.position.y, mm.pose.position.z = x, y, z
        mm.pose.orientation.w = 1.0
        mm.pose.orientation.x = 0.0
        mm.pose.orientation.y = 0.0
        mm.pose.orientation.z = 0.0

        return mm

    def build_from_targets(self, header, loc, targets, img, is_visualize):
        msg = Persons()
        msg.header = header
        msg.pose = loc
        oimg = None

        if is_visualize:
            oimg = np.copy(img)

        m_persons = []
        j_persons = []
        for target_id, t in targets.items():
            body, pose_face, imgs = t.get_latest()

            # name_id, name = t.get_name()
            name = t.consensus_name
            name_id = t.name_id[name]
            pm, pj = self.build_person_all(header, body, pose_face, [name_id, name])
            m_persons.append(pm)
            j_persons.append(pj)

            if is_visualize:
                bodyl = body.body_location
                if not np.any(np.isnan(bodyl)):
                    x, y, w, h = map(int, body.body_location)
                    oimg = self.visualize_image(
                        oimg, x, y, w, h, self.to_alphabet(name), body.instance_id
                    )
                if pose_face is not None:
                    kps = np.asarray(pose_face.pose.keypoints).reshape((-1, 2))
                    cfs = np.asarray(pose_face.pose.confidences).reshape((-1, 1))
                    p = {"keypoints": np.hstack((kps, cfs)).reshape(-1)}
                    self.pose_face_visualize(
                        oimg, p, pose_face.face_location, name_id, name
                    )

        msg.persons = m_persons

        jsondata = {}
        jsondata["timestamp"] = f"{msg.header.stamp.sec}.{msg.header.stamp.nanosec}"
        jsondata["detections"] = j_persons

        return msg, jsondata, oimg

    def set_person_info(self, header, cls_id, location, conf):
        pm = Person()
        pm.header = header
        pm.name = ""
        pm.class_id = -1
        pm.instance_id = -1
        pm.body_location = location
        return pm

    def set_person_json(self, header, cls_id, location, conf):
        pj = {}
        pj["name"] = ""
        pj["class_id"] = -1
        pj["instance_id"] = -1
        pj["body_location"] = location

        return pj

    def build_person_2d(self, header, lo_image, conf, cls_id):
        om = self.set_person_info(header, cls_id, lo_image, conf)
        oj = self.set_person_json(header, cls_id, lo_image, conf)
        return om, oj

    def set_person_info_all(self, header, body, pose_face, name):
        pm = Person()
        pm.header = header
        pm.name = name[1]
        pm.class_id = name[0]
        pm.instance_id = body.instance_id

        pm.body_location = body.body_location
        if pose_face is not None:
            pm.face_location = pose_face.face_location
            pm.face_orientation = pose_face.face_orientation
            pm.pose = pose_face.pose

        pm.body_location_sensor = body.body_location_sensor
        if pose_face is not None:
            pm.face_location_sensor = pose_face.face_location_sensor
            pm.pose_sensor = pose_face.pose_sensor

        pm.body_location_global = body.body_location_global
        if pose_face is not None:
            pm.face_location_global = pose_face.face_location_global
            pm.pose_global = pose_face.pose_global
        return pm

    def set_person_json_all(self, header, body, pose_face, name):
        pj = {}
        pj["name"] = name[1]
        pj["class_id"] = name[0]
        pj["instance_id"] = body.instance_id
        pj["body_location"] = body.body_location
        if pose_face is not None:
            pj["face_location"] = pose_face.face_location
            pj["face_orientation"] = pose_face.face_orientation
            pj["pose"] = pose_face.pose

        pj["body_location_sensor"] = body.body_location_sensor
        if pose_face is not None:
            pj["face_location_sensor"] = pose_face.face_location_sensor
            pj["pose_sensor"] = pose_face.pose_sensor

        pj["body_location_global"] = body.body_location_global
        if pose_face is not None:
            pj["face_location_global"] = pose_face.face_location_global
            pj["pose_global"] = pose_face.pose_global

        return pj

    def build_person_all(self, header, body, pose_face, name):
        om = self.set_person_info_all(header, body, pose_face, name)
        oj = self.set_person_json_all(header, body, pose_face, name)
        return om, oj

    def person_info_only(self, header, pose, face_pos, person_id, name):
        pm = Person()
        pm.header = header

        # 顔の情報
        if face_pos is not None:
            pm.class_id = person_id
            pm.name = name
            pm.face_location = face_pos  # 画像中での位置

        # 姿勢の情報
        if pose is not None:
            pm.pose.dim = 2
            pr_tmp = np.array(pose["keypoints"]).reshape((-1, 3))
            pm.pose.keypoints = pr_tmp[:, :2].reshape(-1).tolist()
            pm.pose.confidences = pr_tmp[:, 2].reshape(-1).tolist()
            pm.body_location = list(pose["bbox"])

        return pm

    def pose_face_visualize(self, show_img, pose, face_pos, person_id, name):
        c = (0, 255, 255)
        if face_pos is not None and len(face_pos) > 0:
            x, y, w, h = map(int, face_pos)
            show_img = cv2.rectangle(show_img, (x, y), (x + w, y + h), c, 2)

        if pose is not None:
            pdata = np.array(pose["keypoints"]).reshape((-1, 3))
            for d in pdata:
                kp = list(map(int, d[:2]))
                c = d[2]
                if c > 0:
                    show_img = cv2.circle(show_img, kp, 4, (255, 255, 0), -1)

            for b in cfg.bones:
                show_img = self.draw_part_line(
                    show_img, pdata[:, :2], pdata[:, 2], b[0], b[1]
                )

        return show_img

    def draw_part_line(self, img, kps, conf, i, j):
        if conf[i] > 0 and conf[j] > 0 and kps[i][0] > 0 and kps[j][0] > 0:
            k1 = list(map(int, kps[i]))
            k2 = list(map(int, kps[j]))
            img = cv2.line(img, k1, k2, (255, 255, 255), 3)
        return img
