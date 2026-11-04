import os
import subprocess
import psutil
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

import rclpy
from rclpy.time import Time
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor


class MachineStatus(Node):
    def __init__(self):
        super().__init__('machine_status')

        self.declare_parameter('report_rate', 1.0)
        self.declare_parameter('mongo_uri', "")
        self.declare_parameter('mongo_port', 0)

        timer_period = self.get_parameter('report_rate').get_parameter_value().double_value
        mongo_uri = self.get_parameter('mongo_uri').get_parameter_value().string_value
        mongo_port = self.get_parameter('mongo_port').get_parameter_value().integer_value

        self.robot_name = os.getenv("ROBOT_NAME")
        if self.robot_name is None:
            self.get_logger().error("failed to get robot name")
            return

        self.host_name = os.uname()[1]

        mongo_client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}")
        self.network_db = mongo_client["tBlackBoard"]           # 保存先のDB
        self.network_collection = self.network_db["status"]     # 保存先のコレクション

        self.timer = self.create_timer(timer_period, self.timer_callback)

    def timer_callback(self):
        self.get_logger().info("timer in")

        self.cpu_temp = self.get_cpu_temp()
        self.load_average = f"{psutil.getloadavg()[0]:.2f}"
        self.get_wifi_status()
        diskusage_used = f"{int(psutil.disk_usage('/').used / (1024 ** 3))}"
        diskusage_total = f"{int(psutil.disk_usage('/').total / (1024 ** 3))}"
        self.filesystem_used = f"{diskusage_used}/{diskusage_total}"
        svmem_free = f"{int(psutil.virtual_memory().free / (1024 ** 3))}"
        svmem_total = f"{int(psutil.virtual_memory().total / (1024 ** 3))}"
        self.mem_free = f"{svmem_free}/{svmem_total}"

        self.update_db()

    def get_cpu_temp(self):
        temps = psutil.sensors_temperatures()
        if 'k10temp' in temps:                  # AMDプロセッサのシステムで、最も適切な温度センサのため最優先とした
            for entry in temps['k10temp']:
                if entry.label == 'Tdie':       # CPUダイの実温度のため正確なので、測っていれば使うこととした
                    return entry.current
            return temps['k10temp'][0].current
        elif 'cpu-thermal' in temps:
            return temps['cpu-thermal'][0].current
        elif 'coretemp' in temps:
            return temps['coretemp'][0].current
        else:
            return None
    
    def get_wifi_status(self):
        # Linuxから通信のパラメータを取得
        connect_flg = True
        iwconfig_res = subprocess.run(["iwconfig"], capture_output=True, text=True)
        iwconfig_res_str = iwconfig_res.stdout
        self.get_logger().debug(iwconfig_res_str)

        # Wi-Fiシグナル強度の取得
        wifi_signal_string = "Signal level="
        wifi_signal_index = iwconfig_res_str.find(wifi_signal_string)   # "Signal level="検索
        if wifi_signal_index == -1:   # 見つからなかった場合
            connect_flg = False
        wifi_signal_after = iwconfig_res_str[wifi_signal_index + len(wifi_signal_string):]    # "Signal level="の直後から文字列末尾までを切り出し
        wifi_signal_split = wifi_signal_after.split()
        self.wifi_signal = wifi_signal_split[0]   # NOTE: Signal level 記載の最初の要素を信号強度として取得

        # Wi-Fi通信速度の取得
        wifi_rate_string = "Bit Rate="
        wifi_rate_index = iwconfig_res_str.find(wifi_rate_string)
        if wifi_rate_index == -1:
            connect_flg = False
        wifi_rate_after = iwconfig_res_str[wifi_rate_index + len(wifi_rate_string):]
        wifi_rate_split = wifi_rate_after.split()
        self.wifi_rate = wifi_rate_split[0]

        if not connect_flg:
            self.wifi_signal = "0"
            self.wifi_rate = "0"
        
    def update_db(self):  # DB更新
        # 最新データのみDBへ入れるため、既存のDBのデータを削除する
        self.network_collection.delete_many({"key": f"{self.host_name}_status"})

        obj = {}
        obj["key"] = self.host_name + "_status"
        obj["actor"] = self.robot_name
        obj_status = {}
        obj["status"] = obj_status
        obj_status["cpu_temp"] = self.cpu_temp
        obj_status["load_average"] = self.load_average
        obj_status["wifi_signal"] = self.wifi_signal
        obj_status["wifi_rate"] = self.wifi_rate
        obj_status["filesystem_used"] = self.filesystem_used
        obj_status["mem_free"] = self.mem_free
        obj["time"] = self.to_datetime()
        self.get_logger().info(f'key = {obj}')

        self.network_collection.insert_one(obj)     # MongoDBのコレクションにドキュメント挿入

    def to_datetime(self):
        JST = timezone(timedelta(hours=9), 'JST')
        now = datetime.now(JST)
        return now

def main():
    rclpy.init()
    node = MachineStatus()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    executor.spin()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()