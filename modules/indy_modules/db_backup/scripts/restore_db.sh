#!/bin/bash

HOST=$MONGO_URI
PORT=$MONGO_PORT 
DB_NAME="ReadOnlyLog"
DATE=$1
BACKUP_DIR="~/mongo_backup/"

mongorestore --host $HOST --port $PORT --db $DB_NAME $BACKUP_DIR$DATE/log/
