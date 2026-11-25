"""ロボットの発話 (Actions の speak) を, このサーバで音声合成してブラウザで再生できるようにする

ロボットの rosTTS (Indy の blr/robot) は合成した音声をスピーカーで鳴らすだけで ROS には流さないので,
同じ声の設定 (persona.Voice の voice_params) を使ってこちらでも合成する.
rosTTS が発話を始めた (status が is_playing になった) ときにブラウザへ知らせ, 音声は
GET /robot_voice/{id} で渡す. 待ち (waiting) のうちに合成を始めて遅れを減らす.
"""
import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO

import requests
from bson import ObjectId
from pymongo import DESCENDING, MongoClient
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

POLL_INTERVAL = 0.3  # Actions を見に行く間隔 (秒)
SCAN_LIMIT = 5  # 一度に見る最新の speak の数
VOICE_PARAMS_TTL = 60  # 声の設定を読み直す間隔 (秒)
AUDIO_CACHE_COUNT = 20  # 覚えておく合成音声の数
LATE_DONE_SEC = 2.0  # is_playing を見逃して done になっていても, この秒数以内に終わったものは再生する
HTTP_TIMEOUT = 15
MAX_TEXT_LENGTH = 300  # rosTTS と同じく, これより長いと「入力音声が長すぎます。」と言う
PERSONA_DB = "persona"


def _speak_text(option, empty_text):
    """pyindy の grp_tts と同じく, 空なら短い声, text が無ければ「言葉に詰まりました」"""
    if "text" not in option:
        return "言葉に詰まりました"
    text = str(option["text"])
    if len(text) > MAX_TEXT_LENGTH:
        return "入力音声が長すぎます。"
    return text or empty_text


def synthesize(option, voice):
    """speak の option を voice_params に従って合成する. 返り値は (音声のバイト列, MIME タイプ, 再生速度).
    デコードはブラウザに任せる (ffmpeg 不要). 再生速度は pyindy の change_pitch_resample と同じく
    音の高さも変わる速度 (Web Audio の playbackRate)"""
    kind = voice.get("type")
    params = voice.get("params") or {}
    if "file" in option:
        raise ValueError("ロボット上のファイルの再生は合成できません")
    if kind == "gtts":
        from gtts import gTTS

        buffer = BytesIO()
        gTTS(_speak_text(option, "うっ"), lang="ja").write_to_fp(buffer)
        # rosTTS は tts_from_gtts(rate=params.rate). rate 倍の数のサンプルに間引くので 1/rate 倍速になる
        rate = float(params.get("rate", 1.0)) or 1.0
        return buffer.getvalue(), "audio/mpeg", 1.0 / rate
    if kind == "hoya":
        # rosTTS は tts_from_hoya(tts_rate=params.rate). 速さはサーバが変え, pitch は既定の 1.0
        body = {"tts_rate": params.get("rate", 1.0), "tts_pitch": 1.0,
                "text": _speak_text(option, "おっ")}
        if "text_ssml" in option:
            body["text_ssml"] = option["text_ssml"] or "えっ"
        response = requests.post(voice["server"], json=body, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.content, "audio/wav", 1.0
    # それ以外は rosTTS では tts_from_http_mp3 (option.url の MP3 を鳴らす)
    if "url" not in option:
        raise ValueError(f"声の種類 {kind!r} で url がありません")
    response = requests.get(option["url"], timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    return response.content, "audio/mpeg", 1.0


class RobotVoice:
    """Actions の speak を見張り, 発話が始まったら events (Broadcaster) に JSON で知らせる.
    聞いているブラウザが無い間は合成しない"""

    def __init__(self, host, port, db_name, robot_name, events):
        client = MongoClient(host, port, serverSelectionTimeoutMS=3000)
        self._actions = client[db_name]["Actions"]
        self._voice_col = client[PERSONA_DB]["Voice"]
        self._robot_name = robot_name
        self._events = events
        self._voice = None
        self._voice_time = 0.0
        self._jobs = OrderedDict()  # Actions の _id -> 合成の Future
        self._status = {}  # Actions の _id -> 最後に見た status
        self._announced = set()
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="robot_voice")
        self._stop = threading.Event()
        self._started = None  # これより前の発話は再生しない (起動時の ObjectId)
        self._warned = False

    def start(self):
        self._started = ObjectId.from_datetime(datetime.now(timezone.utc))
        threading.Thread(target=self._run, name="robot_voice_watch", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def audio(self, action_id):
        """合成済みの音声 (バイト列, MIME タイプ). 合成中なら終わるまで待つ. 無ければ None"""
        with self._lock:
            job = self._jobs.get(action_id)
        if job is None:
            return None
        try:
            data, mime, _ = job.result(timeout=HTTP_TIMEOUT + 5)
        except Exception:
            return None
        return data, mime

    # ---- 見張り ----
    def _run(self):
        while not self._stop.wait(POLL_INTERVAL):
            if not self._events.has_subscribers():
                continue
            try:
                self._check()
                self._warned = False
            except PyMongoError as e:
                if not self._warned:
                    logger.warning("ロボットの発話の取得に失敗しました: %s", e)
                    self._warned = True

    def _voice_params(self):
        now = time.monotonic()
        if self._voice is None or now - self._voice_time > VOICE_PARAMS_TTL:
            self._voice = self._voice_col.find_one({"key": "voice_params"}) or {"type": "gtts", "params": {}}
            self._voice_time = now
        return self._voice

    def _check(self):
        docs = list(
            self._actions.find(
                {"actor": self._robot_name, "command": "speak", "_id": {"$gte": self._started}},
                {"option": 1, "status": 1, "last_update": 1},
            ).sort("_id", DESCENDING).limit(SCAN_LIMIT)
        )
        for doc in reversed(docs):  # 古い順に
            action_id = str(doc["_id"])
            status = doc.get("status", "")
            previous = self._status.get(action_id)
            self._status[action_id] = status
            if status in ("waiting", "is_playing", "done") and action_id not in self._jobs:
                if status == "done" and not _recent(doc.get("last_update")):
                    continue
                self._start_job(action_id, doc.get("option") or {})
            if action_id in self._announced:
                if status == "stopped" and previous != "stopped":
                    self._events.publish({"type": "stop", "id": action_id})
                continue
            if status == "is_playing" or (status == "done" and previous is None and action_id in self._jobs):
                self._announced.add(action_id)
                text = str((doc.get("option") or {}).get("text", ""))
                self._jobs[action_id].add_done_callback(
                    lambda job, action_id=action_id, text=text: self._announce(action_id, text, job))
        # 古いものは忘れる
        with self._lock:
            while len(self._jobs) > AUDIO_CACHE_COUNT:
                old, _ = self._jobs.popitem(last=False)
                self._status.pop(old, None)
                self._announced.discard(old)

    def _start_job(self, action_id, option):
        voice = self._voice_params()
        with self._lock:
            self._jobs[action_id] = self._executor.submit(synthesize, option, voice)

    def _announce(self, action_id, text, job):
        """合成が終わったら, まだ止められていなければブラウザに知らせる (合成のスレッドから呼ばれる)"""
        if job.cancelled():
            return
        error = job.exception()
        if error is not None:
            logger.warning("ロボットの発話の音声合成に失敗しました (%s): %s", text, error)
            self._events.publish({"type": "error", "id": action_id, "text": text,
                                  "message": f"音声合成に失敗しました: {error}"})
            return
        if self._status.get(action_id) == "stopped":
            return
        rate = job.result()[2]
        self._events.publish({"type": "speak", "id": action_id, "text": text, "rate": rate,
                              "url": f"/robot_voice/{action_id}"})


def _recent(last_update):
    """LATE_DONE_SEC 秒以内か. Actions の時刻は naive な UTC"""
    if last_update is None:
        return False
    return (datetime.now(timezone.utc) - last_update.replace(tzinfo=timezone.utc)).total_seconds() < LATE_DONE_SEC
