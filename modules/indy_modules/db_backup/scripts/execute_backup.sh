#!/bin/bash

SCRIPT_PATH=$(cd $(dirname $0); pwd)

HOST=$MONGO_URI
PORT=$MONGO_PORT 
DB_NAME="log"
TODAY=$(date "+%Y/%m/%d")
DATE_WEEK_AGO=$(date -d "-7 day" "+%Y/%m/%d")

BACKUP_RES=$SCRIPT_PATH/backup_db.sh $HOST $PORT $DB_NAME $TODAY
if [ $BACKUP_RES == 0 ]; then
    python3 $SCRIPT_PATH/mongo_delete_date.py $HOST $PORT $DB_NAME $DATE_WEEK_AGO
    exit 0
else
    echo "Failed dump: $TODAY"
    exit 1
fi