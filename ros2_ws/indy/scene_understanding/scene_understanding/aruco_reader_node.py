#!/usr/bin/env python3
import cv2
import numpy as np
import rclpy
from cv2 import aruco
from cv_bridge import CvBridge
from geometry_msgs.msg import TransformStamped
from rclpy import qos
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, CompressedImage
from tf2_ros import TransformBroadcaster

from .image_processing_node import IMAGE_QOS


def rvec_to_quaternion(rvec):
    """Rodrigues rotation vector -> unit quaternion (x, y, z, w).

    Computed directly from the axis-angle form, which is numerically stable
    for all angles (the trace-based formula qw = sqrt(1 + trace(R)) / 2
    divides by ~0 near 180 deg).
    """
    rvec = np.asarray(rvec, dtype=np.float64).reshape(3)
    theta = np.linalg.norm(rvec)
    if theta < 1e-12:
        return 0.0, 0.0, 0.0, 1.0
    axis = rvec / theta
    s = np.sin(theta / 2.0)
    q = np.array([axis[0] * s, axis[1] * s, axis[2] * s, np.cos(theta / 2.0)])
    if q[3] < 0:  # keep w >= 0 (same rotation)
        q = -q
    return float(q[0]), float(q[1]), float(q[2]), float(q[3])


class ArucoTfBroadcaster(Node):
    def __init__(self):
        super().__init__("aruco_tf_broadcaster")

        self.declare_parameter("size", 4)
        self.declare_parameter("number", 50)
        self.declare_parameter("marker_size", 0.05)
        size = self.get_parameter("size").value
        number = self.get_parameter("number").value
        marker_size = self.get_parameter("marker_size").value

        # ArUco設定
        if size == 4 and number == 50:
            aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        elif size == 4 and number == 250:
            aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_250)
        else:
            aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        parameters = aruco.DetectorParameters()
        self.aruco_detector = aruco.ArucoDetector(aruco_dict, parameters)
        self.marker_length = marker_size

        # 可視化画像Publisher
        self.vis_pub = self.create_publisher(
            CompressedImage,
            "vis_topic",
            qos_profile=qos.qos_profile_system_default,
        )

        # 購読
        self.create_subscription(
            CompressedImage,
            "in_color_topic",
            self.image_callback,
            qos_profile=IMAGE_QOS,
        )
        self.camera_info_sub = self.create_subscription(
            CameraInfo,
            "cinfo_topic",
            self.camera_info_callback,
            qos_profile=qos.qos_profile_system_default,
        )

        # TF Broadcaster
        self.br = TransformBroadcaster(self)

        # OpenCV Bridge
        self.bridge = CvBridge()

        # カメラパラメータ (camera_infoから更新される)
        self.camera_matrix = None
        self.dist_coeffs = None

    def camera_info_callback(self, msg: CameraInfo):
        # カメラ行列
        K = np.array(msg.k).reshape(3, 3)
        self.camera_matrix = K.astype(np.float32)
        # 歪みパラメータ
        self.dist_coeffs = np.array(msg.d, dtype=np.float32)
        self.get_logger().info("Camera info received.")
        # このトピックは一度受け取れば良いので購読解除してもOK
        self.destroy_subscription(self.camera_info_sub)

    def image_callback(self, msg: CompressedImage):
        if self.camera_matrix is None or self.dist_coeffs is None:
            return  # camera_infoが来るまで待機

        frame = self.bridge.compressed_imgmsg_to_cv2(msg, desired_encoding="bgr8")
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        corners, ids, _ = self.aruco_detector.detectMarkers(gray)
        is_visualize = self.vis_pub.get_subscription_count() > 0

        if ids is not None:
            rvecs, tvecs, _ = self.estimatePoseSingleMarkers(
                corners, self.marker_length, self.camera_matrix, self.dist_coeffs
            )

            for rvec, tvec, marker_id, corner in zip(
                rvecs, tvecs, ids.flatten(), corners
            ):
                t = TransformStamped()
                t.header.stamp = msg.header.stamp
                t.header.frame_id = msg.header.frame_id
                t.child_frame_id = f"aruco_marker_{marker_id}"

                # 平行移動
                t.transform.translation.x = float(tvec[0][0])
                t.transform.translation.y = float(tvec[0][1])
                t.transform.translation.z = float(tvec[0][2])

                # 回転ベクトルをクォータニオンに変換
                qx, qy, qz, qw = rvec_to_quaternion(rvec)

                t.transform.rotation.w = float(qw)
                t.transform.rotation.x = float(qx)
                t.transform.rotation.y = float(qy)
                t.transform.rotation.z = float(qz)

                # TF配信
                self.br.sendTransform(t)

                # self.get_logger().info(f"Published TF for Marker {marker_id}")

                if not is_visualize:
                    continue
                # ---- 可視化描画 ----
                aruco.drawDetectedMarkers(frame, [corner])
                cv2.drawFrameAxes(
                    frame,
                    self.camera_matrix,
                    self.dist_coeffs,
                    rvec,
                    tvec,
                    self.marker_length * 0.5,
                )

        # 検出画像をCompressedImageに変換してPublish (購読者がいる場合のみ)
        if is_visualize:
            self._publish_visualization(msg.header, frame)

    def _publish_visualization(self, header, show_img):
        success, encoded_image = cv2.imencode(
            ".jpg", show_img, [cv2.IMWRITE_JPEG_QUALITY, 90]
        )
        if not success:
            self.get_logger().error("Failed to encode image")
            return

        mimg = CompressedImage()
        mimg.header = header
        mimg.format = "jpeg"
        mimg.data = encoded_image.tobytes()
        self.vis_pub.publish(mimg)

    def estimatePoseSingleMarkers(self, corners, marker_size, mtx, dist):
        marker_points = np.array(
            [
                [-marker_size / 2, marker_size / 2, 0],
                [marker_size / 2, marker_size / 2, 0],
                [marker_size / 2, -marker_size / 2, 0],
                [-marker_size / 2, -marker_size / 2, 0],
            ],
            dtype=np.float32,
        )
        trash = []
        rvecs = []
        tvecs = []
        for c in corners:
            success, rvec, tvec = cv2.solvePnP(
                marker_points, c, mtx, dist, False, flags=cv2.SOLVEPNP_IPPE_SQUARE
            )
            rvecs.append(rvec)
            tvecs.append([tvec])
            trash.append(success)
        return np.array(rvecs), np.array(tvecs), np.array(trash)


def main(args=None):
    rclpy.init(args=args)
    node = ArucoTfBroadcaster()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
