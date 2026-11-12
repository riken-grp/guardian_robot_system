import rclpy
import os
from std_msgs.msg import Empty

robot_name = os.getenv("ROBOT_NAME")

rclpy.init()
node = rclpy.create_node("stop_pub")
publisher = node.create_publisher(Empty, f"/{robot_name}/rover/stop", 10)
msg = Empty()
publisher.publish(msg)
print("stop publish")
rclpy.shutdown()