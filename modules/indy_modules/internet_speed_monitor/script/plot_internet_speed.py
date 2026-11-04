import datetime
import sys
import os

import matplotlib.pyplot as plt

TEXT_DIRECTORY_PATH = "~/.log/internet_speed_monitor"

def get_file_data(ip_address, start_period, end_period):
    line_data_list = []
    data_list = []
    date_list = []

    start_date = start_period.date()
    end_date = end_period.date()
    date_end_flg = False
    while not date_end_flg:
        date_list.append(start_date)
        if start_date == end_date:
            date_end_flg = True
        start_date += datetime.timedelta(days=1)

    directory_path = os.path.expanduser(TEXT_DIRECTORY_PATH)
    if not directory_path.endswith("/"):
        directory_path += "/"

    for date in date_list:
        line_data_list = []
        file_name = directory_path + date.strftime("%Y%m") + "/" + date.strftime("%m%d") + "_internet_speed.txt"
        try:
            with open(file_name, "r") as f:
                line_data_list = f.readlines()
        except IOError:
            pass

        for data in line_data_list:
            split_data = data.split(", ")
            if split_data[2].strip() == ip_address:
                date_data = datetime.datetime.strptime(split_data[0], "%Y/%m/%d %H:%M:%S.%f")
                speed_data = float(split_data[1].strip())
                data_list.append([date_data, speed_data])

    return data_list


def str_to_datetime(datetime_str):
    return datetime.datetime.strptime(datetime_str, "%Y/%m/%d/%H:%M")


def get_period_data(data_list, start_period, end_period):
    dt_list = []
    speed_list = []
    for data in data_list:
        if (data[0] > start_period and data[0] < end_period):
            dt_list.append(data[0])
            speed_list.append(data[1])
    if len(dt_list) == 0:
        print("Data is nothing from " + 
              start_period.strftime("%Y/%m/%d/%H:%M") + 
              " to " + end_period.strftime("%Y/%m/%d/%H:%M"))
        sys.exit()
    return dt_list, speed_list


def plot_period_data(dt_list, speed_list):
    fig, ax = plt.subplots(1, 1)
    fig.autofmt_xdate()
    ax.tick_params(direction="in")
    ax.plot(dt_list, speed_list)
    ax.set_xlabel("datetime")
    ax.set_ylabel("Internet Speed [ms]")
    plt.show()


def main():
    try:
        args = sys.argv
        ip_address = args[1]
        start_period = str_to_datetime(args[2])
        end_period = str_to_datetime(args[3])
    except:
        print("Please input argument: ip_address start_time(yyyy/mm/dd/hh:mm) end_time(yyyy/mm/dd/hh:mm)")     
        sys.exit()
    data_list = get_file_data(ip_address, start_period, end_period)
    dt_list, speed_list = get_period_data(data_list, start_period, end_period)
    plot_period_data(dt_list, speed_list)

if __name__ == '__main__':
    main()