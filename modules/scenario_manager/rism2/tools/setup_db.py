"""
RISM を動かすのに最低限必要な設定と、サンプルのシナリオを DB に入れる

  uv run python tools/setup_db.py --host db.example.local --robot-id myrobot \\
      --llm-url http://llm.example.local:8001/v1 --llm-model <モデル名>

入れるもの（samples/ の JSON）:
  設定DB（--config-host / --config-port の rism_configs）
    rism_config: 全体の設定（無いときだけ入れる）
    robot_list: --robot-id のロボットの設定
    demo_list: --demo-id のデモの設定（どのシナリオDBを使うか）
  シナリオDB（--scenario-host / --scenario-port の --scenario-db。ロボットの DB と同じサーバ）
    scenarios / interruption_subscenarios: サンプルのシナリオ（見回り、音声対話、充電、制御フロー、ジェネレータ）
    knowledge: KnowledgeEventGenerator のサンプルの知識

同じ名前（knowledge は title）の文書が既にあれば入れない。--update を付けると中身を置き換える（_id は保つ）。
サンプルの中の "@名前" は、その名前のシナリオ／サブシナリオの ID に置き換える。
"{robot_id}" などは、コマンドの引数の値に置き換える。
書き込む前にシナリオをスキーマで検査し、合わなければ何も書かずに終わる。
"""
import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rism2.schema_validator import ScenarioSchemaValidator  # noqa: E402

SAMPLES = ROOT / "samples"
LEGACY_CONFIG_PORT = 9000  # 古い RISM の設定DB。書き込まない
DUMMY_ID = "0" * 24


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="localhost", help="MongoDB のホスト（設定DBとロボットDBが同じサーバのとき）")
    p.add_argument("--config-host", help="設定DBのホスト（既定: --host）")
    p.add_argument("--scenario-host", help="シナリオDBと観測・アクションDB（ロボットDB）のホスト（既定: --host）。"
                                           "robot_list と demo_list にもこのホストを書く")
    p.add_argument("--config-port", type=int, default=9100, help="設定DB（rism_configs）のポート")
    p.add_argument("--config-db", default="rism_configs", help="設定DBの名前（試すときだけ変える）")
    p.add_argument("--scenario-port", type=int, default=9110, help="シナリオDBと観測・アクションDB（tBlackBoard）のポート")
    p.add_argument("--scenario-db", default="demo_configs", help="シナリオDBの名前")
    p.add_argument("--robot-id", required=True, help="ロボットのID（例: indy3e）。ROSのトピック名にも使う")
    p.add_argument("--name-alias", help="ロボットの表示名（既定: robot-id の先頭を大文字にしたもの）")
    p.add_argument("--demo-id", help="デモのID（既定: <robot-id>_demo）。main.py の --demo に渡す")
    p.add_argument("--llm-url", default="http://localhost:8001/v1", help="LLM サーバの URL")
    p.add_argument("--llm-model", default="indy-instruct", help="LLM のモデル名")
    p.add_argument("--only", choices=["config", "scenarios", "knowledge"], action="append",
                   help="入れるものを絞る（複数指定可）。既定は全部")
    p.add_argument("--update", action="store_true", help="同じ名前の文書があれば置き換える")
    p.add_argument("--dry-run", action="store_true", help="何を入れるか表示するだけで、書き込まない")
    args = p.parse_args(argv)
    args.config_host = args.config_host or args.host
    args.scenario_host = args.scenario_host or args.host
    return args


def placeholders(args) -> Dict[str, Any]:
    return {
        "robot_id": args.robot_id,
        "name_alias": args.name_alias or args.robot_id[:1].upper() + args.robot_id[1:],
        "demo_id": args.demo_id or f"{args.robot_id}_demo",
        "db_host": args.scenario_host,
        "db_port": args.scenario_port,
        "scenario_db": args.scenario_db,
        "llm_url": args.llm_url,
        "llm_model": args.llm_model,
    }


def fill(value: Any, values: Dict[str, Any]) -> Any:
    """文字列の {名前} を置き換える。文字列全体が {名前} なら値の型（ポート番号の int など）のまま入れる"""
    if isinstance(value, dict):
        return {k: fill(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, values) for v in value]
    if isinstance(value, str):
        for name, replacement in values.items():
            token = "{" + name + "}"
            if value == token:
                return replacement
            value = value.replace(token, str(replacement))
    return value


def refs(value: Any) -> List[str]:
    """"@名前" の参照をすべて集める"""
    if isinstance(value, dict):
        return [r for v in value.values() for r in refs(v)]
    if isinstance(value, list):
        return [r for v in value for r in refs(v)]
    return [value[1:]] if isinstance(value, str) and value.startswith("@") else []


def resolve(value: Any, ids: Dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: resolve(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, ids) for v in value]
    if isinstance(value, str) and value.startswith("@") and value[1:] in ids:
        return ids[value[1:]]
    return value


def load_json(rel: str) -> Any:
    return json.loads((SAMPLES / rel).read_text(encoding="utf-8"))


def load_scenarios(values) -> List[Tuple[str, str, Dict[str, Any]]]:
    """(コレクション, スキーマの種類, 文書) のリスト"""
    out = []
    for folder, collection, kind in (("scenarios", "scenarios", "scenario"),
                                     ("subscenarios", "interruption_subscenarios", "subscenario")):
        for path in sorted((SAMPLES / folder).glob("*.json")):
            out.append((collection, kind, fill(load_json(f"{folder}/{path.name}"), values)))
    return out


def check_samples(docs, validator) -> List[str]:
    """参照をダミーのIDにしてスキーマで検査し、サンプル同士の参照先があるかも確かめる"""
    names = {d["name"] for _, _, d in docs}
    problems = []
    for _, kind, doc in docs:
        dummy = resolve(doc, {r: DUMMY_ID for r in refs(doc)})
        problems += [f"{doc['name']}: {e}" for e in validator.errors(dummy, kind)]
    return problems, names


def upsert(collection, key: str, doc: Dict[str, Any], update: bool, dry_run: bool) -> str:
    """同じ key の文書が無ければ入れ、あれば update のときだけ置き換える。何をしたかを返す"""
    existing = collection.find_one({key: doc[key]})
    if existing and not update:
        return "skip (exists)"
    if dry_run:
        return "would replace" if existing else "would insert"
    if existing:
        collection.replace_one({"_id": existing["_id"]}, doc)
        return "replaced"
    collection.insert_one(copy.deepcopy(doc))
    return "inserted"


def setup_config(args, values, client) -> None:
    db = client[args.config_db]
    print(f"== 設定DB {args.config_host}:{args.config_port}/{args.config_db}")
    # rism_config は1件だけ（main.py は最初の1件を読む）
    existing = db.rism_config.find_one()
    if existing and not args.update:
        result = "skip (exists)"
    elif args.dry_run:
        result = "would replace" if existing else "would insert"
    elif existing:
        db.rism_config.replace_one({"_id": existing["_id"]}, load_json("config/rism_config.json"))
        result = "replaced"
    else:
        db.rism_config.insert_one(load_json("config/rism_config.json"))
        result = "inserted"
    print(f"  rism_config: {result}")
    robot = fill(load_json("config/robot.json"), values)
    print(f"  robot_list {robot['robot_id']}: {upsert(db.robot_list, 'robot_id', robot, args.update, args.dry_run)}")
    demo = fill(load_json("config/demo.json"), values)
    print(f"  demo_list {demo['demo_id']}: {upsert(db.demo_list, 'demo_id', demo, args.update, args.dry_run)}")


def setup_scenarios(args, values, client) -> bool:
    db = client[args.scenario_db]
    docs = load_scenarios(values)
    problems, _ = check_samples(docs, ScenarioSchemaValidator())
    if problems:
        print("サンプルがスキーマに合わないので、シナリオは書き込みません:")
        for problem in problems:
            print("  " + problem)
        return False
    print(f"== シナリオDB {args.scenario_host}:{args.scenario_port}/{args.scenario_db}")
    for collection, _, doc in docs:
        print(f"  {collection} {doc['name']}: {upsert(db[collection], 'name', doc, args.update, args.dry_run)}")
    if args.dry_run:
        return True
    # "@名前" を、DB にある同じ名前の文書（サンプル以外も含む）の ID に置き換える
    ids = {d["name"]: str(d["_id"]) for c in ("scenarios", "interruption_subscenarios")
           for d in db[c].find({}, {"name": 1})}
    for collection, _, doc in docs:
        stored = db[collection].find_one({"name": doc["name"]})
        missing = [r for r in refs(stored) if r not in ids]
        if missing:
            print(f"  ! {doc['name']}: 参照先が見つかりません: {missing}")
        resolved = resolve(stored, ids)
        if resolved != stored:
            db[collection].replace_one({"_id": stored["_id"]}, resolved)
    return True


def setup_knowledge(args, client) -> None:
    db = client[args.scenario_db]
    print(f"== 知識 {args.scenario_host}:{args.scenario_port}/{args.scenario_db}.knowledge")
    for entry in load_json("knowledge.json"):
        print(f"  {entry['title']}: {upsert(db.knowledge, 'title', entry, args.update, args.dry_run)}")


def main(argv=None) -> int:
    args = parse_args(argv)
    only = set(args.only or ["config", "scenarios", "knowledge"])
    if "config" in only and args.config_port == LEGACY_CONFIG_PORT and args.config_db == "rism_configs":
        print(f"ポート {LEGACY_CONFIG_PORT} は古い RISM の設定DBなので書き込みません")
        return 1
    values = placeholders(args)
    ok = True
    if "config" in only:
        setup_config(args, values, MongoClient(args.config_host, args.config_port))
    if "scenarios" in only:
        ok = setup_scenarios(args, values, MongoClient(args.scenario_host, args.scenario_port)) and ok
    if "knowledge" in only:
        setup_knowledge(args, MongoClient(args.scenario_host, args.scenario_port))
    if not args.dry_run and ok:
        print(f"\n起動: uv run main.py --robots {args.robot_id} --demo {values['demo_id']}"
              f" --host {args.config_host} --port {args.config_port}")
        print("サンプルの移動先（navigation の座標）と充電ステーションの位置は、使う場所に合わせて直してください")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
