import math
import numpy as np

import rclpy
import tf2_ros
import tf2_geometry_msgs

from tf2_geometry_msgs import PointStamped, PoseStamped, Vector3Stamped,TransformStamped

class TFTransformer():
    def __init__(self, node):
        self.node = node
        self.tf_buffer = tf2_ros.buffer.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, node)

    def angle_transform(self, pose_list, rpy_list):
        x = pose_list[0]
        y = pose_list[1]
        z = pose_list[2]
        r = math.sqrt(x * x + y * y + z * z)


    def transform_position(self, pose_list, source_link, target_link):
        pose = PointStamped()
        cur_time = rclpy.time.Time().to_msg()
        pose.header.frame_id = source_link
        pose.header.stamp = cur_time
        pose.point.x = pose_list[0]
        pose.point.y = pose_list[1]
        pose.point.z = pose_list[2]
        if (self.tf_buffer.can_transform(target_link,
                                         source_link,
                                         cur_time,
                                         timeout=rclpy.duration.Duration(seconds=0.1))):
            trans_pose = self.tf_buffer.transform(pose, target_link)
        else:
            trans_pose = pose
        
        pose_x = trans_pose.point.x
        pose_y = trans_pose.point.y
        pose_z = trans_pose.point.z

        return [pose_x, pose_y, pose_z]

    def transform_angle(self, vec_list, source_link, target_link):
        vec_trans = Vector3Stamped()
        vec_trans.vector.x = vec_list[0]
        vec_trans.vector.y = vec_list[1]
        vec_trans.vector.z = vec_list[2]
        cur_time = rclpy.time.Time().to_msg()
        if (self.tf_buffer.can_transform(target_link,
                                         source_link,
                                         cur_time,
                                         timeout=rclpy.duration.Duration(seconds=0.1))):
            trans_all = self.tf_buffer.lookup_transform(target_link, source_link, cur_time)
        else:
            self.node.get_logger().debug("cannot transform")
            trans_all = TransformStamped()
            trans_all.transform.rotation.w = 1.0
            trans_all.transform.rotation.x = 0.0
            trans_all.transform.rotation.y = 0.0
            trans_all.transform.rotation.z = 0.0
        
        trans_angle = TransformStamped()
        trans_angle.transform.rotation.w = trans_all.transform.rotation.w
        trans_angle.transform.rotation.x = trans_all.transform.rotation.x
        trans_angle.transform.rotation.y = trans_all.transform.rotation.y
        trans_angle.transform.rotation.z = trans_all.transform.rotation.z

        target_vec = tf2_geometry_msgs.do_transform_vector3(vec_trans, trans_angle)
        vec_x = target_vec.vector.x
        vec_y = target_vec.vector.y
        vec_z = target_vec.vector.z

        return [vec_x, vec_y, vec_z]

    def transform_all(self, pose_list, quat_list, source_link, target_link):
        trans = PoseStamped()
        cur_time = rclpy.time.Time().to_msg()
        trans.header.frame_id = source_link
        trans.header.stamp = cur_time
        trans.pose.position.x = pose_list[0]
        trans.pose.position.y = pose_list[1]
        trans.pose.position.z = pose_list[2]
        trans.pose.orientation.w = quat_list[0]
        trans.pose.orientation.x = quat_list[1]
        trans.pose.orientation.y = quat_list[2]
        trans.pose.orientation.z = quat_list[3]
        if (self.tf_buffer.can_transform(target_link,
                                         source_link,
                                         cur_time,
                                         timeout=rclpy.duration.Duration(seconds=0.1))):
            trans_result = self.tf_buffer.transform(trans, target_link)
        else:
            self.node.get_logger().debug("cannot transform")
            trans_result = trans
        
        pose_x = trans_result.pose.position.x
        pose_y = trans_result.pose.position.y
        pose_z = trans_result.pose.position.z
        pose = [pose_x, pose_y, pose_z]
        
        quat_w = trans_result.pose.orientation.w
        quat_x = trans_result.pose.orientation.x
        quat_y = trans_result.pose.orientation.y
        quat_z = trans_result.pose.orientation.z
        quat = [quat_w, quat_x, quat_y, quat_z]

        return pose, quat

    def get_rpy_on_camera(self, pose, rpy):
        rot_face = Vector3Stamped()
        rot_face.vector.x = 1.0
        rot_face.vector.y = 0.0
        rot_face.vector.z = 0.0
        quat_on_face = self.quaternion_from_euler([rpy[0], rpy[1], rpy[2]])
        trans_face = TransformStamped()
        trans_face.transform.rotation.w = quat_on_face[0]
        trans_face.transform.rotation.x = quat_on_face[1]
        trans_face.transform.rotation.y = quat_on_face[2]
        trans_face.transform.rotation.z = quat_on_face[3]
        face_unit_pose = tf2_geometry_msgs.do_transform_vector3(rot_face, trans_face)

        face_x = pose[0]
        face_y = pose[1]
        face_z = pose[2]
        range = math.sqrt(face_x * face_x + face_y * face_y + face_z * face_z)
        camera_to_dir_pose = [range - face_unit_pose.vector.x, -face_unit_pose.vector.y, face_unit_pose.vector.z]
        unit_face = [face_x / range, face_y / range, face_z / range]

        quat_to_camera = self.vector_to_quaternion([1.0, 0.0, 0.0], unit_face)

        dir_pose = Vector3Stamped()
        dir_pose.vector.x = camera_to_dir_pose[0]
        dir_pose.vector.y = camera_to_dir_pose[1]
        dir_pose.vector.z = camera_to_dir_pose[2]
        trans = TransformStamped()
        trans.transform.rotation.w = quat_to_camera[0]
        trans.transform.rotation.x = quat_to_camera[1]
        trans.transform.rotation.y = quat_to_camera[2]
        trans.transform.rotation.z = quat_to_camera[3]
        camera_rpy = tf2_geometry_msgs.do_transform_vector3(dir_pose, trans)
        dx = camera_rpy.vector.x - face_x
        dy = camera_rpy.vector.y - face_y
        dz = camera_rpy.vector.z - face_z
        face_dir_vec = [dx, dy, dz]
        self.node.get_logger().debug('face_dir_vec :  %f, %f, %f' % (dx, dy, dz))

        return [dx, dy, dz]
    
    def vector_to_quaternion(self, base_vec, target_vec):
        base_vec = np.array(base_vec)
        target_vec = np.array(target_vec)
        q = [0.0, 0.0, 0.0, 0.0]

        crs = np.cross(base_vec, target_vec)
        leng = np.linalg.norm(np.array(crs))
        if leng > -1e-5 and leng < 1e-5:
            norm_crs = [0.0, 0.0, 0.0]
        else:
            norm_crs = crs / leng
        eps = 0.0002
        ip = np.dot(base_vec, target_vec)
        if eps > leng or 1.0 < ip:
            if ip < (eps - 1.0):
                unit2 = [-target_vec[0], target_vec[2], target_vec[0]]
                crs2 = np.cross(unit2, target_vec)
                q[0] = 0.0
                q[1] = crs2[0]
                q[2] = crs2[1]
                q[3] = crs2[2]
            else:
                q[0] = 1.0
                q[1] = 0.0
                q[2] = 0.0
                q[3] = 0.0
        else:
            e = norm_crs * math.sqrt(0.5 * (1.0 - ip))
            q[0] = math.sqrt(0.5 * (1.0 + ip))
            q[1] = e[0]
            q[2] = e[1]
            q[3] = e[2]
        return q

    def quaternion_from_euler(self, euler_list):
        roll = euler_list[0] / 2.0 * np.pi / 180.0
        pitch = euler_list[1] / 2.0 * np.pi / 180.0
        yaw = euler_list[2] / 2.0 * np.pi / 180.0
        cr = math.cos(roll)
        sr = math.sin(roll)
        cp = math.cos(pitch)
        sp = math.sin(pitch)
        cy = math.cos(yaw)
        sy = math.sin(yaw)

        quat = [0] * 4
        quat[0] = cy * cp * cr + sy * sp * sr   # w
        quat[1] = cy * cp * sr - sy * sp * cr   # x
        quat[2] = sy * cp * sr + cy * sp * cr   # y
        quat[3] = sy * cp * cr - cy * sp * sr   # z

        return quat

    def euler_from_quaternion(self, quat_list):
        w = quat_list[0]
        x = quat_list[1]
        y = quat_list[2]
        z = quat_list[3]
        sr_cp = 2 * (w * x + y * z)
        cr_cp = 1 - 2 * (x * x + y * y)
        roll = math.atan2(sr_cp, cr_cp)
        sp = 2 * (w * y - z * x)
        pitch = math.asin(sp)
        sy_cp = 2 * (w * z + x * y)
        cy_cp = 1 - 2 * (y * y + z * z)
        yaw = math.atan2(sy_cp, cy_cp)

        euler = [0] * 3
        euler[0] = roll * 180.0 / np.pi
        euler[1] = pitch * 180.0 / np.pi
        euler[2] = yaw * 180.0 / np.pi

        return euler
