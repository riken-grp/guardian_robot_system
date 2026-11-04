import subprocess
import os
import socket
import threading
import time
import json
import yaml
import argparse
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta

ROBOT_NAME = os.environ.get("ROBOT_NAME")

env_mongo_uri = os.getenv("MONGO_URI")
env_mongo_port = os.getenv("MONGO_PORT")

MONGOSERVER = env_mongo_uri
MONGOPORT = int(env_mongo_port) if env_mongo_port else None
MONGO_DB = "log"
MONGO_DB_STATUS = "current_status"

BLACKBOARD_DB = "tBlackBoard"
ERROR_TOPIC = "physical_topic"
DEFAULT_ERROR_PRIORITY = 100

# Server configuration

def maybe_add_local_suffix(name):
    if name and not name.endswith(".local"):
        return name + ".local"
    return name

# HOST = 'localhost'  # Set the server host IP address or hostname
HOST = maybe_add_local_suffix(socket.gethostname())
# PORT = 12800       # Set the server port number

DEFAULT_TEST_INTERVAL = 5
TEST_INTERVAL = DEFAULT_TEST_INTERVAL

PING_THRESHOLD = 20 # value over which ping returns a "DELAY"
DISK_NEAR_THRESHOLD = 98 # percentage at which disk is near full
DISK_FULL_THRESHOLD = 100 # percentage at which disk is considered full


TEST_LSUSB = "../sh/hardware-lsusb.sh"
TEST_DEVPERMS = "../sh/hardware-devperms.sh"
TEST_PING = "../sh/network-ping-simple.sh"
TEST_DISK = "../sh/diskspace.sh"

# TEST_TYPES = {}
TEST_TYPES = { "PING":TEST_PING,
               "DEVPERMS": TEST_DEVPERMS,
               "LSUSB": TEST_LSUSB,
               "DISK": TEST_DISK }


# move to database
ROS_DOMAIN_ID = 215

# Test that we got everything we needed from the environment

def error_when_empty(**kwargs):
    for name, value in kwargs.items():
        if not value:
            raise ValueError(f"A necessary environment is empty: {name}")



# function to retrieve the test data for the current machine
def retrieve_documents():
    client = MongoClient(MONGOSERVER, MONGOPORT)
    db = client["system_monitor"]
    collection = db["hardware_config"]
    data_dict = {}
    for document in collection.find():
        document_id = str(document.get('_id'))
        if str(document.get('host')) == HOST and str(document.get('robot')) == ROBOT_NAME:
            data_dict[document_id] = document
    return data_dict

# processes the test in a particular thread
def thread_worker(interval, test):
    test_list = [TEST_TYPES[test['type']]] + test['args']
    while True:
        out, err = execute_script(test_list)
        r_o, r_e = format_result(test, out, err)
        dt = datetime.now(timezone(timedelta(hours=9)))
        ds = dt.strftime("%Y/%m/%d %H:%M:%S.%f")
        result = {"time": dt, "test": test, "out": r_o, "err": r_e}
        print(test['test'])
        print("out " + str(out) + "err " + str(err) + "r_o " + str(r_o) + "r_e " + str(r_e) )
        print("time: " + str(ds))
        print(result)
        process_test_result(result)
        time.sleep(interval)


def process_test_result(result):
    test = result['test']
    test_type = test['type']
    test_name = test['test']
    robot_name = test['robot']
    if test_type == 'PING':
        field = "ping"
        status = interpret_ping_status(result['out'], result['err'])
        vals = { "time": result['time'],
                 "robot": robot_name,
                 "test": test_name,
                 "host": HOST,
                 "target": test['args'][0],
                 "value": result['out'],
                 "status": status }
    elif test_type == 'LSUSB' or test_type == 'DEVPERMS':
        field = "hardware"
        status = interpret_hardware_status(result['out'], result['err'])
        vals = { "time": result['time'],
                 "robot": robot_name,
                 "test": test_name,
                 "host": HOST,
                 "hardware": test['args'][0],
                 "status": status }
    elif test_type == 'DISK':
        field = "disk"
        status = interpret_disk_status(result['out'], result['err'])
        vals = { "time": result['time'],
                 "robot": robot_name,
                 "test": test_name,
                 "host": HOST,
                 "hardware": test['args'][0],
                 "value": result['out'],
                 "status": status }
    else:
        vals = None
    print(f"Values: {vals}")
    if vals:
        insert_document(MONGO_DB, field, vals)
        update_status_document(MONGO_DB_STATUS, field, vals)
        if vals['status'] != "OK":
            inject_error(vals)
    return None


def run_test_loops():
    tests = retrieve_documents()
    threads = {}
    for id,test in tests.items():
        threads[test['test']] = threading.Thread(target=thread_worker, args=(int(test['frequency']), test))
        threads[test['test']].daemon = True
        threads[test['test']].start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Test program terminated.")
        

def run_debug():
    run_test_loops()
    

# Dictionaries to store the results

results = {}
results_simple = {}

def create_unit(entry):
    if entry['type'] == 'DEVPERMS':
        create_unit_DEVPERMS(entry)
    elif entry['type'] == 'LSUSB':
        create_unit_LSUSB(entry)
    else:
        return 0


#
#
#

#def thread_worker(interval):
#    while True:
#        return 0
    
def create_unit_DEVPERMS(entry):
    return 0

def thread_DEVPERMS(entry):
    while True:
        out,err = execute_script(entry["script"], entry["args"])
        print([out, err])
        
        

# Function to execute a script and capture its output
def execute_script(script_with_args):
    try:
        current_env = os.environ.copy()
        # current_env["ROS_DOMAIN_ID"] = ROS_DOMAIN_ID
        completed_process = subprocess.run(script_with_args, capture_output=True, text=True, check=True, env=current_env)
        return completed_process.stdout, completed_process.stderr
    except subprocess.CalledProcessError as e:
        return e.stdout, e.stderr


def format_result(test, stdout, stderr):
    if test['type'] == "PING":
        r_o = 0 if not stdout or stdout == '\n' else float(stdout)
    elif test['type'] == "DISK":
        r_o = 0 if not stdout else stdout
    else:
        r_o = 0 if not stdout else 1
    r_e = 0 if not stderr else 1
    return r_o, r_e


def to_datetime(t):
    s, n = t.seconds_nanoseconds()
    sn = s + n / (10 ** 9)
    dt = datetime.fromtimestamp(sn, tz=timezone(timedelta(hours=9)))
    return dt.strftime("%Y/%m/%d %H:%M:%S.%f")


def run_local_tests(server_name = HOST):
    # Get the SERVER_NAME from the environment variable
    # server_name = os.environ.get("ROS_HOSTNAME")
    # Check if the specified server is in the dictionary
    if server_name in servers:
        # Initialize result dictionary
        results[server_name] = {}
        results_simple = []
        # Iterate over the tests for the specified server
        print("On server: " + server_name)
        for test, script_with_args in servers[server_name].items():
            stdout, stderr = execute_script(script_with_args)
            # Update the dictionary with the output
            # dt = datetime.now() 
            dt = datetime.now(timezone(timedelta(hours=9)))
            ds = dt.strftime("%Y/%m/%d %H:%M:%S.%f")
            results[server_name][test] = {"stdout": stdout, "stderr": stderr}
            r_o, r_e = format_result(test, stdout, stderr)
            results_simple.append({"time": dt, "test": test, "out": r_o, "err": r_e})
            print("Test: " + test + " Has output: " + str(r_o) + " Has error: " + str(r_e))
        print(results_simple)
        return results_simple
    else:
        print(f"No tests to run for server: {server_name}")


        
# Function to insert an array of dictionaries into MongoDB
def insert_documents(database_name, collection_name, documents):
    # Connect to MongoDB - Replace 'localhost' with your MongoDB server address
    client = MongoClient(MONGOSERVER, MONGOPORT)

    # Select the database
    db = client[database_name]

    # Select the collection
    collection = db[collection_name]

    # Insert documents
    collection.insert_many(documents)

    print(f"Inserted {len(documents)} documents into {database_name}.{collection_name}")

    
# Function to insert one document into MongoDB
def insert_document(database_name, collection_name, document):
    # Connect to MongoDB - Replace 'localhost' with your MongoDB server address
    client = MongoClient(MONGOSERVER, MONGOPORT)
    # Select the database
    db = client[database_name]
    # Select the collection
    collection = db[collection_name]
    # Insert documents
    collection.insert_one(document)

# Function to update MongoDB document
def update_status_document(database_name, collection_name, document):
    client = MongoClient(MONGOSERVER, MONGOPORT)
    db = client[database_name]
    collection = db[collection_name]
    query = { 'robot': document["robot"], 'test': document["test"] }
    del document['_id']    
    update = { '$set': document }
    collection.update_one(query, update, upsert=True)
    
    
def inject_error(values_document):
    label = str(values_document["test"] + "-error").replace('-','_')
    print(label)
    client = MongoClient(MONGOSERVER, MONGOPORT)
    db = client[BLACKBOARD_DB]
    collection = db[ERROR_TOPIC]
    error_doc = { "event": label,
                  "priority": DEFAULT_ERROR_PRIORITY,
                  "inserted": values_document['time'],
                  "contents": values_document['status'],
                  "mentioned": False,
                  "last_mentioned": None }
    collection.insert_one(error_doc)    
    
# ugly here, fix later

def interpret_ping_status(output, error):
    try:
        float(output)
    except:
        return "FAIL"
    if output == 0:
        return "FAIL"
    if error == 0 and float(output) < PING_THRESHOLD:
        return "OK"
    elif error == 0:
        return "DELAY"
    else:
        return "FAIL"

def interpret_hardware_status(output, error):
    if error == 0:
        return "OK"
    else:
        return "FAIL"

def interpret_disk_status(output, error):
    try:
        int(output)
    except:
        return "FAIL"
    if int(output) >= DISK_FULL_THRESHOLD:
        return "FAIL"
    elif int(output) >= DISK_NEAR_THRESHOLD:
        return "NEAR_FULL"
    else:
        return "OK"



def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default=env_mongo_uri,
                        help="MongoDB server address (default: $MONGO_URI)")
    parser.add_argument("--port", default=env_mongo_port,
                        help="MongoDB port address (default: $MONGO_PORT)")
    args = parser.parse_args()
    config = vars(args)
    return config

if __name__ == "__main__":
#    run_debug()
    config = parse_args()
    error_when_empty(ROBOT_NAME=ROBOT_NAME, HOST=HOST, **config)
    print(f"Host: {HOST} Robot: {ROBOT_NAME}")
    print(config)
    MONGOSERVER = config['server']
    MONGOPORT = int(config['port'])
    run_test_loops()
    
