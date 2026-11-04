import rclpy
import numpy as np
import logging
import time
import os
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from recognition_msgs.msg import Person, Persons # type: ignore
from common_msgs.msg import StringStamped #type: ignore


def main():
    rclpy.init()
    robot_name = os.getenv('ROBOT_NAME')
    
    node = rclpy.create_node('face_tracking_publisher_dummy')
    #publisher = node.create_publisher(Persons, '/'+robot_name+'/recog/person/face', 10)
    publisher = node.create_publisher(StringStamped, '/'+robot_name+'/recog/robot_looking_target', 10)
    
    person_one = Person()
    person_one.name = 'one_up_left'
    person_one.face_location = [200.0 ,100.0 ,82.0 ,82.0] # image coordinate [x, y, w, h]
    
    person_two = Person()
    person_two.name = 'two_up_right'
    person_two.face_location= [1100.0 ,100.0 ,82.0 ,82.0]
    
    persons_list = [person_one,person_two]
    msg = Persons()
    msg.persons = persons_list
    
    st_msg = StringStamped()
    st_msg.data = '{"instance_id":1,"type":"person","class_id":0,"name":"person","location":[1.2, -0.45, 4.5]}'
    
    def timer_callback():
        node.get_logger().info('Publish face location: ' + str(st_msg.data))
        publisher.publish(st_msg)
        
    timer_period = 0.5
    timer = node.create_timer(timer_period, timer_callback)
    
    rclpy.spin(node)
    
    node.destroy_timer(timer)
    node.destroy_node()
    rclpy.shutdown()

    
if __name__ == '__main__':
    main()
        