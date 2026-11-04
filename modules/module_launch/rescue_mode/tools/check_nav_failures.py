#!/usr/bin/env python3
"""
check_nav_failures.py - MongoDBのナビゲーション連続失敗チェックツール

Usage:
    python3 check_nav_failures.py <mongo_uri> <mongo_port> <robot_name> [threshold]
    python3 check_nav_failures.py --init <mongo_uri> <mongo_port> <robot_name>

    mongo_uri   : MongoDBホスト名またはIP
    mongo_port  : MongoDBポート番号
    robot_name  : ロボット名 (ROBOT_NAME)
    threshold   : 連続失敗とみなす件数 (default: 3)

    --init モード:
        直近の completed なナビゲーション結果が failed なら canceled に書き換える。
        hv_watch.sh 起動直後に1回だけ呼び出すことで、
        前回稼働の failed が誤検知として引っかかるのを防ぐ。

Exit code:
    0 : 連続失敗なし（正常）
    1 : 連続失敗を検知
    2 : 引数エラー・接続エラー等
"""

import sys
from pymongo import MongoClient, DESCENDING

def init_clear_failures(mongo_uri, mongo_port, robot_name):
    """起動時に直近のfailed結果をcanceledに書き換えて誤検知を防ぐ"""
    try:
        client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}", serverSelectionTimeoutMS=3000)
        col = client["tBlackBoard"]["Actions"]

        # 直近1件を取得して failed かどうか確認
        recent = list(col.find(
            {
                "command": "navigation",
                "actor": robot_name,
                "status": {"$in": ["done", "failed", "stopped", "canceled"]},
            },
            sort=[("last_update", DESCENDING)],
            limit=1,
        ))

        if not recent:
            print("[init] No navigation history found. Nothing to clear.")
            return

        latest = recent[0]
        if latest["status"] == "failed":
            col.update_one(
                {"_id": latest["_id"]},
                {"$set": {"status": "canceled"}},
            )
            print(f"[init] Overwrote latest failed → canceled (_id={latest['_id']})")
        else:
            print(f"[init] Latest status is '{latest['status']}', no overwrite needed.")

    except Exception as e:
        print(f"[init] Error: {e}", file=sys.stderr)
        sys.exit(2)

def check_consecutive_failures(mongo_uri, mongo_port, robot_name, threshold=3):
    try:
        client = MongoClient(f"mongodb://{mongo_uri}:{mongo_port}", serverSelectionTimeoutMS=3000)
        col = client["tBlackBoard"]["Actions"]

        # 直近 threshold 件のナビゲーション（完了済み）を新しい順に取得
        recent = list(col.find(
            {
                "command": "navigation",
                "actor": robot_name,
                "status": {"$in": ["done", "failed", "stopped", "canceled"]},
            },
            sort=[("last_update", DESCENDING)],
            limit=threshold,
        ))

        if len(recent) < threshold:
            # 履歴がthreshold件未満なら判定しない
            print(f"Not enough history ({len(recent)}/{threshold}), skip.")
            return False

        statuses = [r["status"] for r in recent]
        print(f"[check_nav_failures] last {threshold} statuses: {statuses}")

        all_failed = all(s == "failed" for s in statuses)
        if all_failed:
            print(f"CONSECUTIVE FAILURES DETECTED: last {threshold} = {statuses}")
            # 最新の failed を canceled に書き換えて次回の誤検知を防ぐ
            col.update_one(
                {"_id": recent[0]["_id"]},
                {"$set": {"status": "canceled"}},
            )
            print(f"Overwrote latest failed → canceled (_id={recent[0]['_id']})")
            return True
        else:
            print(f"OK: last {threshold} = {statuses}")
            return False

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--init":
        if len(sys.argv) < 5:
            print(f"Usage: {sys.argv[0]} --init <mongo_uri> <mongo_port> <robot_name>", file=sys.stderr)
            sys.exit(2)
        init_clear_failures(sys.argv[2], int(sys.argv[3]), sys.argv[4])
        sys.exit(0)

    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <mongo_uri> <mongo_port> <robot_name> [threshold]", file=sys.stderr)
        sys.exit(2)

    mongo_uri  = sys.argv[1]
    mongo_port = int(sys.argv[2])
    robot_name = sys.argv[3]
    threshold  = int(sys.argv[4]) if len(sys.argv) >= 5 else 3

    if check_consecutive_failures(mongo_uri, mongo_port, robot_name, threshold):
        sys.exit(1)
    else:
        sys.exit(0)
