#!/usr/bin/python3

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor


from std_msgs.msg import String
import os
import json
from pathlib import Path

from pyindy.grp_tts import tts_from_gtts as gTTS
from pyindy.grp_tts import tts_from_hoya as hTTS
from pyindy.grp_tts import tts_from_http_mp3 as mp3TTS
from pyindy.grp_tts import tts_from_http_wav as wavTTS
from pyindy.grp_tts import playMP3
from pyindy.mongo import UtteranceManager as mngdb
from pyindy.mongo import PersonaDBManager as PDBM
from pyindy.mongo import DialogueHistoryManager


class polling_tts_node(Node):
    def __init__(self, robot_name='none'):
        super().__init__('TTS_say_from_MongoDB')
        # 
        print("Start a TTS node for " + robot_name)
        self.robot_name=robot_name
        #
        self.declare_parameter("mongo_port", 0)
        self.mongo_port = self.get_parameter("mongo_port").get_parameter_value().integer_value
        self.get_logger().info("mongo_port: " + str(self.mongo_port))
        #
        self.declare_parameter("mongo_uri", "")
        self.mongo_uri = self.get_parameter("mongo_uri").get_parameter_value().string_value
        self.get_logger().info("mongo_uri: " + self.mongo_uri)
        #
        self.mpub = self.create_publisher(String, "robot/action_ctl", 10)
        self.rmpub = self.create_publisher(String, "robot/action_cond", 10)
        self.msub = self.create_subscription(String, "robot/action_ctl", self.msg_callback, 10)
        #
        timer_period = 0.1
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.mng=mngdb(self.mongo_uri,self.mongo_port,self.robot_name)
        self.dhm = DialogueHistoryManager(
            self.mongo_uri, self.mongo_port, self.robot_name
        )
        self.remaining_time=0.0
        self.dt=timer_period
        #############################################################
        personadb=PDBM(self.mongo_uri, self.mongo_port)
        persona=personadb.get_voice_params()
        self.get_logger().info("Persona: " + str(persona))
        channel=os.environ.get("VOICE_CH", "both")
        self.channel=channel
        if persona['type']=='gtts':
            self.tts=gTTS(name=self.robot_name, rate=persona['params']['rate'], ch=channel)
        elif persona['type']=='hoya':
            self.tts=hTTS(name=self.robot_name, tts_rate=persona['params']['rate'],url=persona['server'], ch=channel)
        else:
            self.tts=mp3TTS(name=self.robot_name, ch=channel)
        #
        self.mng.insert({'text': self.robot_name + " TTS ノードを初期化しました"})
        self.utter=self.mng.get_next()
        self.mng.set_status(self.utter['_id'],'is_playing')
        #
        self.dhm_inserted=False
        self.p, stat=self.say(self.utter)
        if self.p == False:
            self.mng.set_status(self.utter['_id'],'failed')
        self.get_logger().info("start. ")
        self.get_logger().info(" num of canceled. " + str(self.mng.cancel_all()))
        self.get_logger().info(" num of stopped. " + str(self.mng.clear_playing()))
        self.get_logger().info(" channel. " + self.channel)
    #####################################################################
    def action_ctl_pub(self, text):
        msg=String()
        msg.data=text
        self.mpub.publish(msg)
        #
    def action_cond_pub(self, text):
        msg=String()
        msg.data=text
        self.rmpub.publish(msg)
    #####################################################################
    def say(self, utter):
        utext=utter['option']
        if 'file' in utext.keys():
            if Path(utext['file']).is_file():
                p, stats=playMP3(utext['file'])
            else:
                p=False
                stats='File not found'
            return p, stats
        self.get_logger().info("mongo_uri: " + self.mongo_uri)
        self.get_logger().info("    text= " + json.dumps(utext))
        self.get_logger().info("    channel. " + self.channel)
        if len(utext['text']) > 300:
            utext['text']='入力音声が長すぎます。'
        self.dhm_inserted=False
        p, stat = self.tts.say(utext)
        self.get_logger().info("    start. id == " +str(utter['_id']) + json.dumps(stat))
        data={}
        data['speak']=utext['text']
        data['duration']=stat['duration']
        self.action_ctl_pub(json.dumps(data))
        return p, stat
    #
    def timer_callback(self):
        if self.p == False:
            self.utter=self.mng.get_next()
            if not self.utter == False:
                self.mng.set_status(self.utter['_id'],'is_playing')
                self.p, stat=self.say(self.utter)
                self.remaining_time=stat['duration']
                if self.p == False:
                    self.mng.set_status(self.utter['_id'],'failed')
        else:
            if self.p.is_playing():
                self.action_cond_pub(f'{self.robot_name}: speaking, remaining time: {self.remaining_time}')
                self.remaining_time=self.remaining_time-self.dt
                if self.remaining_time < 1.0 and not self.dhm_inserted:
                    self.dhm.insert(self.robot_name, self.utter['option']['text'])
                    self.dhm_inserted=True
            if not self.p.is_playing():
                self.mng.set_status(self.utter['_id'],'done')
                self.p = False
                self.get_logger().info("finishied. id == " + str(self.utter['_id']))
    # 
    def msg_callback(self, msg):
        if msg.data == 'stop':
            if self.p != False:
                self.p.stop()
                self.get_logger().info("stopped. id == " + str(self.utter['_id']))
                self.mng.set_status(self.utter['_id'],'stopped')
                self.p = False
            else:
                self.get_logger().warn("was not played.")

def main():
    rclpy.init()
    robot_name=os.getenv("ROBOT_NAME")
    node = polling_tts_node(robot_name)
    #
    exec=MultiThreadedExecutor()
    exec.add_node(node)
    try:
        exec.spin()
    except KeyboardInterrupt:
        print("Exit: Ctrl + C")
    exec.shutdown()
    node.destroy_node()

if __name__ == '__main__':
    main()

