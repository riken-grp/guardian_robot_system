import time
from logging import getLogger
from typing import Dict, List, NamedTuple
from collections.abc import Callable
from openai import OpenAI
from openai.types.chat import ChatCompletion
from pymongo import MongoClient


class LanguageModelWrapper:
    def __init__(
        self,
        api_url: str,
        model_name: str,
        system_prompt: str,
        defaults: dict = {},
        api_key: str = "EMPTY",
    ):
        self._model_name = model_name

        self.client = OpenAI(base_url=api_url, api_key=api_key)
        self._system_prompt = system_prompt
        self._defaults = defaults
        if "retries" not in defaults:
            self._defaults["retries"] = 3

        self._logger = getLogger(__name__)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def defaults(self) -> dict:
        return self._defaults

    def get_response(
        self,
        prompt: str,
        dialog_history: List[Dict[str, str]],
        **llm_opts,
    ) -> str:
        resps = self.get_n_responses(prompt, dialog_history, **llm_opts)

        return resps[0] if resps else ""

    def get_n_responses(
        self,
        prompt: str,
        dialog_history: List[Dict[str, str]],
        n: int = 1,
        **llm_opts,
    ) -> List[str]:
        """Gets responses from the Large Language Model.
        - `prompt` is to provide instructions to the LLM.
        - `history` includes the user's latest dialog turn.
        - `llm_opts` can include options passed to the LLM (see below)

        History length is decided by the Scenario Manager.

        Some possible LLM options:
        - `temperature`: Sampling temp, affects diversity of generation.
        - `top_p`: alternative sampling based on top probability.
        - `max_tokens`: Limits the size of the response.
        - `stop`: string or list of strings that delimit when the LLM will stop.

        `temperature` and `top_p` affect randomness.
        Higher temperature/Top-P produces more random output.
        Lower produces more consistent output (i.e. with the same prompt & history)

        For Indy's pre-trained models, we can use `temperature` and `stop`
        """
        msgs = [{"role": "system", "content": self._system_prompt}]
        if prompt:
            msgs.append({"role": "system", "content": f"\n{prompt}"})

        # Must be pre-formatted based on roles: "system", "user" and "assistant"
        msgs.extend(dialog_history)

        opts = {}
        opts.update(self._defaults)

        opts.update(llm_opts)

        if "retries" in opts:
            retries = opts["retries"]
            del opts["retries"]

        for i in range(retries):
            try:
                response = self.client.chat.completions.create(
                    model=self._model_name, messages=msgs, n=n, **opts  # type: ignore
                )
                self._logger.debug(f"LLM Response #{i+1}: {response}")
                return [
                    str(choiche.message.content)
                    for choiche in response.choices
                ]
            except Exception as e:
                self._logger.warning(
                    f"{e.__class__.__name__} in LLM Response Generation: "
                    + f"Details: {e}, Retry #{i+1}."
                )
                time.sleep(0.01)

        self._logger.error(
            "LLM Response Generation has exceeded expected retries "
            + f"({retries}). Returning Empty Response."
        )

        return []

    def get_validated_response(
        self,
        prompt: str,
        dialog_history: List[Dict[str, str]],
        selector: Callable[[List[str]], str],
        n: int = 5,
        **llm_opts,
    ) -> str:
        opts = {}
        opts.update(self._defaults)

        opts.update(llm_opts)

        outer_retries = 3
        if "retries" in opts:
            outer_retries = opts["retries"]
            opts["retries"] = 1

        for i in range(outer_retries):
            try:
                resps = self.get_n_responses(prompt, dialog_history, n, **opts)
                val_resp = selector(resps)
                if val_resp:
                    return val_resp
            except Exception as e:
                self._logger.warning(
                    f"{e.__class__.__name__} in LLM Response Generation: "
                    + f"Details: {e}, Retry #{i+1}."
                )
                time.sleep(0.01)

        self._logger.error(
            "LLM Validated Response Generation has exceeded expected retries "
            + f"({outer_retries}). Returning Empty Response."
        )

        return ""


class LlmLogInfo(NamedTuple):
    host: str
    port: int
    dbname: str
    coll: str


class LlmWrapperLogged(LanguageModelWrapper):
    def __init__(
        self,
        api_url: str,
        model_name: str,
        system_prompt: str,
        log_info: LlmLogInfo,
        defaults: Dict = {},
        api_key: str = "EMPTY",
    ):
        super().__init__(api_url, model_name, system_prompt, defaults, api_key)
        self._log_info = log_info
        db_client = MongoClient(self._log_info.host, self._log_info.port)
        self._col = db_client[self._log_info.dbname][self._log_info.coll]

    def get_n_responses(
        self,
        prompt: str,
        dialog_history: List[Dict[str, str]],
        n: int = 1,
        **llm_opts,
    ) -> List[str]:
        """Same as parent class."""
        log_msg = {}

        msgs = [{"role": "system", "content": self._system_prompt}]
        if prompt:
            msgs.append({"role": "system", "content": f"\n{prompt}"})

        # Must be pre-formatted based on roles: "system", "user" and "assistant"
        msgs.extend(dialog_history)

        opts = {}
        opts.update(self._defaults)

        opts.update(llm_opts)

        if "retries" in opts:
            retries = opts["retries"]
            del opts["retries"]

        log_msg["msgs"] = msgs
        log_msg["opts"] = opts

        resps = []

        for i in range(retries):
            try:
                response: ChatCompletion = self.client.chat.completions.create(
                    model=self._model_name, messages=msgs, n=n, **opts  # type: ignore
                )
                log_msg["status"] = "success"
                log_msg["completion"] = response.to_dict()

                self._logger.debug(f"LLM Response #{i+1}: {response}")
                resps = [
                    str(choiche.message.content)
                    for choiche in response.choices
                ]
                break
            except Exception as e:
                self._logger.warning(
                    f"{e.__class__.__name__} in LLM Response Generation: "
                    + f"Details: {e}, Retry #{i+1}."
                )
                time.sleep(0.01)
        if not resps:
            self._logger.error(
                "LLM Response Generation has exceeded expected retries "
                + f"({retries}). Returning Empty Response."
            )
            log_msg["status"] = "failure"

        try:
            self._col.insert_one(log_msg)
        except Exception as e:
            self._logger.error(
                f"LLM DB Logging failure: '{str(e)}'. "
                + "This call will not be logged in the Database."
            )

        return resps


def getValidatedWrapper(
    api_url: str,
    model_name: str,
    system_prompt: str,
    log_db_info: dict = {},
    defaults: Dict = {},
    api_key: str = "EMPTY",
) -> LanguageModelWrapper:
    """
    Creates and returns one of two wrappers:
    - a Regular LLM Wrapper if no logging information is provided, or
    - a LLM Wrapper that logs all calls to a database.
    The database-enabled wrapper is created only if its info is given.
    """
    try:
        log_info = LlmLogInfo(**log_db_info)
        return LlmWrapperLogged(
            api_url, model_name, system_prompt, log_info, defaults, api_key
        )
    except TypeError:
        # Fallback
        return LanguageModelWrapper(
            api_url, model_name, system_prompt, defaults, api_key
        )


class EmbeddingModelWrapper(LanguageModelWrapper):
    def __init__(
        self,
        api_url: str,
        model_name: str,
        api_key: str = "EMPTY",
    ):
        super().__init__(api_url, model_name, "", api_key=api_key)

    def get_response(
        self,
        prompt: str,
        dialog_history: List[Dict[str, str]],
        prompt_append=False,
        **llm_opts,
    ) -> str:
        raise NotImplementedError()

    def get_embeddings(self, text: str) -> List[float]:
        emb = self.client.embeddings.create(input=text, model=self.model_name)

        if emb.data:
            return emb.data[0].embedding

        return []
