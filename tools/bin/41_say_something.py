#!/usr/bin/env python3

import os
from pyindy.mongo import ActionManager
from argparse import ArgumentParser

def say_something(text):
    hostname = os.getenv("MONGO_URI")
    port = os.getenv("MONGO_PORT")
    robot_name = os.getenv("ROBOT_NAME")
    am = ActionManager(hostname, port, robot_name)
    com_list = {}
    com_list["speak"] = {"text": text}
    ids = am.insert_many(com_list)
    print(ids)

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument('text', help='話させたい内容')
    args = parser.parse_args()

    say_something(args.text)
