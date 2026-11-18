#!/usr/bin/python3
import rclpy
import os
import time
from std_msgs.msg import Empty

robot_name = os.getenv("ROBOT_NAME")

rclpy.init()
node = rclpy.create_node("stop_pub")
publisher = node.create_publisher(Empty, f"/{robot_name}/rover/stop", 10)

# 受信側(rover_wrapper)が見つかる前に送ると届かないため、最大3秒待ってから送る
deadline = time.time() + 3.0
while publisher.get_subscription_count() == 0 and time.time() < deadline:
    time.sleep(0.1)
if publisher.get_subscription_count() == 0:
    print(f"warning: no subscriber on /{robot_name}/rover/stop")

msg = Empty()
publisher.publish(msg)
print("stop publish")
time.sleep(0.5)  # 送信完了を待ってから終了する
rclpy.shutdown()
