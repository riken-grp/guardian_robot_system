"""Web 側: ロボットの状態を表示し, 操作を受け付ける FastAPI アプリ

使い方 (ロボットごとの値は引数か --config の設定ファイルで渡す. 一覧は --help):
    uv run main.py --robot <ロボット名> --web-port 8001 --db-host <MongoDBのホスト> --db-port 9110 --ros-domain-id <ID>
    uv run main.py --config config_<ロボット名>.json   (config.example.json をコピーして作る)
"""
import asyncio
import io
import logging
import wave
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
import numpy as np
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pyindy.mongo import DBManager, ROSCommandManager, UtteranceManager
from pymongo.errors import PyMongoError

from blackboard import Blackboard, ScenarioCatalog
from config import load_config
from destinations import DEFAULT_COLLECTION, Destinations
from robot import QOS_PROFILES, SpeechSegment, StringStamped, RobotState, run_ros

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# 移動コマンド -> (前進速度 m/s, 回転速度 rad/s)
VELOCITIES = {
    "front": (0.05, 0.0),
    "back": (-0.05, 0.0),
    "left": (0.0, 0.05),
    "right": (0.0, -0.05),
    "stop": (0.0, 0.0),
}

LOW_BATTERY = 50  # これ未満で「残量わずか」を表示 (%)
ACTION_COUNT = 5  # 種類ごとに表示するロボットの行動の数 (設定 action_count で変更可)
SCENARIO_HISTORY_COUNT = 6  # 表示するシナリオ履歴の数
MJPEG_BOUNDARY = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"


def to_wav(sample_rate, samples):
    """float32 のサンプル列を 16bit PCM の WAV にする"""
    pcm = (np.clip(np.frombuffer(samples, dtype="<f4"), -1, 1) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buffer.getvalue()


def error(message, status_code):
    return JSONResponse({"error": message}, status_code=status_code)


def create_app(config):
    robot_name = config["robot_name"]
    server_name = config["server_name"]
    server_port = config["server_port"]
    db_name = config["db_name"]
    template_name = config.get("template", "index.html")
    action_count = config.get("action_count", config.get("spoken_text_count", ACTION_COUNT))
    battery_qos = QOS_PROFILES[config.get("battery_qos", "system_default")]
    ros_domain_id = config.get("ros_domain_id")  # 未指定なら環境変数 ROS_DOMAIN_ID

    # MongoDB: 書き込み (pyindy) と, 画面表示用の読み出し (行動・シナリオ・地図)
    physical_db = DBManager(server_name, server_port, db_name, "physical_topic")
    utterance_manager = UtteranceManager(server_name, server_port, robot_name, db_name)
    command_manager = ROSCommandManager(server_name, server_port, robot_name, db_name)
    blackboard = Blackboard(server_name, server_port, db_name, robot_name, action_count, config.get("map_region"))
    # RISM のシナリオ定義 (タイムラインの詳細表示用). RISM の rism_configs.demo_list の scenario_db と同じ場所
    scenario_db = config.get("scenario_db", {})
    demo_configs = (
        scenario_db.get("host", server_name),
        scenario_db.get("port", server_port),
        scenario_db.get("db_name", "demo_configs"),
    )
    catalog = ScenarioCatalog(*demo_configs, blackboard.location_name)
    # 「部屋を見に行く」の行き先. デモの設定なのでシナリオ定義と同じ DB (demo_configs) に置く (管理は destinations.py)
    destinations = Destinations(*demo_configs, config.get("destinations_collection", DEFAULT_COLLECTION))

    templates = Jinja2Templates(directory=BASE_DIR / "templates")
    # 静的ファイルが更新されたらブラウザのキャッシュを使わないよう, URL に更新時刻を付ける
    asset_version = int(max(p.stat().st_mtime for p in STATIC_DIR.iterdir()))
    state = RobotState()
    ros = {}

    @asynccontextmanager
    async def lifespan(app):
        """起動時にROS2ノードを別スレッドで開始し, 終了時に停止する"""
        state.start(asyncio.get_running_loop())
        with run_ros(robot_name, state, battery_qos, ros_domain_id) as node:
            ros["node"] = node
            try:
                yield
            finally:
                ros.clear()

    app = FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # ---- ページと操作 ----
    @app.get("/", response_class=HTMLResponse)
    async def read_root(request: Request):
        return templates.TemplateResponse(
            request,
            template_name,
            {
                "battery": state.battery,
                "is_charging": state.is_charging,
                "low_battery": LOW_BATTERY,
                "speech_enabled": SpeechSegment is not None,
                "asr_enabled": StringStamped is not None,
                "asset_version": asset_version,
            },
        )

    @app.post("/submit")
    def submit_text(user_input: str = Form(...)):
        utterance_manager.insert({"text": user_input})
        return RedirectResponse(url="/", status_code=303)

    @app.get("/destinations")
    def get_destinations():
        """「部屋を見に行く」の行き先 (DB から読む)"""
        try:
            return {"destinations": destinations.list()}
        except PyMongoError as e:
            logger.warning("行き先の取得に失敗しました: %s", e)
            return error("行き先を取得できません", 503)

    @app.post("/destinations/{destination_id}/visit")
    async def visit_destination(destination_id: str):
        try:
            destination = await run_in_threadpool(destinations.get, destination_id)
        except PyMongoError as e:
            logger.warning("行き先の取得に失敗しました: %s", e)
            return error("行き先を取得できません", 503)
        if destination is None:
            return error("行き先が見つかりません (一覧が変更された可能性があります)", 404)
        text = destination["text"]
        # DB への書き込みはブロックするのでスレッドプールで行う
        await run_in_threadpool(
            command_manager.insert,
            {"type": "normal", "topic": f"/{robot_name}/robot/action_ctl", "data": "stop"},
        )
        await asyncio.sleep(1)  # 停止を待つ (イベントループはブロックしない)
        await run_in_threadpool(
            physical_db.insert, "asr", {"instance_id": -1, "words": text, "text": text}, priority=100
        )
        return {"message": f"{destination['label']}を見に行ってきます"}

    @app.post("/control/{command}")
    async def handle_control_button(command: str):
        if command not in VELOCITIES:
            return error("移動コマンドが正しくありません", 400)
        node = ros.get("node")
        if node is None:
            return error("ROS2 ノードが起動していません", 503)
        node.publish_velocity(*VELOCITIES[command])
        return {"message": command}

    # ---- ROS から受け取った状態 ----
    @app.get("/status")
    async def get_status():
        """ROSから受信した状態 (ページから定期的に取得して表示を更新する)"""
        return {
            "battery": state.battery,
            "is_charging": state.is_charging,
            "pose": state.current_pose(),
            "heard": state.current_heard(),
        }

    @app.get("/camera")
    async def get_camera_stream():
        """カメラ映像 (MJPEG). 新しいフレームが届いたときだけ送る"""
        async def frames():
            with state.frames.subscribe() as queue:
                if state.jpeg is not None:
                    yield MJPEG_BOUNDARY + state.jpeg + b"\r\n"
                while True:
                    yield MJPEG_BOUNDARY + await queue.get() + b"\r\n"

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace;boundary=frame")

    @app.get("/speech_clip/{clip_id}")
    def get_speech_clip(clip_id: str):
        """聞き取った言葉の元になった発話音声 (WAV)"""
        clip = state.clip(clip_id)
        if clip is None:
            return error("音声が残っていません", 404)
        return Response(to_wav(*clip), media_type="audio/wav", headers={"Cache-Control": "max-age=3600"})

    @app.get("/speech_face/{clip_id}")
    def get_speech_face(clip_id: str):
        """聞き取った言葉を話した人の顔画像 (JPEG)"""
        face = state.face(clip_id)
        if face is None:
            return error("顔画像が残っていません", 404)
        return Response(face, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    @app.websocket("/speech")
    async def speech_stream(websocket: WebSocket):
        """発話音声を受信のたびにバイナリで送る"""
        await websocket.accept()
        with state.speech.subscribe() as queue:
            async def sender():
                while True:
                    await websocket.send_bytes(await queue.get())

            send_task = asyncio.create_task(sender())
            try:
                # クライアントからは何も送られてこないので, 切断の検出だけを行う
                while (await websocket.receive())["type"] != "websocket.disconnect":
                    pass
            except WebSocketDisconnect:
                pass
            finally:
                send_task.cancel()

    # ---- DB から読む情報 (同期関数はスレッドプールで実行される) ----
    @app.get("/blackboard")
    def get_blackboard():
        """ロボットの行動とシナリオ"""
        try:
            kinds, goal = blackboard.actions()
            return {"actions": kinds, "goal": goal, "scenario": blackboard.scenario(SCENARIO_HISTORY_COUNT)}
        except PyMongoError as e:
            logger.warning("DBからの取得に失敗しました: %s", e)
            return error("ロボットの行動とシナリオを取得できません", 503)

    @app.get("/timeline")
    def get_timeline(minutes: int = 30):
        """直近 minutes 分のシナリオの遷移 (割り込みは段を分ける)"""
        try:
            return blackboard.timeline(min(max(minutes, 5), 24 * 60))
        except PyMongoError as e:
            logger.warning("シナリオの遷移の取得に失敗しました: %s", e)
            return error("シナリオの遷移を取得できません", 503)

    @app.get("/scenario_definition/{scenario_id}")
    def get_scenario_definition(scenario_id: str, interruption: bool = False):
        """シナリオの定義の要約 (優先度・発動条件・イベントなど)"""
        try:
            definition = catalog.definition(scenario_id, interruption)
        except PyMongoError as e:
            logger.warning("シナリオの定義の取得に失敗しました: %s", e)
            return error("シナリオの定義を取得できません", 503)
        if definition is None:
            return error("シナリオの定義が見つかりません", 404)
        return definition

    @app.get("/map.png")
    def get_map_png():
        try:
            data = blackboard.map_image()
        except PyMongoError as e:
            logger.warning("地図の取得に失敗しました: %s", e)
            return Response(status_code=503)
        if data is None:
            return Response(status_code=404)
        return Response(data["png"], media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    @app.get("/map.json")
    def get_map_info():
        """地図の座標情報と登録されている場所"""
        try:
            data = blackboard.map_image()
            if data is None:
                return error("地図がありません", 404)
            return {"info": data["info"], "locations": blackboard.locations()}
        except PyMongoError as e:
            logger.warning("地図の取得に失敗しました: %s", e)
            return error("地図を取得できません", 503)

    return app


def run(argv=None):
    """コマンドライン引数 (と --config の設定ファイル) に従ってサーバを起動する"""
    config = load_config(argv)
    # ページが数秒おきに状態を取りに来るので, 既定では警告以上だけを出す (アクセスログも出さない)
    log_level = config.get("log_level", "warning").lower()
    logging.basicConfig(level=log_level.upper())
    logger.info("設定: %s", config)
    uvicorn.run(
        create_app(config),
        host=config["web_host"],
        port=config["web_port"],
        log_level=log_level,
        access_log=log_level in ("debug", "info"),
    )


if __name__ == "__main__":
    run()
