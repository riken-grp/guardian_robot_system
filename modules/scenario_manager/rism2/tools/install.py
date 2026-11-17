"""
RISM2 のサーバを対話で用意する

  uv run python tools/install.py                      # 対話で聞く
  uv run python tools/install.py --answers deploy/install_answers.json   # 前回の答えで、聞かずにやり直す

ポートの既定: 設定DB は 9100、ロボット 1, 2, 3, ... のロボットDB は 9110, 9120, 9130, ...（9100 + 10 × 番号）

することは3つ:
  1. MongoDB（設定DB と ロボットDB）と Web UI の docker compose ファイルを作る
       設定DB とロボットDB が同じサーバなら docker-compose.yml 1つ（と .env、rs-healthcheck.js）、
       別のサーバなら config/（docker-compose.config.yml）と robot/（docker-compose.robot.yml）の
       フォルダに分ける（それぞれのサーバにフォルダごとコピーする）
       2台目からのロボットのように設定DB がもうあれば、ロボットDB だけの docker-compose.yml を作る
       DB のデータは、聞いたディレクトリ（<データの置き場所>/mongodb_for_<名前>/data など）に置く
  2. 答えを install_answers.json に保存する（--answers で読み直せる）
  3. DB が起動していれば、RISM を動かすのに要る設定（rism_configs）とサンプルのシナリオを入れる
       （tools/setup_db.py を使う。書き込む前に何を入れるか見せて確かめる）

MongoDB はレプリカセット（rs0）で動かす（RISM は変更ストリームで観測を受け取るため）。
メンバーの名前は「ホスト名:ポート」で、RISM やロボットからその名前でつなげる必要がある。
レプリカセットの作成とメンバー名の修正は、healthcheck が rs-healthcheck.js でする。
Web UI（mongo-express か DbGate）はログインなし。各 MongoDB のポート+1 で開く。
"""
import argparse
import json
import socket
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 版は固定する
MONGO_IMAGE = "mongo:8.0.34"
MONGO_EXPRESS_IMAGE = "mongo-express:1.0.2-20-alpine3.19"
DBGATE_IMAGE = "dbgate/dbgate:7.3.3"
REPLICA_SET = "rs0"
LEGACY_CONFIG_PORT = 9000  # 古い RISM の設定DB
CONFIG_PORT = 9100


def robot_port_for(number: int) -> int:
    """ロボット 1, 2, 3, ... の ロボットDB の既定のポート（9110, 9120, 9130, ...）"""
    return CONFIG_PORT + 10 * number


@dataclass
class Answers:
    """対話で決めること（install_answers.json にそのまま保存する）"""
    new_config: bool = True                  # 設定DB も作るか（2台目からのロボットで、設定DB がもうあれば False）
    same_server: bool = True                 # 設定DB とロボットDB を同じサーバ（同じ compose ファイル）に置くか
    config_host: str = "localhost"
    config_port: int = CONFIG_PORT
    robot_number: int = 1
    robot_host: str = "localhost"
    robot_port: int = 0                      # 0 なら robot_port_for(robot_number)
    web_ui: str = "mongo-express"            # mongo-express / dbgate / none
    data_dir: str = "/srv/rism2/mongodb"     # DB のデータを置くホストのディレクトリ（この下に DB ごとのディレクトリ）
    mongo_user: str = "1001:1001"            # MongoDB を動かすユーザー（uid:gid）。データのディレクトリの持ち主
    output_dir: str = "deploy"
    robot_id: str = ""                       # 空なら robot<番号>
    name_alias: str = ""
    demo_id: str = ""
    llm_url: str = "http://localhost:8001/v1"
    llm_model: str = "indy-instruct"
    install_samples: bool = True

    def __post_init__(self):
        if not self.new_config:
            self.same_server = False
        if self.same_server:
            self.robot_host = self.config_host
        self.robot_port = self.robot_port or robot_port_for(self.robot_number)
        self.robot_id = self.robot_id or f"robot{self.robot_number}"
        self.name_alias = self.name_alias or self.robot_id[:1].upper() + self.robot_id[1:]
        self.demo_id = self.demo_id or f"{self.robot_id}_demo"


# ---------------------------------------------------------------- docker compose
# 作る compose の形:
#   データはホストのディレクトリ（<データの置き場所>/<名前>/data・config・var_cache）、
#   指定したユーザーで動かす、レプリカセットは rs-healthcheck.js が作る、ホスト名とイメージは .env に書く

RS_HEALTHCHECK_JS = """\
// tools/install.py が作ったファイル。MongoDB の healthcheck から実行する
// レプリカセット rs0 を、メンバー名 RS_HOST（外からつなぐ <ホスト名>:<ポート>）で作る。
// 既にあってメンバー名が違えば（ホスト名を変えたときなど）、RS_HOST に直す。
// PRIMARY になっていれば正常（終了コード 0）。
const want = process.env.RS_HOST;
let initiated = true;
try {
  rs.status();
} catch (e) {
  initiated = false;
}
if (!initiated) {
  rs.initiate({_id: "rs0", members: [{_id: 0, host: want}]});
} else {
  const conf = rs.conf();
  if (conf.members.length === 1 && conf.members[0].host !== want) {
    conf.members[0].host = want;
    rs.reconfig(conf, {force: true});
  }
}
if (rs.status().myState !== 1) {
  quit(1);
}
"""


@dataclass
class MongoService:
    name: str        # compose のサービス名
    label: str       # 人が読む名前
    host: str        # レプリカセットのメンバー名に使うホスト名（RISM・ロボットからつなぐ名前）
    port: int
    data_dir: str    # ホストのディレクトリ（この下に data・config・var_cache）


def _needs_host_alias(host: str) -> bool:
    """コンテナの中からホスト名で自分につなぐために、extra_hosts が要るか（localhost と IP は要らない）"""
    if host in ("localhost", "127.0.0.1"):
        return False
    try:
        socket.inet_aton(host)
        return False
    except OSError:
        return True


def _mongo_block(m: MongoService) -> List[str]:
    lines = [
        f"  {m.name}:",
        f"    # {m.label}",
        "    <<: *mongo",
        f"    command: [\"--replSet\", \"{REPLICA_SET}\", \"--bind_ip_all\", \"--port\", \"{m.port}\"]",
        "    ports:",
        f"      - {m.port}:{m.port}",
        "    volumes:",
        "      - ./rs-healthcheck.js:/rs-healthcheck.js:ro",
        f"      - {m.data_dir}/data:/data/db",
        f"      - {m.data_dir}/config:/data/configdb",
        f"      - {m.data_dir}/var_cache:/var/cache",
        "    environment:",
        f"      MONGO_PORT: \"{m.port}\"",
        f"      RS_HOST: ${{MONGO_PUBLIC_HOST:?MONGO_PUBLIC_HOST を .env に設定してください}}:{m.port}",
    ]
    if _needs_host_alias(m.host):
        lines += [
            "    extra_hosts:",
            "      # メンバー名のホスト名を、コンテナの中からも引けるようにする（このサーバ自身を指す）",
            "      - ${MONGO_PUBLIC_HOST}:host-gateway",
        ]
    return lines


def _mongo_express_block(m: MongoService) -> List[str]:
    return [
        f"  {m.name}-ui:",
        f"    # {m.label} の Web UI（mongo-express、ログインなし） http://<このサーバ>:{m.port + 1}/",
        "    <<: *mongo_express",
        "    ports:",
        f"      - {m.port + 1}:8081",
        "    depends_on:",
        f"      {m.name}:",
        "        condition: service_healthy",
        "    environment:",
        "      TZ: Asia/Tokyo",
        "      ME_CONFIG_BASICAUTH: \"false\"",
        "      ME_CONFIG_MONGODB_ENABLE_ADMIN: \"true\"",
        f"      ME_CONFIG_MONGODB_URL: mongodb://{m.name}:{m.port}/?directConnection=true",
    ]


def _dbgate_block(mongos: List[MongoService], name: str, data_dir: str) -> List[str]:
    port = mongos[0].port + 1
    lines = [
        f"  {name}:",
        f"    # Web UI（DbGate、ログインなし） http://<このサーバ>:{port}/",
        f"    image: {DBGATE_IMAGE}",
        "    restart: always",
        "    ports:",
        f"      - {port}:3000",
        "    volumes:",
        f"      - {data_dir}:/root/.dbgate",
        "    environment:",
        "      TZ: Asia/Tokyo",
        f"      CONNECTIONS: \"{','.join(m.name.replace('-', '_') for m in mongos)}\"",
    ]
    for m in mongos:
        key = m.name.replace("-", "_")
        lines += [
            f"      LABEL_{key}: \"{m.label}\"",
            f"      URL_{key}: mongodb://{m.name}:{m.port}/?directConnection=true",
            f"      ENGINE_{key}: mongo@dbgate-plugin-mongo",
        ]
    lines += ["    depends_on:"]
    for m in mongos:
        lines += [f"      {m.name}:", "        condition: service_healthy"]
    return lines


def _compose_file(project: str, mongos: List[MongoService], a: "Answers", title: str) -> str:
    lines = [
        f"# {title}",
        "# tools/install.py が作ったファイル。作り直すときは install.py を実行し直す",
        "# MongoDB は単一ノードのレプリカセット（rs0）。メンバー名は <MONGO_PUBLIC_HOST>:<公開ポート> で、",
        "# mongod はコンテナの中でも公開ポートと同じ番号で待ち受ける。MONGO_PUBLIC_HOST は同じフォルダの .env に書く。",
        "# レプリカセットの作成とメンバー名の修正は rs-healthcheck.js がする。",
        "#   起動: docker compose up -d     状態: docker compose ps（MongoDB が healthy になれば使える）",
        f"name: {project}",
        "",
        "x-mongo: &mongo",
        "  image: \"${MONGO_IMAGE:?MONGO_IMAGE を .env に設定してください}\"",
        "  restart: always",
        f"  user: \"{a.mongo_user}\"",
        "  healthcheck:",
        "    test: [\"CMD-SHELL\", \"HOME=/tmp mongosh --quiet --port $${MONGO_PORT} /rs-healthcheck.js\"]",
        "    interval: 10s",
        "    timeout: 10s",
        "    retries: 30",
        "    start_period: 20s",
        "",
    ]
    if a.web_ui == "mongo-express":
        lines += [
            "x-mongo-express: &mongo_express",
            f"  image: {MONGO_EXPRESS_IMAGE}",
            "  restart: always",
            "",
        ]
    lines += ["services:", ""]
    for m in mongos:
        lines += _mongo_block(m) + [""]
        if a.web_ui == "mongo-express":
            lines += _mongo_express_block(m) + [""]
    if a.web_ui == "dbgate":
        lines += _dbgate_block(mongos, "web-ui", f"{a.data_dir}/dbgate_for_{project}") + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _env_file(host: str) -> str:
    return (
        "# tools/install.py が作ったファイル（docker compose が読む）\n"
        "# レプリカセットのメンバー名に使う、このサーバのホスト名（RISM・ロボットからつなぐ名前）\n"
        f"MONGO_PUBLIC_HOST={host}\n"
        f"MONGO_IMAGE={MONGO_IMAGE}\n"
    )


def mongo_services(a: "Answers") -> List[MongoService]:
    config = MongoService("mongo-config", f"設定DB（rism_configs）:{a.config_port}", a.config_host, a.config_port,
                          f"{a.data_dir}/mongodb_for_rism_config")
    robot = MongoService("mongo-robot", f"ロボットDB {a.robot_id}（tBlackBoard / demo_configs）:{a.robot_port}",
                         a.robot_host, a.robot_port, f"{a.data_dir}/mongodb_for_{a.robot_id}")
    return [config, robot]


def build_compose(a: "Answers") -> Dict[str, str]:
    """出力フォルダからの相対パス → 中身。別のサーバなら、サーバごとのフォルダ（config/ と robot/）に分ける"""
    config, robot = mongo_services(a)
    if not a.new_config:
        return {
            "docker-compose.yml": _compose_file(f"rism2-{a.robot_id}", [robot], a,
                                                f"RISM2 のロボットDB {a.robot_id}（{a.robot_host} で動かす）"),
            ".env": _env_file(a.robot_host),
            "rs-healthcheck.js": RS_HEALTHCHECK_JS,
        }
    if a.same_server:
        return {
            "docker-compose.yml": _compose_file("rism2", [config, robot], a,
                                                f"RISM2 の MongoDB（設定DB とロボットDB {a.robot_id}）"),
            ".env": _env_file(a.config_host),
            "rs-healthcheck.js": RS_HEALTHCHECK_JS,
        }
    return {
        "config/docker-compose.config.yml": _compose_file("rism2-config", [config], a,
                                                          f"RISM2 の設定DB（{a.config_host} で動かす）"),
        "config/.env": _env_file(a.config_host),
        "config/rs-healthcheck.js": RS_HEALTHCHECK_JS,
        "robot/docker-compose.robot.yml": _compose_file(f"rism2-{a.robot_id}", [robot], a,
                                                        f"RISM2 のロボットDB {a.robot_id}（{a.robot_host} で動かす）"),
        "robot/.env": _env_file(a.robot_host),
        "robot/rs-healthcheck.js": RS_HEALTHCHECK_JS,
    }


def data_dirs(a: "Answers") -> Dict[str, List[str]]:
    """サーバ（ホスト名）→ そのサーバに作るデータのディレクトリ（DB ごと。中に data・config・var_cache）"""
    config, robot = mongo_services(a)
    out: Dict[str, List[str]] = {}
    if not a.new_config:
        out[robot.host] = [robot.data_dir]
        if a.web_ui == "dbgate":
            out[robot.host].append(f"{a.data_dir}/dbgate_for_rism2-{a.robot_id}")
        return out
    for m in (config, robot):
        out.setdefault(m.host, []).append(m.data_dir)
    if a.web_ui == "dbgate":
        out[config.host].append(f"{a.data_dir}/dbgate_for_{'rism2' if a.same_server else 'rism2-config'}")
        if not a.same_server:
            out[robot.host].append(f"{a.data_dir}/dbgate_for_rism2-{a.robot_id}")
    return out


def prepare_commands(a: "Answers") -> List[str]:
    """データのディレクトリを作り、MongoDB を動かすユーザーの持ち物にするコマンド（サーバごと）"""
    commands = []
    for host, dirs in data_dirs(a).items():
        made = " ".join(f"{d}/{{data,config,var_cache}}" if "/mongodb_for_" in d else d for d in dirs)
        commands.append(f"（{host} で）sudo mkdir -p {made} && sudo chown -R {a.mongo_user} {' '.join(dirs)}")
    return commands


def setup_db_args(a: Answers, extra: Optional[List[str]] = None) -> List[str]:
    """tools/setup_db.py に渡す引数"""
    args = ["--config-host", a.config_host, "--config-port", str(a.config_port),
            "--scenario-host", a.robot_host, "--scenario-port", str(a.robot_port),
            "--robot-id", a.robot_id, "--name-alias", a.name_alias, "--demo-id", a.demo_id,
            "--llm-url", a.llm_url, "--llm-model", a.llm_model]
    if not a.install_samples:
        args += ["--only", "config"]
    return args + (extra or [])


def start_commands(a: Answers) -> List[str]:
    out = Path(a.output_dir)
    if not a.new_config:
        return [f"（{a.robot_host} で）{out} の中で docker compose up -d"]
    if a.same_server:
        return [f"cd {out} && docker compose up -d"]
    return [f"（{a.config_host} で）{out / 'config'} をコピーして、その中で docker compose -f docker-compose.config.yml up -d",
            f"（{a.robot_host} で）{out / 'robot'} をコピーして、その中で docker compose -f docker-compose.robot.yml up -d"]


def run_command(a: Answers) -> str:
    return (f"uv run main.py --robots {a.robot_id} --demo {a.demo_id} "
            f"--host {a.config_host} --port {a.config_port}")


# ---------------------------------------------------------------- 対話

class Prompter:
    """input() で聞く（テストでは input_func を差し替える）"""

    def __init__(self, input_func: Callable[[str], str] = input):
        self.input = input_func

    def text(self, question: str, default: str) -> str:
        reply = self.input(f"{question} [{default}]: ").strip()
        return reply or default

    def number(self, question: str, default: int) -> int:
        while True:
            reply = self.text(question, str(default))
            if reply.isdigit() and 0 < int(reply) < 65535:
                return int(reply)
            print("  1〜65534 の数字で答えてください")

    def yes(self, question: str, default: bool = True) -> bool:
        mark = "Y/n" if default else "y/N"
        while True:
            reply = self.input(f"{question} [{mark}]: ").strip().lower()
            if not reply:
                return default
            if reply in ("y", "yes", "はい"):
                return True
            if reply in ("n", "no", "いいえ"):
                return False
            print("  y か n で答えてください")

    def choice(self, question: str, options: List[str], default: str) -> str:
        print(question)
        for i, option in enumerate(options, 1):
            print(f"  {i}. {option}")
        while True:
            reply = self.text("番号", str(options.index(default) + 1))
            if reply.isdigit() and 1 <= int(reply) <= len(options):
                return options[int(reply) - 1]
            print(f"  1〜{len(options)} で答えてください")


def ask(p: Prompter, base: Answers) -> Answers:
    print("== MongoDB の置き場所")
    print("RISM とロボットがつなぐときのホスト名を答える（レプリカセットのメンバー名になる）")
    new_config = p.yes("設定DB も新しく作りますか？（2台目からのロボットで、設定DB がもうあれば n）", base.new_config)
    if new_config:
        same = p.yes("設定DB とロボットDB を同じサーバに置きますか？", base.same_server)
        if same:
            config_host = robot_host = p.text("そのサーバのホスト名", base.config_host)
        else:
            config_host = p.text("設定DB のサーバのホスト名", base.config_host)
            robot_host = p.text("ロボットDB のサーバのホスト名", base.robot_host)
    else:
        same = False
        config_host = p.text("今ある設定DB のホスト名", base.config_host)
        robot_host = p.text("ロボットDB を置くサーバのホスト名", config_host)
    while True:
        config_port = p.number("設定DB のポート", base.config_port)
        if config_port != LEGACY_CONFIG_PORT:
            break
        print(f"  {LEGACY_CONFIG_PORT} は古い RISM の設定DBのポートなので使えません")
    while True:
        robot_number = p.number("ロボットの番号（1, 2, 3, ...。ロボットDB のポートの既定が 9110, 9120, 9130, ... になる）",
                                base.robot_number)
        if robot_port_for(robot_number) < 65535:
            break
        print("  番号が大きすぎます")
    while True:
        robot_port = p.number("ロボットDB のポート", robot_port_for(robot_number))
        clash = robot_host == config_host and abs(robot_port - config_port) < 2
        if not clash:
            break
        print("  同じサーバでは、Web UI がポート+1 を使うので、2つ以上離してください")
    web_ui = p.choice("Web UI（ログインなし、各 MongoDB のポート+1 で開く）", ["mongo-express", "dbgate", "none"],
                      base.web_ui)
    print("DB のデータは、ホストのディレクトリに置く（この下に DB ごとのディレクトリを作る）")
    data_dir = p.text("データを置くディレクトリ（絶対パス）", base.data_dir).rstrip("/")
    while not data_dir.startswith("/"):
        print("  / で始まる絶対パスで答えてください")
        data_dir = p.text("データを置くディレクトリ（絶対パス）", base.data_dir).rstrip("/")
    while True:
        mongo_user = p.text("MongoDB を動かすユーザー（uid:gid、データのディレクトリの持ち主）", base.mongo_user)
        if len(mongo_user.split(":")) == 2 and all(x.isdigit() for x in mongo_user.split(":")):
            break
        print("  1001:1001 のように数字で答えてください")
    output_dir = p.text("docker compose ファイルを置くフォルダ", base.output_dir)

    print("\n== ロボット")
    default_id = f"robot{robot_number}" if base.robot_id == f"robot{base.robot_number}" else base.robot_id
    robot_id = p.text("ロボットの ID（robot_list のキー、ROS のトピック名にも使う）", default_id)
    name_alias = p.text("表示名", base.name_alias if base.robot_id == robot_id else robot_id[:1].upper() + robot_id[1:])
    demo_id = p.text("デモの ID（main.py の --demo）", base.demo_id if base.robot_id == robot_id else f"{robot_id}_demo")
    llm_url = p.text("LLM サーバの URL（OpenAI 互換）", base.llm_url)
    llm_model = p.text("LLM のモデル名", base.llm_model)
    samples = p.yes("サンプルのシナリオと知識も入れますか？", base.install_samples)
    return Answers(new_config=new_config, same_server=same, config_host=config_host, config_port=config_port,
                   robot_number=robot_number, robot_host=robot_host, robot_port=robot_port, web_ui=web_ui, data_dir=data_dir, mongo_user=mongo_user,
                   output_dir=output_dir, robot_id=robot_id,
                   name_alias=name_alias, demo_id=demo_id, llm_url=llm_url, llm_model=llm_model,
                   install_samples=samples)


def web_ui_urls(a: Answers) -> List[str]:
    if a.web_ui == "none":
        return []
    if not a.new_config:
        return [f"http://{a.robot_host}:{a.robot_port + 1}/"]
    if a.web_ui == "dbgate" and a.same_server:
        return [f"http://{a.config_host}:{a.config_port + 1}/"]
    return [f"http://{a.config_host}:{a.config_port + 1}/", f"http://{a.robot_host}:{a.robot_port + 1}/"]


def summary(a: Answers) -> str:
    rows = [
        ("設定DB", f"{a.config_host}:{a.config_port}（rism_configs）" + ("" if a.new_config else "（今あるものを使う）")),
        ("ロボットDB", f"{a.robot_host}:{a.robot_port}（ロボット {a.robot_number}。tBlackBoard、シナリオは demo_configs）"),
        ("Web UI", a.web_ui if a.web_ui == "none" else f"{a.web_ui}（{', '.join(web_ui_urls(a))}）"),
        ("データ", f"{a.data_dir}/（" + ("mongodb_for_rism_config、" if a.new_config else "")
         + f"mongodb_for_{a.robot_id}）、ユーザー {a.mongo_user}"),
        ("ロボット", f"{a.robot_id}（表示名 {a.name_alias}、デモ {a.demo_id}）"),
        ("LLM", f"{a.llm_model} @ {a.llm_url}"),
        ("サンプル", "入れる" if a.install_samples else "入れない（設定だけ）"),
    ]
    return "\n".join(f"  {k:8} {v}" for k, v in rows)


def db_reachable(host: str, port: int) -> bool:
    from pymongo import MongoClient
    try:
        MongoClient(host, port, serverSelectionTimeoutMS=3000).admin.command("ping")
        return True
    except Exception:
        return False


def write_files(a: Answers) -> List[Path]:
    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in build_compose(a).items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    answers_path = out / "install_answers.json"
    answers_path.write_text(json.dumps(asdict(a), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append(answers_path)
    return written


def setup_databases(a: Answers, p: Prompter) -> int:
    import setup_db
    for label, host, port in (("設定DB", a.config_host, a.config_port), ("ロボットDB", a.robot_host, a.robot_port)):
        if not db_reachable(host, port):
            print(f"{label} {host}:{port} につながりません。docker compose で起動してから、もう一度")
            print(f"  uv run python tools/install.py --answers {Path(a.output_dir) / 'install_answers.json'}")
            print("を実行してください")
            return 1
    print("\n== 入れるもの（まだ書き込んでいない）")
    setup_db.main(setup_db_args(a, ["--dry-run"]))
    if not p.yes("\nこの内容で書き込みますか？", True):
        print("書き込みませんでした")
        return 0
    return setup_db.main(setup_db_args(a))


def main(argv=None, input_func: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--answers", help="前回の答え（install_answers.json）。あれば聞かずにそれを使う")
    parser.add_argument("--compose-only", action="store_true", help="docker compose ファイルを作るだけで、DB には書かない")
    args = parser.parse_args(argv)
    p = Prompter(input_func)

    if args.answers:
        a = Answers(**json.loads(Path(args.answers).read_text(encoding="utf-8")))
    else:
        print(__doc__.strip().splitlines()[0] + "\n（Enter で [ ] の中の値を使う）\n")
        a = ask(p, Answers(config_host=socket.gethostname(), robot_host=socket.gethostname()))
    print("\n== 決めたこと\n" + summary(a))
    if not args.answers and not p.yes("\nこの内容で進めますか？", True):
        print("やめました")
        return 1

    for path in write_files(a):
        print(f"作成: {path}")
    print("\n== データのディレクトリを作る（初めてのとき）")
    for command in prepare_commands(a):
        print(f"  {command}")
    print("\n== MongoDB の起動")
    for command in start_commands(a):
        print(f"  {command}")

    if args.compose_only:
        result = 0
    elif args.answers or p.yes("\nMongoDB は起動していますか？（起動していれば、RISM の設定を DB に入れる）", False):
        result = setup_databases(a, p)
    else:
        print("\nMongoDB を起動したら、次で設定を DB に入れる:")
        print(f"  uv run python tools/install.py --answers {Path(a.output_dir) / 'install_answers.json'}")
        result = 0
    if result == 0:
        print(f"\n== RISM の起動\n  {run_command(a)}")
    return result


if __name__ == "__main__":
    sys.exit(main())
