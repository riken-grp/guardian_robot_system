import datetime
import os
import subprocess
import sys
import time

import matplotlib.pyplot as plt
import numpy as np

INTERVAL    = 1.0 # [seconds]
ANALYZE_DATA_CNT = 10
PLOT_PERIOD = 180.0 # [minutes]
TEXT_DIRECTORY_PATH = "~/.log/internet_speed_monitor"

class InternetSpeedMonitor():
    def __init__(self, ip_address):
        self.ip_address = ip_address
        self.ping_res = []
        self.analyzed_data = []
        self.directory_path = os.path.expanduser(TEXT_DIRECTORY_PATH)
        if not self.directory_path.endswith("/"):
            self.directory_path += "/"

        self.get_file_data()

    def get_file_data(self):
        data_list = []
        dt = datetime.datetime.now()
        file_name = self.get_file_name(dt)
        try:
            with open(file_name, "r") as f:
                data_list = f.readlines()
        except IOError:
            pass

        for data in data_list:
            split_data = data.split(", ")
            if split_data[2].strip() == self.ip_address:
                date_data = datetime.datetime.strptime(split_data[0], "%Y/%m/%d %H:%M:%S.%f")
                speed_data = float(split_data[1].strip())
                self.ping_res.append([date_data, speed_data])
        
        while len(self.ping_res) >= 10:
            data = self.ping_res[0: 10]
            dt = np.array(data).T[0][-1]
            data_list = np.array(data).T[1]
            self.analyzed_data.append([dt, np.min(data_list), np.max(data_list), np.median(data_list)])
            self.ping_res = self.ping_res[10:]

    def main_loop(self):
        base_time = time.time()
        next_time = 0
        ax, lines = self.initial_plot()
        while True:
            self.ping_run()
            if len(self.ping_res) % ANALYZE_DATA_CNT == 0:
                self.analyze_data()
                self.check_plot_time()
                self.plot_current(ax, lines)
            next_time = ((base_time - time.time()) % INTERVAL) or INTERVAL
            time.sleep(next_time)

    def ping_run(self):
        ping_res = subprocess.run(["ping", self.ip_address, "-c 1"], capture_output=True, text=True)
        dt = datetime.datetime.now()
        if ping_res.returncode == 0:
            ping_res_str = ping_res.stdout
            ping_res_str.split()
            for split_str in ping_res_str.split():
                if split_str[:5] == "time=":
                    time = split_str[5:]
        else:
            time = -1
        self.ping_res.append([dt, float(time)])
        file_name = self.get_file_name(dt)
        with open(file_name, "a") as f:
            f.write(dt.strftime("%Y/%m/%d %H:%M:%S.%f") + ", " + str(time) + ", " + self.ip_address + "\n")

    def get_file_name(self, dt):
        directory_name = self.directory_path + dt.strftime("%Y%m")
        if not os.path.isdir(directory_name):
            os.makedirs(directory_name)
        file_name = directory_name + "/" + dt.strftime("%m%d") + "_internet_speed.txt"
        return file_name
    
    def analyze_data(self):
        dt = datetime.datetime.now()
        data_list = np.array(self.ping_res).T[1]
        self.analyzed_data.append([dt, np.min(data_list), np.max(data_list), np.median(data_list)])
        self.ping_res = []

    def check_plot_time(self):
        dt_list = np.array(self.analyzed_data).T[0]
        for i, date in enumerate(dt_list):
            time_diff = dt_list[-1] - date
            time_diff_minutes = time_diff.total_seconds() / 60.0
            if time_diff_minutes < PLOT_PERIOD:
                break
        self.analyzed_data = self.analyzed_data[i:]

    def initial_plot(self):
        lines = [0] * 3
        if len(self.analyzed_data) != 0:
            dt_list = np.array(self.analyzed_data).T[0]
            min_list = np.array(self.analyzed_data).T[1]
            max_list = np.array(self.analyzed_data).T[2]
            med_list = np.array(self.analyzed_data).T[3]
        else:
            dt_list = [datetime.datetime.now()]
            min_list = [0]
            max_list = [0]
            med_list = [0]
        fig, ax = plt.subplots(1, 1)
        fig.autofmt_xdate()
        lines[0], = ax.plot(dt_list, min_list, label="min")
        lines[1], = ax.plot(dt_list, max_list, label="max")
        lines[2], = ax.plot(dt_list, med_list, label="med")
        ax.set_xlim([dt_list[0] - datetime.timedelta(seconds=INTERVAL), 
                     dt_list[-1] + datetime.timedelta(seconds=INTERVAL)])
        ax.set_ylim([-0.1, max(max_list) + 0.1])
        ax.set_title("internet speed to " + self.ip_address, fontsize=15)
        ax.set_xlabel("datetime")
        ax.set_ylabel("Internet Speed [ms]")
        ax.legend(loc='upper left')
        plt.pause(INTERVAL / 10.0)
        return ax, lines

    def plot_current(self, ax, lines):
        dt_list = np.array(self.analyzed_data).T[0]
        min_list = np.array(self.analyzed_data).T[1]
        max_list = np.array(self.analyzed_data).T[2]
        med_list = np.array(self.analyzed_data).T[3]
        lines[0].set_data(dt_list, min_list)
        lines[1].set_data(dt_list, max_list)
        lines[2].set_data(dt_list, med_list)
        ax.set_xlim([dt_list[0] - datetime.timedelta(seconds=INTERVAL), 
                     dt_list[-1] + datetime.timedelta(seconds=INTERVAL)])
        ax.set_ylim([-0.1, max(max_list) + 0.1])
        ax.legend(loc='upper left')
        plt.pause(INTERVAL / 10.0)


def main():
    args = sys.argv
    internet_speed_monitor = InternetSpeedMonitor(args[1])
    internet_speed_monitor.main_loop()


if __name__ == '__main__':
    main()