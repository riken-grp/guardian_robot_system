from pymongo.database import Database

from .util.llm_output_helper import (
    DEFAULT_ASK,
    DEFAULT_FILLERS,
    LlmChatHistory,
    create_diag_turn,
    format_history,
)


class AsrInputTracker:
    def __init__(self, dialogue_db: Database) -> None:
        self.col = dialogue_db["dia"]
        self.asr_id = -1

    def get_history(self, N=10, t0: float = 0) -> LlmChatHistory:
        if N == 0:
            return []
        latest_data = list(
            self.col.find({"created_at_ts": {"$gte": t0}})
            .sort("created_at_ts", -1)
            .limit(N * 2)
        )
        flag = False
        idx = -1
        for i, doc in enumerate(latest_data):
            if doc["origin"] == "asr" and not flag:
                idx = i
                break
        hist = (
            [
                create_diag_turn(
                    "user" if doc["origin"] == "asr" else "assistant",
                    doc["utterance"],
                )
                for doc in latest_data[idx:]
                if not (
                    doc["utterance"] in DEFAULT_FILLERS
                    or doc["utterance"] in DEFAULT_ASK
                )
            ]
            if idx >= 0
            else []
        )
        hist = hist[:N]
        return format_history(hist[::-1])

    def has_new_asr(self, t_f: float = 0):
        latest_data = self.col.find_one(
            filter={"origin": "asr", "created_at_ts": {"$gte": t_f}},
            sort=[("created_at_ts", -1)],
        )
        if not latest_data:
            return False

        doc_id = latest_data["_id"]
        if self.asr_id == doc_id:
            # No new observations
            return False

        self.asr_id = doc_id

        return True
