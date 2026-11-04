#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import numpy as np
import random
import cv2
from cv_bridge import CvBridge

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor

from sensor_msgs.msg import Image
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import PoseStamped 


def get_point_distance(x1, y1, x2, y2):
    l = math.sqrt((x2-x1)**2  + (y2 -y1)**2) 
    return l
    

class FinderLine(object):
    def __init__(self ):   # インスタンス生成時に自動的に呼ばれるメソッド 必須
        self.left_point = (0,0)
        self.right_point = (0,0)
        self.left_pixel = (0,0)
        self.right_pixel = (0,0)    

        self.length = 0

    def set_line(self , x1, y1, x2, y2  ,_cell_size):
        self.left_pixel = (x1,y1)
        self.right_pixel = (x2,y2)

        self.left_point = (x1 * _cell_size,  y1 * _cell_size)
        self.right_point = (x2* _cell_size,  y2 * _cell_size)
        self.length =  get_point_distance( x1, y1, x2, y2) * _cell_size

    def set_line_from_point(self , x1, y1, x2, y2  ,_cell_size):
        self.left_point = (x1,y1)
        self.right_point = (x2,y2)

        self.left_pixel = (int(x1 / _cell_size), int(  y1 / _cell_size))
        self.right_pixel = (int(x2/ _cell_size),  int(y2 / _cell_size))
        self.length =  get_point_distance( x1, y1, x2, y2) 
        

class DockTarget(object):
    def __init__(self ,_cell_size ):   # インスタンス生成時に自動的に呼ばれるメソッド 必須
        self.left_wing = FinderLine()
        self.right_wing = FinderLine()
        self.center_line =  FinderLine()
        self.intersection_point = (0,0)
        self.cell_size = _cell_size

        self.angle_rad = 0
        self.angle_deg = 0

    def set_line(self , _left_wing , _right_wing , _intersection_x , _intersection_y , angle_deg):
        self.left_wing =_left_wing
        self.right_wing = _right_wing
        self.intersection_point = ( _intersection_x ,_intersection_y)

        rot_x = _right_wing.left_point[0] - _intersection_x
        rot_y = _right_wing.left_point[1] - _intersection_y

        rad = math.radians((angle_deg + 90) / 2.0 ) 

        wing_center_x = rot_x * math.cos(rad) - rot_y *math.sin(rad)  + _intersection_x
        wing_center_y = rot_x * math.sin(rad) + rot_y *math.cos(rad)  + _intersection_y

        self.angle_rad = math.atan2(wing_center_x - _intersection_x  , -(wing_center_y - _intersection_y))
        self.angle_deg = math.degrees(self.angle_rad)      

        self.center_line.set_line_from_point(  _intersection_x ,_intersection_y ,wing_center_x, wing_center_y ,self.cell_size)


class FinderDockTarget(object):
    def __init__(self):   # インスタンス生成時に自動的に呼ばれるメソッド 必須
        self.wing_length = 250  #mm   目標形状の片翼の長さ
        self.wing_length_tolerance = 50 #mm 片翼を推定する場合の許容誤差
        self.intersection_tolerance = 150 #mm 両翼交点の許容誤差

        self.wing_angle = 135 #deg  両翼の角度
        self.wing_angle_tolerance  = 5 #deg  両翼の角度の許容誤差
        self.cell_size = 0

        self.target_candidate_list = []

    def reset_target_candidate_list(self ): 
        self.target_candidate_list = []

    def line_length_judge(self , _line = FinderLine()):
        if(self.wing_length - self.wing_length_tolerance   < _line.length    and _line.length  < self.wing_length + self.wing_length_tolerance  ):
            return True
        else:
            return False

    def line_wing_judge(self , _left_line = FinderLine() , _right_line = FinderLine()):
        x1 = _left_line.left_point[0]
        y1 = _left_line.left_point[1]
        x2 = _right_line.right_point[0]
        y2 = _right_line.right_point[1]
        point_dist = get_point_distance( x1, y1, x2, y2) 
        if(abs(point_dist) < self.intersection_tolerance ):

            if ((_left_line.right_point[0] == _left_line.left_point[0]) or
                (_right_line.right_point[0] == _right_line.left_point[0])):
                return False
            # 直線Aの傾きを計算
            slope_A =  (_left_line.right_point[1] - _left_line.left_point[1]) / (_left_line.right_point[0] - _left_line.left_point[0])
            # 直線Bの傾きを計算
            slope_B =  (_right_line.right_point[1] - _right_line.left_point[1]) / (_right_line.right_point[0] - _right_line.left_point[0])

            # 2つの直線のなす角を計算
            angle_rad = math.atan(abs((slope_B - slope_A) / (1 + slope_A * slope_B)))
            angle_deg = math.degrees(angle_rad)  

            if(abs ( self.wing_angle - angle_deg) < self.wing_angle_tolerance  or  abs( 180 - self.wing_angle  - ( angle_deg) )< self.wing_angle_tolerance ):
                # 直線Aと直線Bの交点の座標を計算
                intersection_x = (_right_line.right_point[1] - _left_line.right_point[1] + slope_A * _left_line.right_point[0]  - slope_B * _right_line.right_point[0] ) / (slope_A - slope_B)
                intersection_y = _left_line.right_point[1] + slope_A * (intersection_x -  _left_line.right_point[0])

                target_candidate = DockTarget(self.cell_size)
                target_candidate.set_line(_left_line,_right_line,intersection_x,intersection_y ,angle_deg)
                self.target_candidate_list.append(target_candidate)
                return True

        return False



class LidarMarkerFinder(Node):
    def __init__(self):
        super().__init__('lidar_marker_finder')

        self.docking_target =   FinderDockTarget()
        self.cv_bridge = CvBridge()
        
        qos_profile = rclpy.qos.QoSProfile(depth=20, reliability=rclpy.qos.ReliabilityPolicy.BEST_EFFORT,)
        self.create_subscription(LaserScan, 'rover/scan', self.sub_get_scan , qos_profile)

        self.pose_pub = self.create_publisher(PoseStamped, "auto_charge/dock_target_pose", 1)
        # self.view_pub = self.create_publisher(Image, "auto_charge/docking_image", 1)

    def sub_get_scan(self, scan):
        ranges = scan.ranges  # レーザースキャンデータの範囲を取得
        ranges = self.remove_radial_lines(ranges, scan.angle_min, scan.angle_increment)

        self.docking_target.reset_target_candidate_list()

        cell_size = 3 #(mm)
        observe_aria_width = 3000 #(mm)
        observe_aria_length  = 3000 #(mm)

        self.docking_target.cell_size = cell_size
        width =  int(observe_aria_width / cell_size)
        length  = int(observe_aria_length / cell_size)

        meter_to_cell = 1000/cell_size

        # 画像サイズと解像度の設定
        row_image = np.zeros((length , width), np.uint8)
        # line_img = np.zeros((length , width,3), np.uint8)

        # レーザースキャンデータを画像に変換
        for i in range(len(ranges)):
            if ranges[i] < scan.range_max and ranges[i] > scan.range_min:
                angle = scan.angle_min + i * scan.angle_increment
                if(angle < -3.14/2.0 or angle > 3.14/2.0):
                    x = int(width / 2 - ranges[i]*meter_to_cell * np.sin(angle) ) 
                    y = int( - ranges[i]*meter_to_cell * np.cos(angle) ) 
                    if(0<x and x < width  and 0<y and y < length  ):
                        row_image[y, x] = 255             

        #膨張縮小処理
        kernel = np.ones((3,3),np.uint8)
        dilate_image = cv2.dilate(row_image,kernel,iterations = 1)
        filtering_image = dilate_image

        #直線検出
        lines = cv2.HoughLinesP(filtering_image, rho=1, theta=np.pi/360, threshold=50, minLineLength=120/cell_size, maxLineGap=30/cell_size)
        

        #直線が検出できれば、
        line_list = [] 
        if(lines is None):
            # self.get_logger().warn("line not found")
            pass
        else:
            #設定された長さの直線のみを抽出
            for line in lines:
                x1, y1, x2, y2 = line[0]        
                _line= FinderLine()
                _line.set_line(x1, y1, x2, y2 ,cell_size )

                cont_flg = False
                for exsisting_line in line_list:
                    e_x1 = exsisting_line.left_pixel[0]
                    e_y1 = exsisting_line.left_pixel[1]
                    e_x2 = exsisting_line.right_pixel[0]
                    e_y2 = exsisting_line.right_pixel[1]
                    if (abs(e_x1 - x1) < 10 and abs(e_y1 - y1) < 10 and
                        abs(e_x2 - x2) < 10 and abs(e_y2 - y2) < 10):
                        cont_flg = True
                if cont_flg:
                    continue

                if(self.docking_target.line_length_judge(_line)):
                    line_list.append(_line)

            #抽出した直線同士を比較し、直線の交点、角度などが、設定値のものを抽出する
            for right_line in line_list:
                for left_line in line_list:
                    # if right_line == left_line:
                    #     continue
                    self.docking_target.line_wing_judge(left_line , right_line )

            #c_image = cv2.cvtColor(filtering_image, cv2.COLOR_GRAY2RGB)
            _sum_pose_data = PoseStamped()
            _sum_length = 0

            for target in self.docking_target.target_candidate_list:
                R = int(255 )
                G = int(255 * random.random())
                B = int(255 * random.random())

                target.left_wing.left_pixel

                # line_img= cv2.cvtColor(filtering_image, cv2.COLOR_GRAY2RGB)
                # line_img = cv2.line(line_img, target.left_wing.left_pixel, target.left_wing.right_pixel, (B,G,R ), 2)
                # line_img = cv2.line(line_img, target.right_wing.left_pixel, target.right_wing.right_pixel, (B,G,R ), 2)
                # line_img = cv2.line(line_img, target.center_line.left_pixel, target.center_line.right_pixel, (0,0,255 ), 1)

                _sum_length += 1.0
                _sum_pose_data.pose.position.x +=  -target.intersection_point[1] /1000.0 
                _sum_pose_data.pose.position.y +=  -target.intersection_point[0] /1000.0 + (observe_aria_width/1000.0 )/2.0
                _sum_pose_data.pose.position.z += 0

                _sum_pose_data.pose.orientation.x += target.angle_rad 


            if(_sum_length !=0):
                pub_pose_data = PoseStamped()

                pub_pose_data.header = scan.header

                pub_pose_data.pose.position.x = _sum_pose_data.pose.position.x / _sum_length
                pub_pose_data.pose.position.y = _sum_pose_data.pose.position.y / _sum_length
                pub_pose_data.pose.position.z = _sum_pose_data.pose.position.z / _sum_length

                _ave_rad = _sum_pose_data.pose.orientation.x /_sum_length
                pub_pose_data.pose.orientation.w = math.cos(-_ave_rad / 2.0) 
                pub_pose_data.pose.orientation.z = math.sin(-_ave_rad / 2.0) 

                self.pose_pub.publish(pub_pose_data)
                # #For debag
                # self.get_logger().info(f"angle: {_ave_rad} [rad]")
                # self.get_logger().info(f"{math.atan2(pub_pose_data.pose.position.y, pub_pose_data.pose.position.x)}")


            # send_image = line_img 
            # send_image = cv2.cvtColor(filtering_image, cv2.COLOR_GRAY2RGB)

            # #デバッグ用　ROSにイメージを送信する
            # publish_image = self.cv_bridge.cv2_to_imgmsg(send_image, "bgr8")
            # self.view_pub.publish(publish_image)  


    def remove_radial_lines(self, range_data, angle_min, angle_increment):
        radial_cnt = 3
        measured_range_data = []
        measured_idx = []
        remove_idx = []
        for i, val in enumerate(range_data):
            if val != np.inf:
                measured_range_data.append(val)
                measured_idx.append(i)
        theta = [angle_min + i * angle_increment for i in range(len(measured_range_data))]
        x = measured_range_data * np.cos(theta)
        y = measured_range_data * np.sin(theta)
        for i in range(len(x) - 4):
            x_range = x[i: i + radial_cnt]
            y_range = y[i: i + radial_cnt]
            # self.get_logger().info(f"x_range:{x_range}, y_range:{y_range}")
            a = ((np.dot(x_range, y_range) - y_range.sum() * x_range.sum() / radial_cnt) /
                ((x_range ** 2).sum() - x_range.sum() ** 2 / radial_cnt))
            b = (y_range.sum() - a * x_range.sum()) / radial_cnt
            distance = abs(b) / math.sqrt(math.pow(a, 2) + 1)
            if distance < 0.01:
                for k in range(radial_cnt):
                    if (i + k) not in remove_idx:
                        remove_idx.append(i + k)

        for idx in remove_idx:
            range_data[measured_idx[idx]] = np.inf
        return range_data

def main():
    rclpy.init()
    node = LidarMarkerFinder()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
