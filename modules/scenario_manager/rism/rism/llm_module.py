import time
from logging import getLogger

from pyindy.llm import GRPNCM


class LLMModule:
    def __init__(self, config: dict) -> None:
        self.LMM = GRPNCM
        self.ncms = {}
        self.config = config
        host = config["prev_ncm"]["host"]
        port = config["prev_ncm"]["port"]
        self.url = f"http://{host}:{port}/ncms"

        # Retry settings
        self.max_retries = config.get("llm_max_retries", 3)
        self.retry_delay = config.get("llm_retry_delay", 2.0)
        self.retry_backoff = config.get("llm_retry_backoff", 2.0)

        self._logger = getLogger(__name__)

    def generate_utterance(
        self, model: str, prev_speaker: str, input_text: str, contexts: list, opts: dict
    ) -> dict:
        # LLMを使って1つの発話を生成する
        if model not in self.ncms:
            self.ncms[model] = self.LMM(self.url)

        ret = self._retry_llm_call(
            lambda: self.ncms[model].get_response(prev_speaker, input_text, contexts),
            operation_name="generate_utterance"
        )
        return ret

    def _retry_llm_call(self, llm_func, operation_name="LLM call"):
        """
        LLM呼び出しをリトライ機能付きで実行する

        Args:
            llm_func: 実行するLLM関数
            operation_name: ログに出力する操作名

        Returns:
            LLMのレスポンス

        Raises:
            Exception: 最大リトライ回数を超えた場合
        """
        last_exception = None
        delay = self.retry_delay

        for attempt in range(self.max_retries):
            try:
                self._logger.debug(f"{operation_name}: attempt {attempt + 1}/{self.max_retries}")
                result = llm_func()

                # 成功した場合、結果を返す
                if result is not None:
                    if attempt > 0:
                        self._logger.info(f"{operation_name} succeeded on attempt {attempt + 1}")
                    return result
                else:
                    self._logger.warning(f"{operation_name} returned None on attempt {attempt + 1}")
                    last_exception = ValueError("LLM returned None")

            except Exception as e:
                last_exception = e
                self._logger.warning(
                    f"{operation_name} failed on attempt {attempt + 1}/{self.max_retries}: {e}"
                )

            # 最後の試行でない場合は待機
            if attempt < self.max_retries - 1:
                self._logger.info(f"Waiting {delay:.1f} seconds before retry...")
                time.sleep(delay)
                delay *= self.retry_backoff

        # すべてのリトライが失敗した場合
        error_msg = f"{operation_name} failed after {self.max_retries} attempts"
        self._logger.error(error_msg)

        # エラーメッセージを含む辞書を返す（Noneではなく）
        return {
            "error": True,
            "message": error_msg,
            "last_exception": str(last_exception),
            "sentence": "[LLMエラー: 応答を生成できませんでした]"
        }

    def generate_scenario(self, opts: dict) -> dict:
        # LLMを使ってシナリオを生成する
        # 状況optsを元に，シナリオのlistを生成
        # 以下はダミー

        data = {}
        data["events"] = [
            {
                "actor": "robot1",
                "utterance": {
                    "sentence": "LLMで生成したシナリオにそって話をしよう",
                    "type": "normal",
                },
            },
            {
                "actor": "robot2",
                "utterance": {"sentence": "こんにちは", "type": "normal"},
            },
            {
                "actor": "robot1",
                "utterance": {"sentence": "こんにちは", "type": "normal"},
            },
            {
                "actor": "robot1",
                "utterance": {"sentence": "あなたは誰ですか？", "type": "normal"},
            },
            {
                "actor": "robot2",
                "utterance": {"sentence": "あなたは誰ですか？", "type": "normal"},
            },
            {
                "actor": "robot1",
                "utterance": {"sentence": "私は{t[robot1]}です", "type": "blank"},
            },
            {
                "actor": "robot2",
                "utterance": {"sentence": "私は{t[robot2]}です", "type": "blank"},
            },
            {
                "actor": "robot1",
                "utterance": {"sentence": "あそこに誰かがいるよ", "type": "blank"},
            },
            {
                "actor": "robot2",
                "utterance": {"sentence": "ほんとだね", "type": "normal"},
            },
            {"actor": "robot1", "utterance": {"sentence": "", "type": "generate"}},
            {"actor": "robot2", "utterance": {"sentence": "うわぁ", "type": "normal"}},
            {"actor": "robot1", "utterance": {"sentence": "おーい", "type": "normal"}},
            {"actor": "person", "timeout": 10, "type": "asr", "interruptable": False},
        ]
        data["blanks"] = ["person"]
        data["subevents"] = {
            "success": [
                {
                    "speaker": "robot1",
                    "sentence": "返事してくれてありがとう",
                    "type": "normal",
                },
                {"speaker": "robot2", "sentence": "", "type": "generate"},
            ],
            "failure": [
                {"speaker": "robot2", "sentence": "返事してくれよ", "type": "normal"},
                {"speaker": "robot1", "sentence": "", "type": "generate"},
            ],
        }
        return data
