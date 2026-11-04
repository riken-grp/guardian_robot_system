#!/usr/bin/env python
# coding: utf-8 -*-
import os
import re
from typing import List, Dict, Any

from bson import ObjectId
from bson.errors import InvalidId

from pyindy.llm.llm_wrapper import EmbeddingModelWrapper, getValidatedWrapper
from pymongo.database import Database
from rclpy.impl.rcutils_logger import RcutilsLogger
from rclpy.node import Node
from .. import substitute
from .. import ts_to_str_jst


class LlmRequestManager:
    def __init__(
        self,
        node: Node,
        db: Database,
        llm_settings: dict,
        emb_settings: dict | None = None,
    ) -> None:
        self.node = node

        self.__url = llm_settings["url"]
        self.__model = llm_settings["model"]
        self.__lang = llm_settings["lang"]
        self.__system_prompt = llm_settings["system_prompt"]
        self.__robot_name = llm_settings["robot_name"]
        self.__robot_alias = llm_settings["robot_alias"]
        self.__log_db = (
            {} if "log_db" not in llm_settings else llm_settings["log_db"]
        )

        self.__prompts_coll = (
            db.llm_prompts
            if "prompts_coll" not in llm_settings
            else db[llm_settings["prompts_coll"]]
        )
        self.__defauls = (
            llm_settings["defaults"] if "defaults" in llm_settings else {}
        )

        self.__api_key = (
            str(os.environ.get("OPENAI_API_KEY"))
            if "api.openai.com" in self.__url
            else (
                llm_settings["api_key"]
                if "api_key" in llm_settings
                else "EMPTY"
            )
        )

        self.llm = getValidatedWrapper(
            self.__url,
            self.__model,
            self.__system_prompt,
            api_key=self.__api_key,
            defaults=self.__defauls,
            log_db_info=self.__log_db,
        )

        self.emb_model = (
            None
            if emb_settings is None
            or "embed_api" not in emb_settings
            or not emb_settings["embed_api"]
            else EmbeddingModelWrapper(
                emb_settings["embed_api"]["url"],
                emb_settings["embed_api"]["model"],
                api_key=(
                    str(os.environ.get("OPENAI_API_KEY"))
                    if "api.openai.com" in emb_settings["embed_api"]["url"]
                    else emb_settings["embed_api"]["api_key"]
                ),
            )
        )
        self.__subs_hist = {"asr": "user", "tts": "assistant"}
        self.__subs_append = {
            "en": {"asr": 'USER:"{utt}"', "tts": 'ROBOT:"{utt}"'},
            "ja": {"asr": "ユーザー:「{utt}」", "tts": "ロボット:「{utt}」"},
        }

    @property
    def api_key(self) -> str:
        return self.llm.client.api_key

    @property
    def logger(self) -> RcutilsLogger:
        return self.node.get_logger()

    @property
    def model(self) -> str:
        return self.__model

    @property
    def robot_name(self) -> str:
        return self.__robot_name

    @property
    def robot_alias(self) -> str:
        return self.__robot_alias

    @property
    def url(self) -> str:
        return self.__url

    @property
    def system_prompt(self) -> str:
        return self.__system_prompt

    def get_prompt(self, name_or_id: str, substitutions: dict) -> str:
        prompt_base = self.__prompts_coll.find_one(filter={"name": name_or_id})
        if prompt_base:
            return substitute(prompt_base[self.__lang], substitutions)
        try:
            id = ObjectId(name_or_id)
        except (TypeError, ValueError, InvalidId):
            return ""

        prompt_base = self.__prompts_coll.find_one(filter={"_id": id})

        prompt_base = self.__prompts_coll.find_one(
            filter={"_id": ObjectId(name_or_id)}
        )

        if not prompt_base:
            return ""
        return substitute(prompt_base[self.__lang], substitutions)

    def generate(
        self,
        prompt_name_or_id: str,
        substitutions: dict,
        chat_history: list = [],
        llm_opts: dict = {},
        debug=False,
        date_to_add: float = -1,
        hist_to_prompt=False
    ) -> str:
        hist = [h for h in chat_history]
        prompt = self.get_prompt(prompt_name_or_id, substitutions)

        if date_to_add > 0:
            prompt += (
                "\n\n現在の日時はおよそ"
                + ts_to_str_jst(date_to_add, "%Y年%m月%d日 %H時%M分")
                + "です。"
            )

        if debug:
            self.logger.debug(f"[generate] prompt: {prompt}")
            self.logger.debug(f"[generate] history: {hist}")

        prompt_msg = [{"role": "system", "content": prompt}]
        hist = (hist + prompt_msg) if hist_to_prompt else prompt_msg + hist

        resp = self.llm.get_response("", hist, **llm_opts)

        return self.sanitize_response(resp)

    def generate_n_validate(
        self,
        prompt_name_or_id: str,
        substitutions: dict,
        chat_history: list = [],
        keywords: List[str] = [],
        n: int = 3,
        llm_opts: dict = {},
        debug=False,
        date_to_add: float = -1,
        hist_to_prompt=False
    ) -> str:
        hist = [h for h in chat_history]
        prompt = self.get_prompt(prompt_name_or_id, substitutions)

        if date_to_add > 0:
            prompt += (
                "\n\n現在の日時はおよそ"
                + ts_to_str_jst(date_to_add, "%Y年%m月%d日 %H時%M分")
                + "です。"
            )

        if debug:
            self.logger.debug(f"[generate] prompt: {prompt}")
            self.logger.debug(f"[generate] history: {hist}")

        def validator(choiches: List[str]) -> str:
            for c in choiches:
                if any(k in c for k in keywords):
                    return c
            return ""

        prompt_msg = [{"role": "system", "content": prompt}]
        hist = (hist + prompt_msg) if hist_to_prompt else prompt_msg + hist

        resp = self.llm.get_validated_response(
            "", hist, validator, n, **llm_opts
        )
        return self.sanitize_response(resp)

    def get_embeddings(self, text: str) -> List[float]:

        return (
            []
            if self.emb_model is None
            else self.emb_model.get_embeddings(text)
        )

    def count_tokens(self, text: str) -> int:
        url = str(self.llm.client.base_url) + "tokenize"
        body = {"model": self.__model, "prompt": text}
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
        }
        resp = self.llm.client.post(
            path=url,
            cast_to=Dict[str, Any],
            body=body,
            options={"headers": headers},
        )

        return int(resp["count"])

    def format_chat_history_dia(self, history: list) -> list:
        return [
            {"role": self.__subs_hist[d["origin"]], "content": d["utterance"]}
            for d in history
        ]

    def format_chat_history_append(self, history: list) -> str:
        s = self.__subs_append[self.__lang]
        return "\n".join(
            s[d["origin"]].format(utt=d["utterance"]) for d in history
        )

    def sanitize_response(self, resp: str) -> str:
        # Remove hash tags
        resp = (
            resp.replace(":\n", ": ").replace("### ", "").replace("\n\n", "\n")
        )
        if "#" in resp:
            resp = resp[: resp.index("#")].strip()

        # : 4+ repetitions into 1
        repeat4pattern = r"(\S+)\1\1\1"
        m = re.match(repeat4pattern, resp, re.I)
        while m:
            resp = re.sub(repeat4pattern, r"\1", resp)
            m = re.match(repeat4pattern, resp, re.I)

        # Pattern 2: Emoji, etc.
        # Based off: https://stackoverflow.com/a/33417311
        emojiPattern = (
            "["
            + "\U00002600-\U000027bf"  # symbols & dingbats
            + "\U0001f600-\U0001f64f"  # emoticons
            + "\U0001f300-\U0001f5ff"  # symbols & pictographs
            + "\U0001f680-\U0001f6ff"  # transport & map symbols
            + "\U0001f1e0-\U0001f1ff"  # flags (iOS)
            + "\U0001f900-\U0001f9ff"  # supp. symbols
            + "\U0001fa70-\U0001faff"  # supp. symbols ext. A
            + "]+"
        )

        resp = re.sub(emojiPattern, "", resp, flags=re.UNICODE)

        # RESERVED FOR FUTURE HEURISTICS/PATTERNS

        return resp
