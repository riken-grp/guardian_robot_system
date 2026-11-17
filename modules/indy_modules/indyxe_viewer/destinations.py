"""「部屋を見に行く」の行き先 (MongoDB に保存し, 画面はここから読む)

ドキュメントの形式 (既定: demo_configs.room_checker_destinations.
    シナリオ定義と同じ DB. main.py は --scenario-db-host/--scenario-db-port の場所を読む):
    {"label": "Alice",                     # ボタンに出す名前 (一意)
     "text": "Aliceの部屋を見てきて",       # ロボットに聞かせる言葉 (省略時は "<label>の部屋を見てきて")
     "order": 1,                           # 並び順 (小さい順. 省略時は最後)
     "enabled": true}                      # false ならボタンを出さない (省略時は true)

管理用コマンド (DB の場所は main.py と同じ引数で指定する):
    uv run destinations.py --db-port 9130 list
    uv run destinations.py --db-port 9130 add Alice [--text ...] [--order 1]
    uv run destinations.py --db-port 9130 remove Bob
    uv run destinations.py --db-port 9130 import destinations.json [--replace]
    uv run destinations.py --db-port 9130 export > destinations.json
"""
import argparse
import json
import sys
import threading
import time

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, MongoClient

DEFAULT_COLLECTION = "room_checker_destinations"
CACHE_TTL = 2.0  # 閲覧者の数だけ DB に問い合わせないよう, 一覧を使い回す (秒)


def default_text(label):
    return f"{label}の部屋を見てきて"


class Destinations:
    """行き先の読み出し. メソッドはスレッドプールから同時に呼ばれる"""

    def __init__(self, host, port, db_name, collection=DEFAULT_COLLECTION):
        self._collection = MongoClient(host, port, serverSelectionTimeoutMS=3000)[db_name][collection]
        self._lock = threading.Lock()
        self._cache = None  # (取得時刻, 一覧)

    def list(self):
        """有効な行き先 ([{id, label, text}], 並び順)"""
        with self._lock:
            if self._cache is not None and time.monotonic() - self._cache[0] < CACHE_TTL:
                return self._cache[1]
        docs = [doc for doc in self._collection.find({"enabled": {"$ne": False}}) if doc.get("label")]
        # order の無いものは最後に (Mongo の昇順では null が先頭に来るので Python で並べる)
        docs.sort(key=lambda doc: (doc.get("order") is None, doc.get("order") or 0, doc["_id"]))
        items = [
            {"id": str(doc["_id"]), "label": doc["label"], "text": doc.get("text") or default_text(doc["label"])}
            for doc in docs
        ]
        with self._lock:
            self._cache = (time.monotonic(), items)
        return items

    def get(self, destination_id):
        """有効な行き先 1 件 (無ければ None). 一覧のキャッシュではなく DB の今の値を見る"""
        try:
            oid = ObjectId(destination_id)
        except (InvalidId, TypeError):
            return None
        doc = self._collection.find_one({"_id": oid, "enabled": {"$ne": False}})
        if doc is None or not doc.get("label"):
            return None
        return {"id": str(doc["_id"]), "label": doc["label"], "text": doc.get("text") or default_text(doc["label"])}


# ---- 管理用コマンド ----
def _parse_args(argv):
    parser = argparse.ArgumentParser(description="「部屋を見に行く」の行き先を MongoDB で管理する")
    parser.add_argument("--db-host", default="localhost", help="MongoDB (RISM) のホスト (既定: localhost)")
    parser.add_argument("--db-port", type=int, required=True, help="MongoDB (RISM) のポート番号 (例: 9110)")
    parser.add_argument("--db-name", default="demo_configs", help="DB 名 (既定: demo_configs)")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help=f"コレクション名 (既定: {DEFAULT_COLLECTION})")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="行き先を一覧表示する")
    add = sub.add_parser("add", help="行き先を追加する (同じ label があれば, 指定した項目だけ更新して有効にする)")
    add.add_argument("label", help="ボタンに出す名前")
    add.add_argument("--text", help="ロボットに聞かせる言葉 (既定: <label>の部屋を見てきて)")
    add.add_argument("--order", type=int, help="並び順 (既定: 新規なら最後, 既存なら変えない)")
    add.add_argument("--disabled", action="store_true", help="ボタンを出さない")
    remove = sub.add_parser("remove", help="行き先を削除する")
    remove.add_argument("label")
    imp = sub.add_parser("import", help="JSON ファイル (ドキュメントの配列) から追加・更新する. order を省くとファイルの順になる")
    imp.add_argument("file")
    imp.add_argument("--replace", action="store_true", help="ファイルに無い行き先を削除する")
    sub.add_parser("export", help="JSON で標準出力に書き出す")
    return parser.parse_args(argv)


def _upsert(collection, doc):
    fields = {k: doc[k] for k in ("label", "text", "order", "enabled") if doc.get(k) is not None}
    return collection.update_one({"label": doc["label"]}, {"$set": fields}, upsert=True)


def main(argv=None):
    args = _parse_args(argv)
    collection = MongoClient(args.db_host, args.db_port, serverSelectionTimeoutMS=3000)[args.db_name][args.collection]
    target = f"{args.db_host}:{args.db_port}/{args.db_name}.{args.collection}"

    if args.command in ("list", "export"):
        docs = list(collection.find({}, {"_id": 0}).sort([("order", ASCENDING), ("label", ASCENDING)]))
        if args.command == "export":
            json.dump(docs, sys.stdout, ensure_ascii=False, indent=2)
            print()
            return
        print(f"# {target} ({len(docs)} 件)")
        for doc in docs:
            mark = " " if doc.get("enabled", True) else "x"
            print(f"[{mark}] {doc.get('order', '-')!s:>3}  {doc['label']}  →  {doc.get('text') or default_text(doc['label'])}")
        return

    if args.command == "add":
        if args.order is None and collection.find_one({"label": args.label}) is None:
            last = collection.find_one({"order": {"$ne": None}}, sort=[("order", -1)])
            args.order = (last["order"] + 1) if last else 1
        _upsert(collection, {"label": args.label, "text": args.text, "order": args.order, "enabled": not args.disabled})
        print(f"{target}: {args.label} を登録しました")
    elif args.command == "remove":
        result = collection.delete_one({"label": args.label})
        print(f"{target}: {args.label} を{'削除しました' if result.deleted_count else '見つけられませんでした'}")
    elif args.command == "import":
        with open(args.file, encoding="utf-8") as f:
            docs = json.load(f)
        for i, doc in enumerate(docs, 1):
            _upsert(collection, {"order": i, "enabled": True, **doc})
        removed = 0
        if args.replace:
            removed = collection.delete_many({"label": {"$nin": [doc["label"] for doc in docs]}}).deleted_count
        print(f"{target}: {len(docs)} 件を登録しました" + (f", {removed} 件を削除しました" if removed else ""))


if __name__ == "__main__":
    main()
