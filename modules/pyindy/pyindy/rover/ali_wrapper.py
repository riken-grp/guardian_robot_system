#!/usr/bin/python3
import numpy as np
import signal
import time
import datetime

import requests
import json
import os

import base64
import cv2

headers = {'content-type': 'application/json'}

class ali_wrapper():
    def __init__(self, uri, robot_name):
        self.uri=uri
        self.name=robot_name
    ###
    def reset(self):
        print(self.name + ": " + self.uri + ' reset')
        data=json.dumps('')
        resp = requests.post(self.uri+'/v2/error/reset', data=data, headers=headers)
        return json.loads(resp.text)
    ###
    def stop(self):
        print(self.name + ": " + self.uri + ' stop')
        data=json.dumps('')
        resp = requests.post(self.uri+'/v2/taskset/abort', data=data, headers=headers)
        return json.loads(resp.text)
    ###
    def go_coordinate(self, x, y, th=0.0):
        print(self.name + ": " + ' coordinate ' + str([x, y, th]))
        position=json.dumps({'x': x, "y": y, "theta": th, "type":0})
        resp = requests.post(self.uri+'/v2/task/move_position', data=position, headers=headers)
        return json.loads(resp.text)
    ###
    def set_max_velocity(self, v):
        if (v > 0.5 or v < 0.1):
            print("set_max_velocity: invalid value: " + str(v))
            return False
        params={"data":v}
        resp = requests.post(self.uri+'/v2/settings/max_speed', json=params)
        cs=requests.get(self.uri+'/v2/settings')
        return json.loads(cs.text)
    ###
    def rotate(self, angle, v=30):
        direction=0
        if angle < 0:
            direction=1
        params={"cmds":[{
            "cmdType":400,
            "arg":{
                "angle":abs(angle),
                "velocity":v,
                "direction":direction
                },
            }]}
        resp = requests.post(self.uri+'/v2/taskset/direct_exec', json=params)
        print(params)
        return json.loads(resp.text)
    ###
    def move_straight(self, dist, v=0.3):
        direction=0
        if dist < 0:
            direction=1
        params={"cmds":[{
            "cmdType":410,
            "arg":{
                "distance":abs(dist),
                "velocity":v,
                "direction":direction
                },
            }]}
        resp = requests.post(self.uri+'/v2/taskset/direct_exec', json=params)
        print(params)
        return json.loads(resp.text)
    ###
    def set_pose(self, x, y, th=0.0):
        params={"x":x, "y":y, "theta":th}
        resp = requests.post(self.uri+'/v2/initial_position', json=params)
        return json.loads(resp.text)
    ###
    def get_map(self):
        resp=requests.get(self.uri+'/v2/map/maps')
        maps=resp.json()['lists']
        print(maps)
        fnames=[]
        for m in maps:
            params = {'mapId':m['id']}
            resp=requests.get(self.uri+'/v2/map',json=params)
            data=json.loads(resp.text)
            img_text=base64.b64decode(resp.json()['map'])
            img_encoded_int=np.frombuffer(img_text,dtype=np.uint8)
            img=cv2.imdecode(img_encoded_int, cv2.IMREAD_COLOR)
            fname=('map-'+m['name']+'.png').replace(' ', '-')
            fnames.append(fname)
            cv2.imwrite(fname, img)
        return fnames
####################################################################################
     
####################################################################################
import sys
if __name__ == '__main__':
    args=sys.argv
    if len(args) <2:
        print(args[0], "command", "options")
        exit(0)
    ali=ali_wrapper('http://192.168.4.2:9085', 'indy4')
    #
    command=args[1]
    if command == 'set_max_velocity':
        print(ali.set_max_velocity(int(args[2])))
    elif command == 'go':
        print(ali.go_coordinate(float(args[2]),float(args[3])))
    elif command == 'stop':
        print(ali.stop())
    elif command == 'reset':
        print(ali.reset())
    elif command == 'rotate':
        print(ali.rotate(float(args[2])))
    elif command == 'forward':
        print(ali.move_straight(float(args[2])))
    elif command == 'map':
        print(ali.get_map())
    else:
        print("invalid command")

    
    
