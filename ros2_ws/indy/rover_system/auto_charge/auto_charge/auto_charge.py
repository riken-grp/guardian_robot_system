import os
import math
import time

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy import qos

from std_msgs.msg import Empty, Bool, String
from geometry_msgs.msg import PoseStamped, Twist
from sensor_msgs.msg import BatteryState

class AutoCharge(Node):
    def __init__(self):
        super().__init__('auto_charge_node')

        self.robot_name = os.getenv("ROBOT_NAME")
        if self.robot_name is None:
            self.get_logger().error("failed to get robot name")
            return

        self.now_docking = False    #docking処理中か否か
        self.now_sequence = 0       #現在のシーケンスを示す
        self.last_traget_time = 0.0     #充電ステーションが最後に見えた時間
        self.target_finding_time = 3.0      #充電ステーションが最後に見えてからのタイムアウト時間
        self.delta_x = 0        #充電ステーションから見たロボットのｘ座標　別途取得
        self.delta_y = 0        #充電ステーションから見たロボットのｙ座標　別途取得
        self.delta_y_history = []  #delta_yの履歴（過去5回分）
        self.delta_y_history_size = 5  #平均化するサンプル数
        self.follow_yaw = 0     #ターゲットの方向　充電ステーションのｙ座標と目標位置より計算
        self.diff_angle = 0     #充電ステーションから見たロボットの角度偏差　別途計算
        self.battery_charge_state = False   #充電状態
        self.end_length_retry = 0.5    #retryするときの前進距離
        self.end_length_coarse_induction = 0.25      #荒誘導　終了距離
        self.end_length_precision_induction = 0.355   #精密誘導停止距離　最終停止距離
        self.max_cmd_w = 0.3    #最大旋回速度
        self.min_cmd_w = 0.005    #最小旋回速度
        self.retry_cmd_v = 0.2        #コース誘導時最大並進速度
        self.max_near_coarse_cmd_v = 0.1      #コース誘導時最大並進速度
        self.precision_cmd_v = 0.05        #精密誘導時最大並進速度
        self.precision_min_cmd_v = 0.005   #精密誘導時最小並進速度
        self.precision_cmd_w = 0.06        #精密誘導時最大旋回角度
        self.max_follow_angle = 1.0     #目標までの最大許容角度
        self.max_delta_y = 0.5     #コース誘導時のロボットのy座標方向のズレの許容値
        self.tolerance_delta_y = 0.03     #位置偏差閾値
        self.coarse_tolerance_delta_y = 0.1  #荒誘導終了時の左右ズレ許容値
        self.retry_count = 0       #リトライ回数
        self.max_retry_count = 5           #最大リトライ回数
        self.precision_runnning = False   #精密誘導中かどうか
        self.precision_start_time = 0.0   #精密誘導開始時刻
        self.precision_timeout = 15.0     #精密誘導のタイムアウト時間
        self.coarse_close_backup_done = False  #荒誘導で近すぎた際の後退完了フラグ
        self.coarse_backing_up = False  #荒誘導でバックアップ中フラグ
        self.cancel_requested = False   #外部からのドッキング中止要求
        self.docking_start_time = 0.0   #ドッキング開始時刻
        self.docking_timeout = 180.0    #ドッキング全体のタイムアウト時間
                                        #（リトライ上限で止まらない経路の保険。
                                        #  最大リトライ5回分の所要時間に余裕を見た値）

        docking_cb_group = MutuallyExclusiveCallbackGroup()
        get_pose_cb_group = MutuallyExclusiveCallbackGroup()
        timer_cb_group = MutuallyExclusiveCallbackGroup()

        self.stop_pub = self.create_publisher(Empty, 'rover/stop', 10)
        self.cmd_vel_pub = self.create_publisher(Twist, 'rover/cmd_vel', 10)
        self.dock_status_pub = self.create_publisher(Bool, 'auto_charge/in_docking_process', 10)
        self.dock_start_pub = self.create_publisher(Empty, 'auto_charge/dock_start', 10)
        self.robot_from_target_pub = self.create_publisher(PoseStamped, 'auto_charge/robot_pose_from_target', 10)
        # For debag
        # self.value_pub = self.create_publisher(Twist, 'test_value', 10)

        self.action_sub = self.create_subscription(String, "robot/action_ctl", self.action_cb, 10)
        self.buttery_sub = self.create_subscription(BatteryState, "rover/battery", self.battery_cb, qos.qos_profile_sensor_data)
        self.dock_start_sub = self.create_subscription(Empty, 'auto_charge/dock_start', self.dock_start_cb , 
                                                       10, callback_group=docking_cb_group)
        # 中止要求はドッキング処理中にも受け取る必要があるため、
        # docking_cb_group（ループで占有される）とは別のグループで受ける
        self.dock_cancel_sub = self.create_subscription(Empty, 'auto_charge/dock_cancel', self.dock_cancel_cb, 10)
        self.target_pose_sub = self.create_subscription(PoseStamped, 'auto_charge/dock_target_pose', self.target_pose_cb, 
                                                        10, callback_group=get_pose_cb_group)

        self.timer = self.create_timer(0.1, self.timer_callback, callback_group=timer_cb_group)

    def action_cb(self, msg):
        if msg.data == "battery charge":
            pub_msg = Empty()
            self.dock_start_pub.publish(pub_msg)

    def dock_cancel_cb(self, msg):
        if self.now_docking:
            self.get_logger().warn("Docking cancel requested")
        self.cancel_requested = True

    def target_pose_cb(self, msg):
        x = -msg.pose.position.x
        y = -msg.pose.position.y
        diff_angle_from_robot = 2*math.asin(msg.pose.orientation.z)
        self.delta_x = x * math.cos(-diff_angle_from_robot) - y * math.sin(-diff_angle_from_robot)
        
        # delta_yの生値を計算
        delta_y_raw = x * math.sin(-diff_angle_from_robot) + y * math.cos(-diff_angle_from_robot)
        
        # 履歴に追加
        # ドッキング終了時に別スレッドから self.delta_y_history が差し替えられても
        # 平均計算が壊れないよう、ローカル参照で扱う
        history = self.delta_y_history
        history.append(delta_y_raw)
        if len(history) > self.delta_y_history_size:
            history.pop(0)  # 古い値を削除
        
        # 平均値を計算
        self.delta_y = sum(history) / len(history)
        
        self.follow_yaw = math.atan2(msg.pose.position.y, msg.pose.position.x)
        self.diff_angle = -diff_angle_from_robot
        self.last_traget_time = self.get_clock().now().nanoseconds * 1e-9
        
        # ターゲットから見たロボット位置を配信（回転行列で変換済み）
        robot_from_target = PoseStamped()
        robot_from_target.header = msg.header
        robot_from_target.pose.position.x = self.delta_x
        robot_from_target.pose.position.y = self.delta_y
        robot_from_target.pose.position.z = 0.0
        robot_from_target.pose.orientation.w = math.cos(self.diff_angle / 2.0)
        robot_from_target.pose.orientation.z = math.sin(self.diff_angle / 2.0)
        self.robot_from_target_pub.publish(robot_from_target)
        
        # For debag
        # test_value = Twist()
        # test_value.linear.x = self.delta_x
        # test_value.linear.y = self.delta_y
        # test_value.linear.z = self.follow_yaw
        # test_value.angular.x = self.diff_angle
        # self.value_pub.publish(test_value)

    def battery_cb(self, msg):
        cur = msg.current
        if cur > 0.0:
            self.battery_charge_state = False
        else:
            self.battery_charge_state = True

    def dock_start_cb(self, msg):
        # ドッキング処理中の場合は終了
        if self.now_docking:
            self.get_logger().warn("Running docking process")
            return

        # ドッキング処理中の場合は終了
        if self.battery_charge_state:
            self.get_logger().warn("Charging now")
            return

        # ドッキング開始
        # 待機中に届いていた中止要求は、今回のドッキングには持ち越さない
        self.cancel_requested = False
        self.docking_start_time = self.get_clock().now().nanoseconds * 1e-9
        self.now_docking = True
        self.now_sequence = 1

        while self.now_docking:
            # 充電状態であれば終了
            if self.battery_charge_state:
                self.get_logger().info("docking complete")
                self.now_docking = False
                break

            # 外部から中止を要求された場合は終了
            if self.cancel_requested:
                self.get_logger().warn("Docking canceled")
                self.now_docking = False
                break

            # 全体のタイムアウト
            # リトライ上限では止まらない経路（後退できずシーケンス100に留まる等）に対する
            # 最終的な保険。開始経路によらず必ずここで自力復帰する
            if (self.check_time_diff(self.docking_start_time) > self.docking_timeout):
                self.get_logger().error(
                    f"Docking failed: overall timeout ({self.docking_timeout:.0f}s) exceeded")
                self.now_docking = False
                break

            # 充電ステーションが見つからない場合は終了
            if (self.check_time_diff(self.last_traget_time) > self.target_finding_time):
                self.get_logger().warn("Could not find charging station")
                self.now_docking = False
                break

            # ドッキング処理
            if(self.now_sequence == 1):
                self.get_logger().debug("start_up")
                self.start_up_docking()
            elif(self.now_sequence == 2):
                self.get_logger().debug("coarse_induction")
                self.coarse_induction()
            elif(self.now_sequence == 3):
                self.get_logger().debug("check_before_final")
                self.check_before_final_induction()
            elif(self.now_sequence == 4):
                self.get_logger().debug("precision")
                self.precision_induction()
            elif(self.now_sequence == 100):
                self.get_logger().debug("retry")
                self.retry_approach()
            else:
                self.get_logger().warn("Failed to docking station by bad sequence")
                self.now_docking = False
            time.sleep(0.1)

            if (self.retry_count > self.max_retry_count):
                self.get_logger().error(
                    f"Docking failed: retry limit ({self.max_retry_count}) exceeded")
                self.now_docking = False

        # 成否によらず、必ずローバを停止させてから内部状態を初期化する。
        # ここを通さずに抜けると最後の速度指令が残り続けるため、終了処理は
        # ループ内ではなくこの1箇所に集約している。
        self.stop_move()
        self.precision_runnning = False
        self.coarse_close_backup_done = False
        self.coarse_backing_up = False
        self.delta_y_history = []
        self.cancel_requested = False
        self.retry_count = 0
        self.now_sequence = 0

    def start_up_docking(self):
        self.stop_move()
        self.coarse_close_backup_done = False  # 荒誘導の後退フラグをリセット
        self.coarse_backing_up = False  # バックアップ中フラグもリセット

        self.now_sequence += 1

    def coarse_induction(self):
        cmd_w = self.calc_cmd_w()
        
        # ターゲットが後方視野から外れそうな場合は旋回を制限（見失い防止）
        # follow_yawが小さい（前方に近い）場合は旋回を抑制
        abs_follow_yaw = abs(self.follow_yaw)
        if abs_follow_yaw < 2.0:  # 約115度以内（前方寄り）なら旋回を抑制
            cmd_w_limit = 0.15  # 通常より小さい旋回速度制限
            if abs(cmd_w) > cmd_w_limit:
                cmd_w = cmd_w_limit if cmd_w > 0 else -cmd_w_limit
            self.get_logger().debug(f"Target near front view boundary, limiting rotation: follow_yaw={self.follow_yaw:.3f}")
        
        abs_delta_y = abs(self.delta_y)
        distance_threshold = self.end_length_coarse_induction + self.end_length_precision_induction
        backup_target_distance = self.end_length_retry + self.end_length_precision_induction + 0.3  # retry_approachと同じ距離
        
        # バックアップモードの処理
        if not self.coarse_close_backup_done:
            # バックアップ開始判定：近い＋左右がずれている
            if abs(self.delta_x) < distance_threshold and abs_delta_y >= self.coarse_tolerance_delta_y:
                self.coarse_backing_up = True
            
            # バックアップ実行中
            if self.coarse_backing_up:
                if abs(self.delta_x) < backup_target_distance:
                    # まだ目標距離に達していない → 継続
                    cmd_v = self.retry_cmd_v * 0.7
                    cmd_w = self.calc_cmd_w_from_follow_yaw(self.follow_yaw)
                    self.get_logger().info(f"Backing up: delta_x={self.delta_x:.3f}, target={backup_target_distance:.3f}")
                    self.move(cmd_v, cmd_w)
                    return
                else:
                    # 目標距離に達した → バックアップ完了
                    self.coarse_close_backup_done = True
                    self.coarse_backing_up = False
                    self.get_logger().info(f"Backup complete at {self.delta_x:.3f}m, resuming normal approach")
        
        # 通常の距離制御
        if abs(self.delta_x) < distance_threshold:
            # 終了距離以内
            if abs_delta_y < self.coarse_tolerance_delta_y:
                # 左右のズレも許容範囲内 → 次のフェーズへ
                self.stop_move()
                self.now_sequence += 1
                self.get_logger().debug(f"Coarse induction complete: delta_x={self.delta_x:.3f}, delta_y={self.delta_y:.3f}")
                return
            else:
                # 近いが左右がずれている。
                # その場旋回では横ズレ(delta_y)が変化せず条件も変わらないため、
                # ここに留まると永久に抜けられない。下がり直してやり直す。
                self.retry_count += 1
                self.now_sequence = 100
                self.stop_move()
                self.get_logger().warn(
                    f"Close but misaligned, retry {self.retry_count}/{self.max_retry_count}: "
                    f"delta_y={self.delta_y:.3f}")
                return
        else:
            # まだ遠い → 通常の前進制御
            if abs_delta_y > self.coarse_tolerance_delta_y:
                # ズレが大きい → ほぼその場旋回（前進速度を大幅に低減）
                cmd_v = -self.max_near_coarse_cmd_v * 0.8 * (1 - 1.0 * abs(cmd_w / self.max_cmd_w))
                self.get_logger().debug(f"Large lateral deviation: delta_y={self.delta_y:.3f}, reducing forward speed")
            else:
                # ズレが小さい → 通常の前進
                cmd_v = -self.max_near_coarse_cmd_v * (1 - 1.0 * abs(cmd_w / self.max_cmd_w))
        
        self.move(cmd_v, cmd_w)

    def calc_cmd_w(self):
        now_angle = self.diff_angle
        return self.angle_p_contorol(now_angle)

    def angle_p_contorol(self , now_angle):
        abs_delta_y = abs(self.delta_y)
        if(abs_delta_y >= self.max_delta_y):
            target_angle = self.max_follow_angle
            self.get_logger().debug(f"large delta_y: {abs_delta_y}, {target_angle}")
        elif(self.tolerance_delta_y <= abs_delta_y < self.max_delta_y):
            ratio = (abs_delta_y - self.tolerance_delta_y) / (self.max_delta_y - self.tolerance_delta_y)
            target_angle = self.max_follow_angle * (-ratio * ratio + 2* ratio)
            self.get_logger().debug(f"med delta_y: {abs_delta_y}, {target_angle}")
        else:
            target_angle = 0.0
        
        cmd_w = target_angle * self.delta_y / abs(self.delta_y) - now_angle
        self.get_logger().debug(f"high x:{self.delta_x}, y:{self.delta_y}, diff_angle:{now_angle}, target_angle:{target_angle}, cmd_w:{cmd_w}")

        if(0.0 < cmd_w < self.min_cmd_w):
            cmd_w = self.min_cmd_w
        if(0.0 > cmd_w > self.min_cmd_w):
            cmd_w = -self.min_cmd_w

        if(cmd_w > self.max_cmd_w ):
            cmd_w = self.max_cmd_w 
        if(cmd_w < -self.max_cmd_w ):
            cmd_w = -self.max_cmd_w 

        return cmd_w

    def check_before_final_induction(self):
        if((abs( self.delta_y) < self.tolerance_delta_y ) ):
            self.stop_move()
            self.now_sequence += 1
        else:
            self.retry_count += 1
            self.now_sequence = 100

    def precision_induction(self):
        if not self.precision_runnning:
            self.precision_start_time = self.get_clock().now().nanoseconds * 1e-9
            self.precision_runnning = True
        if (self.check_time_diff(self.precision_start_time) > self.precision_timeout):
            # リトライへ移るので、この回は速度指令を出さずに抜ける
            self.get_logger().warn("Precision induction timed out, retrying")
            self.retry_count += 1
            self.now_sequence = 100
            self.precision_runnning = False
            return
        follow_yaw = self.follow_yaw
        cmd_v  = -self.precision_cmd_v * (self.delta_x - self.end_length_precision_induction) / (self.end_length_coarse_induction)
        cmd_v = min(cmd_v, -self.precision_min_cmd_v)
        cmd_w = self.calc_cmd_w_from_follow_yaw(follow_yaw)
        self.move(cmd_v, cmd_w)
        if(abs(self.delta_x) < self.end_length_precision_induction or self.battery_charge_state == True):
            self.stop_move()
            self.precision_runnning = False
    
    def calc_cmd_w_from_follow_yaw(self, follow_yaw):
        if(follow_yaw >= 0.0):
            cmd_w =  follow_yaw - math.pi
            cmd_w = max(cmd_w, -self.precision_cmd_w)
        else:
            cmd_w = follow_yaw + math.pi
            cmd_w = min(cmd_w, self.precision_cmd_w)
        return cmd_w

    def retry_approach(self):
        follow_yaw = self.follow_yaw
        # リトライ距離より近い場合のみバック、それ以外は荒誘導からやり直し
        if(abs(self.delta_x) < self.end_length_retry + self.end_length_precision_induction):
            cmd_v  = self.retry_cmd_v
            cmd_w = self.calc_cmd_w_from_follow_yaw(follow_yaw)
            self.move(cmd_v, cmd_w)
        else:
            # 遠い位置からのリトライ → 荒誘導に戻る
            self.now_sequence = 1
        
        # 十分に前進したら荒誘導に戻る
        if(abs(self.delta_x) > self.end_length_retry + self.end_length_precision_induction + 0.3):
            self.stop_move()
            self.now_sequence = 1
            self.get_logger().info("Retry complete, returning to coarse induction")

    def move(self, v, w):
        send_msg = Twist()
        send_msg.linear.x = v
        send_msg.angular.z = w
        self.cmd_vel_pub.publish(send_msg)

    def stop_move(self):
        stop_msg = Empty()
        self.stop_pub.publish(stop_msg)
        self.move(0.0, 0.0)

    def check_time_diff(self, time):
        return self.get_clock().now().nanoseconds * 1e-9 - time

    def timer_callback(self):
        pub_msg = Bool()
        pub_msg.data = self.now_docking
        self.dock_status_pub.publish(pub_msg)

def main():
    rclpy.init()
    node = AutoCharge()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
