#!/usr/bin/python3

import os
from pyindy.mongo import ActionManager
hostname = os.getenv("MONGO_URI")
port = os.getenv("MONGO_PORT")
robot_name = os.getenv("ROBOT_NAME")
am=ActionManager(hostname, port, robot_name)
res=am.cancel_all()
print(res)

