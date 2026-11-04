#!/bin/bash

if [ $# -ne 4 ]; then
    echo "Usage: backup_db.sh HOST PORT DB_NAME TODAY"
    return 1
fi

HOST=$1
PORT=$2
DB_NAME=$3
DATE=$4

BACKUP_DIR="~/mongo_backup/"

SCRIPT_PATH=$(cd $(dirname $0); pwd)

COLLECTIONS=$(python3 $SCRIPT_PATH/print_collections.py $HOST $PORT $DB_NAME)
for COLLECTION in $COLLECTIONS
do
    mongodump --db $DB_NAME --collection $COLLECTION --host $HOST --port $PORT --out $BACKUP_DIR${DATE////}\
              --query "{\"time\":{\"\$gt\":{\"\$date\":`date -d $DATE +%s`000},\"\$lte\":{\"\$date\":`date -d "1 day $DATE" +%s`000}}}"
    if [ $? == 1]; then
        rm -rf ${DATE////}/*
        return 1
    fi
done

FILE_NUM=$(ls -1 ${DATE////} | wc -l)
if [ FILE_NUM == 0]; then
    return 1
fi

return 0
