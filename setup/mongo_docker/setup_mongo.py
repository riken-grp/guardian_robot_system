#!/usr/bin/env python3
"""Indy の MongoDB（設定DB とロボットDB）を対話で用意する

  ./setup_mongo.sh                                          # 対話で聞く
  ./setup_mongo.sh --answers deploy/<ロボット名>/install_answers.json   # 前回の答えでやり直す（起動後の DB への投入も）
  ./setup_mongo.sh --compose-only                           # compose ファイルを作るだけ

することは次のとおり。環境変数（mongo.env など）を手で書く必要はない。
  1. rism2 の tools/install.py と同じ質問で、MongoDB の docker compose ファイルを作る
     Indy 用に、キャッシュ上限とログのローテーションを docker-compose.indy.yml で足す（.env の COMPOSE_FILE で読む）
  2. Indy で使う値（LLM・音声サーバなど）を聞く
  3. MongoDB が起動していれば、DB に入れる（書き込む前に内容を見せて確かめる）
     - 設定DB : RISM2 の設定とサンプルのシナリオ（rism2 の tools/setup_db.py）、
                ロボット側の設定（rism_configs.robot_list への追記、rism_configs.common）
     - ロボットDB: 標準データ（default_data/）
  4. ロボット・サーバの ~/indy.env に書く値と、シナリオの起動方法を出す
"""
import argparse
import json
import os
import re
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RISM2 = REPO / "modules" / "scenario_manager" / "rism2"
sys.path[:0] = [str(RISM2 / "tools"), str(RISM2 / "src")]

import install  # noqa: E402  rism2/tools/install.py（GRP のまま使う）
from install import Answers, Prompter  # noqa: E402

DEFAULT_DATA = HERE / "default_data"            # ロボットDB に入れる標準データ（<db>.<collection>.json）
CONFIG_DATA = HERE / "default_data_config"      # 設定DB に入れるロボット側の設定
INDY_ANSWERS = "indy_answers.json"
INDY_COMPOSE = "docker-compose.indy.yml"

# 対話で聞くプレースホルダ（__名前__）。Enter で飛ばしたものは置き換えずに残す
PLACEHOLDERS = [
    ("EMBED_HOST", "埋め込み API のホスト（robot_config.system_parameters の memory / llm_responder）"),
    ("TTS_HOST", "音声合成サーバのホスト（persona.Voice。type が hoya のとき使用）"),
    ("ADIN_SERVER", "音声認識の入力（adintool）サーバの IP（robot_config.system_parameters の asr）"),
    ("AUDIO_IP", "音声の送り先の IP（robot_config.system_parameters の ros_audio_tracker）"),
    ("GOOGLE_ASR_SERVER", "Google 音声認識中継サーバの IP（rism_configs.robot_list の google_asr）"),
]
# 秘密情報は答えのファイルに保存せず、入れるときに毎回聞く
SECRETS = [("OPENWEATHERMAP_TOKEN", "OpenWeatherMap の API キー（rism_configs.common。天気の話題で使用）")]


@dataclass
class IndyAnswers:
    """Indy で足す答え（indy_answers.json に保存する）"""
    cache_gb: float = 1.0
    values: Optional[Dict[str, str]] = None   # プレースホルダ名 → 値

    def __post_init__(self):
        self.values = self.values or {}


# ---------------------------------------------------------------- compose（Indy 用の追加）

def compose_dirs(a: Answers) -> Dict[Path, List[install.MongoService]]:
    """compose ファイルのあるフォルダ → そのファイルで動かす MongoDB"""
    out = Path(a.output_dir)
    config, robot = install.mongo_services(a)
    if not a.new_config:
        return {out: [robot]}
    if a.same_server:
        return {out: [config, robot]}
    return {out / "config": [config], out / "robot": [robot]}


def indy_compose(mongos: List[install.MongoService], cache_gb: float) -> str:
    lines = [
        "# setup_mongo.py が作ったファイル。install.py が作った compose に、Indy 用の設定を足す",
        "# （同じフォルダの .env の COMPOSE_FILE で読むので、docker compose コマンドに -f は要らない）",
        "#   - WiredTiger のキャッシュ上限（mongod は既定でメモリの約半分を使うため）",
        "#   - コンテナのログのローテーション",
        "x-logging: &logging",
        "  driver: json-file",
        "  options:",
        "    max-size: \"10m\"",
        "    max-file: \"3\"",
        "",
        "services:",
    ]
    for m in mongos:
        lines += [
            f"  {m.name}:",
            f"    command: [\"--replSet\", \"rs0\", \"--bind_ip_all\", \"--port\", \"{m.port}\","
            f" \"--wiredTigerCacheSizeGB\", \"{cache_gb:g}\"]",
            "    logging: *logging",
        ]
    return "\n".join(lines) + "\n"


def write_indy_files(a: Answers, ia: IndyAnswers) -> List[Path]:
    written = []
    compose_names = [n for n in install.build_compose(a) if n.endswith(".yml")]
    for folder, mongos in compose_dirs(a).items():
        base = next(Path(n).name for n in compose_names if (Path(a.output_dir) / n).parent == folder)
        (folder / INDY_COMPOSE).write_text(indy_compose(mongos, ia.cache_gb), encoding="utf-8")
        written.append(folder / INDY_COMPOSE)
        env = folder / ".env"
        text = env.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^COMPOSE_FILE=.*\n", "", text)
        env.write_text(text + f"# Indy 用の設定（{INDY_COMPOSE}）も読む\nCOMPOSE_FILE={base}:{INDY_COMPOSE}\n",
                       encoding="utf-8")
    path = Path(a.output_dir) / INDY_ANSWERS
    path.write_text(json.dumps(asdict(ia), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append(path)
    return written


def start_commands(a: Answers) -> List[str]:
    dirs = list(compose_dirs(a))
    if not a.new_config:
        return [f"（{a.robot_host} で）{dirs[0]} をコピーして、その中で docker compose up -d"]
    if a.same_server:
        return [f"cd {dirs[0]} && docker compose up -d"]
    return [f"（{a.config_host} で）{dirs[0]} をコピーして、その中で docker compose up -d",
            f"（{a.robot_host} で）{dirs[1]} をコピーして、その中で docker compose up -d"]


# ---------------------------------------------------------------- 対話

def ask_indy(p: Prompter, a: Answers, base: IndyAnswers) -> IndyAnswers:
    print("\n== Indy")
    while True:
        reply = p.text("MongoDB のキャッシュ上限（GB。1台のサーバで複数動かすときは小さめに）", f"{base.cache_gb:g}")
        try:
            cache_gb = float(reply)
            if cache_gb > 0:
                break
        except ValueError:
            pass
        print("  0 より大きい数で答えてください")
    print("標準データのサーバの値（わからなければ Enter で飛ばし、あとで Web UI で書き換える）")
    values = {}
    for name, label in PLACEHOLDERS:
        reply = p.text(f"{label}", base.values.get(name, ""))
        if reply:
            values[name] = reply
    return IndyAnswers(cache_gb=cache_gb, values=values)


def ask_answers(p: Prompter, output_root: Path) -> Answers:
    host = socket.gethostname()
    robot_name = os.getenv("ROBOT_NAME", "")
    base = Answers(config_host=host, robot_host=host, robot_id=robot_name,
                   output_dir=str(output_root / (robot_name or "robot1")),
                   data_dir="/srv/indy/mongodb")
    a = install.ask(p, base)
    if robot_name and a.robot_id != robot_name:
        print(f"  ※ ロボットの ID が ROBOT_NAME（{robot_name}）と違います。ロボットの ROBOT_NAME もこの ID に合わせてください")
    return a


# ---------------------------------------------------------------- DB への投入

def llm_host(a: Answers) -> str:
    return urlparse(a.llm_url).hostname or ""


def fill(text: str, values: Dict[str, str]) -> str:
    for name, value in values.items():
        text = text.replace(f"__{name}__", str(value))
    return text


def load_docs(path: Path, values: Dict[str, str]) -> list:
    from bson import json_util
    return json_util.loads(fill(path.read_text(encoding="utf-8"), values))


def remaining_placeholders(paths: List[Path], values: Dict[str, str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for path in paths:
        for name in sorted(set(re.findall(r"__([A-Z_]+)__", fill(path.read_text(encoding="utf-8"), values)))):
            out.setdefault(name, []).append(path.stem)
    return out


def robot_values(a: Answers, ia: IndyAnswers) -> Dict[str, str]:
    values = {"ROBOT_NAME": a.robot_id, "MONGO_HOST": a.robot_host, "MONGO_PORT": str(a.robot_port)}
    if llm_host(a):
        values["LLM_HOST"] = llm_host(a)
    values.update(ia.values)
    return values


def plan_robot_data(client, values: Dict[str, str]):
    """ロボットDB に入れる標準データ。(db, coll, 文書, 既にあるか) のリスト"""
    plan = []
    for path in sorted(DEFAULT_DATA.glob("*.json")):
        db, coll = path.stem.split(".", 1)
        for doc in load_docs(path, values):
            exists = client[db][coll].count_documents({"_id": doc["_id"]}, limit=1) > 0
            plan.append((db, coll, doc, exists))
    return plan


def has_key(doc: dict, dotted: str) -> bool:
    for part in dotted.split("."):
        if not isinstance(doc, dict) or part not in doc:
            return False
        doc = doc[part]
    return True


def plan_config_data(client, a: Answers, values: Dict[str, str], overwrite: bool):
    """設定DB に足すもの: robot_list に $set する項目（文書に無い項目だけ。overwrite なら全部）と、common（無ければ作る）"""
    db = client["rism_configs"]
    template = load_docs(CONFIG_DATA / "rism_configs.robot_list.json", values)[0]
    robot = db.robot_list.find_one({"robot_id": a.robot_id})
    has_robot = robot is not None
    robot_set = {k: v for k, v in template.items() if overwrite or not (has_robot and has_key(robot, k))}
    has_common = db.common.count_documents({}, limit=1) > 0
    return robot_set, has_robot, has_common


def setup_indy_data(a: Answers, ia: IndyAnswers, p: Prompter, overwrite: bool) -> int:
    from pymongo import MongoClient
    values = robot_values(a, ia)
    robot_client = MongoClient(a.robot_host, a.robot_port, serverSelectionTimeoutMS=5000)
    config_client = MongoClient(a.config_host, a.config_port, serverSelectionTimeoutMS=5000)

    plan = plan_robot_data(robot_client, values)
    robot_set, has_robot, has_common = plan_config_data(config_client, a, values, overwrite)
    secrets = {}
    if not has_common:
        for name, label in SECRETS:
            reply = p.text(f"{label}（Enter で飛ばす）", "")
            if reply:
                secrets[name] = reply
    common = load_docs(CONFIG_DATA / "rism_configs.common.json", {**values, **secrets})[0]

    print(f"\n== Indy 用に入れるもの（まだ書き込んでいない）")
    print(f"ロボットDB {a.robot_host}:{a.robot_port}（標準データ。同じ _id があれば"
          f"{'上書きする' if overwrite else '入れない'}）")
    counts: Dict[str, List[int]] = {}
    for db, coll, _, exists in plan:
        c = counts.setdefault(f"{db}.{coll}", [0, 0])
        c[1 if exists else 0] += 1
    for ns, (new, old) in counts.items():
        action = f"上書き {old}" if overwrite else f"既存のため入れない {old}"
        print(f"  {ns:42s} 追加 {new} 件" + (f" / {action} 件" if old else ""))
    print(f"設定DB {a.config_host}:{a.config_port}/rism_configs")
    if has_robot and robot_set:
        print(f"  robot_list {a.robot_id}: ロボット側の設定を{'上書き' if overwrite else '追記'}（{', '.join(robot_set)}）")
    elif has_robot:
        print(f"  robot_list {a.robot_id}: ロボット側の設定は既にあるため入れない（上書きは --overwrite）")
    else:
        print(f"  robot_list {a.robot_id}: まだ無いため追記しない（先に RISM の設定を入れてください）")
    print("  common: " + ("既にあるため入れない" if has_common else "作る"))

    if not p.yes("\nこの内容で書き込みますか？", True):
        print("書き込みませんでした")
        return 0
    for db, coll, doc, exists in plan:
        if exists and overwrite:
            robot_client[db][coll].replace_one({"_id": doc["_id"]}, doc)
        elif not exists:
            robot_client[db][coll].insert_one(doc)
    db = config_client["rism_configs"]
    if has_robot and robot_set:
        db.robot_list.update_one({"robot_id": a.robot_id}, {"$set": robot_set})
    if not has_common:
        db.common.insert_one(common)
    print("書き込みました")

    # 今回入れたものだけを見る（既にある common や、入れなかった robot_list の追記は数えない）
    paths = sorted(DEFAULT_DATA.glob("*.json"))
    if has_robot and robot_set:
        paths.append(CONFIG_DATA / "rism_configs.robot_list.json")
    if not has_common:
        paths.append(CONFIG_DATA / "rism_configs.common.json")
    rest = remaining_placeholders(paths, {**values, **secrets})
    if rest:
        print("\n次のプレースホルダは置き換えていません。Web UI（各 MongoDB のポート+1）で書き換えてください:")
        for name, where in rest.items():
            print(f"  __{name}__ : {' '.join(where)}")
    return 0


def setup_databases(a: Answers, ia: IndyAnswers, p: Prompter, overwrite: bool, answers_path: Path) -> int:
    for label, host, port in (("設定DB", a.config_host, a.config_port), ("ロボットDB", a.robot_host, a.robot_port)):
        if not install.db_reachable(host, port):
            print(f"{label} {host}:{port} につながりません。docker compose で起動してから、もう一度")
            print(f"  {HERE / 'setup_mongo.sh'} --answers {answers_path}")
            print("を実行してください")
            return 1
    # RISM2 の設定とサンプル（rism2 の tools/setup_db.py。dry-run を見せてから書く）
    result = install.setup_databases(a, p)
    if result != 0:
        return result
    return setup_indy_data(a, ia, p, overwrite)


# ---------------------------------------------------------------- 結果の表示

def env_lines(a: Answers) -> List[str]:
    lines = [f"export ROBOT_NAME={a.robot_id}",
             f"export MONGO_URI={a.robot_host}",
             f"export MONGO_PORT={a.robot_port}"]
    if a.config_host != a.robot_host:
        lines.append(f"export RISM_CONFIG_HOST={a.config_host}   # 設定DB が別のサーバのとき")
    if a.config_port != install.CONFIG_PORT:
        lines.append(f"export RISM_CONFIG_PORT={a.config_port}")
    if a.demo_id != f"{a.robot_id}_demo":
        lines.append(f"export SCENARIO_DEMO={a.demo_id}")
    return lines


def main(argv=None, input_func: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answers", help="前回の答え（install_answers.json）。あれば聞かずにそれを使う")
    parser.add_argument("--compose-only", action="store_true", help="docker compose ファイルを作るだけで、DB には書かない")
    parser.add_argument("--overwrite", action="store_true", help="標準データ（同じ _id の文書）と robot_list のロボット側の設定を、テンプレートの値で上書きする")
    parser.add_argument("--output-root", default=str(HERE / "deploy"),
                        help="compose ファイルを置くフォルダの親（既定: setup/mongo_docker/deploy。この下にロボットごと）")
    args = parser.parse_args(argv)
    p = Prompter(input_func)

    if args.answers:
        answers_path = Path(args.answers)
        a = Answers(**json.loads(answers_path.read_text(encoding="utf-8")))
        indy_path = answers_path.parent / INDY_ANSWERS
        ia = IndyAnswers(**json.loads(indy_path.read_text(encoding="utf-8"))) if indy_path.exists() else IndyAnswers()
    else:
        print(__doc__.strip().splitlines()[0] + "\n（Enter で [ ] の中の値を使う）\n")
        a = ask_answers(p, Path(args.output_root))
        ia = ask_indy(p, a, IndyAnswers())
    answers_path = Path(a.output_dir) / "install_answers.json"
    print("\n== 決めたこと\n" + install.summary(a))
    print(f"  キャッシュ {ia.cache_gb:g} GB")
    for name, value in ia.values.items():
        print(f"  {name:8s} {value}")
    if not args.answers and not p.yes("\nこの内容で進めますか？", True):
        print("やめました")
        return 1

    for path in install.write_files(a) + write_indy_files(a, ia):
        print(f"作成: {path}")
    print("\n== データのディレクトリを作る（初めてのとき）")
    for command in install.prepare_commands(a):
        print(f"  {command}")
    print("\n== MongoDB の起動")
    for command in start_commands(a):
        print(f"  {command}")

    if args.compose_only:
        result = 0
    elif args.answers or p.yes("\nMongoDB は起動していますか？（起動していれば、設定とデータを DB に入れる）", False):
        result = setup_databases(a, ia, p, args.overwrite, answers_path)
    else:
        print("\nMongoDB を起動したら、次で設定とデータを DB に入れる:")
        print(f"  {HERE / 'setup_mongo.sh'} --answers {answers_path}")
        result = 0
    if result == 0:
        print("\n== ~/indy.env に書く値（ロボット搭載マシンとサーバマシン。シナリオはロボット搭載マシンで起動する）")
        for line in env_lines(a):
            print(f"  {line}")
        print("\n== シナリオの起動")
        print("  $GUARDIAN_ROBOT_PATH/modules/module_launch/scenario_launch.sh")
    return result


if __name__ == "__main__":
    sys.exit(main())
