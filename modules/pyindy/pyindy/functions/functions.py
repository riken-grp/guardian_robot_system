import json
import numpy as np
import os
import sys

########
def is_json(myjson):
    try:
        json_object = json.loads(myjson)
    except ValueError as e:
        return False
    return json_object

########
def limit11(x):
    x[np.where(x>1.0)]=1.
    x[np.where(x<-1.0)]=-1.
    print(x)
    return x

########
def is_named_pipe(pipe_path):
    if os.path.exists(pipe_path):
        if os.path.isfile(pipe_path):
            print(f"{pipe_path} exists, but it is a file.")
            return False
        if os.path.isdir(pipe_path):
            print(f"{pipe_path} exists, but it is a directory.")
            return False
        if os.path.islink(pipe_path):
            print(f"{pipe_path} exists, but it is a link.")
            return False
        if os.path.ismount(pipe_path):
            print(f"{pipe_path} exists, but it is a mount.")
            return False
        return True
    else:
        print(f"{pipe_path} does not exist.")
        print(f"  Execute mkfifo {pipe_path} to make the pipe")
        return False

if __name__ == '__main__':
    print(is_named_pipe(sys.argv[1]))
