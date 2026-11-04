#!/usr/bin/env python
# coding: utf-8 -*-
import re
from collections import defaultdict
from random import choice
from typing import List, Literal, Tuple, TypedDict

DEFAULT_HASHTAG_REGEX = r"(?:#|＃)(\S*?)(?=#|＃|\Z)"
DEFAULT_CMD_REGEX = (
    r"(^(?:待つ(?:：|\:)|それから(?:？|\?)(?:：|\:)"
    + r"|聞き返し(?:：|\:)|無視(?:：|\:))?)(.+)$"
)

DEFAULT_EYES_DICT = defaultdict(lambda: "neutral1.jpg")
DEFAULT_EYES_DICT.update(
    {
        "smiling": "smile.jpg",
        "excited": "smile.jpg",
        "cheering": "smile.jpg",
        "smile": "smile.jpg",
        "clapping": "smile.jpg",
        "cheering": "smile.jpg",
        "laughing": "smile.jpg",
        "thinking": "thinking.jpg",
        "thoughtful": "thinking.jpg",
        "sympathizing": "sad.jpg",
        "concerned": "sad.jpg",
        "bowing": "sad.jpg",
        "warning": "sad.jpg",
    }
)

DEFAULT_FILLERS = [
    "うん",
    "んん",
    "ふん",
    "ぅん",
    "うぅん",
    "うむ",
    "うん",
]

DEFAULT_ASK = ["フムフム", "それから？", "それで", "なるほど"]


LlmRole = Literal["system", "assistant", "user"]


class LlmChatTurn(TypedDict):
    role: LlmRole
    content: str


LlmChatHistory = List[LlmChatTurn]


def format_history(history: LlmChatHistory) -> LlmChatHistory:
    if not history:
        return history
    new_history = [history[0]]
    for turn in history[1:]:
        if turn["role"] == "system":
            continue
        elif turn["role"] == new_history[-1]["role"]:
            new_history[-1]["content"] += "\n" + turn["content"]
        else:
            new_history.append(turn)
    return new_history


def parse_llm_response_hashtags(
    resp: str,
    ht_regex: str = DEFAULT_HASHTAG_REGEX,
    cmd_regex: str = DEFAULT_CMD_REGEX,
) -> Tuple[str, str, List[str]]:
    m = re.match(cmd_regex, resp)
    if m is None:
        return ("", "", [])
    head = m.group(1).strip()
    resp = m.group(2).strip()

    tags = [m.group(1).strip() for m in re.finditer(ht_regex, resp)]

    tags = [t for t in tags if t]

    resp = re.sub(ht_regex, "", resp).strip()

    return (head, resp, tags)


def sanitize_llm_response(resp: str) -> str:
    # Pattern 1: 4 repetitions into 1
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


def create_diag_turn(role: LlmRole, content: str) -> LlmChatTurn:
    return {"role": role, "content": content}


def choose_filler() -> str:
    return choice(DEFAULT_FILLERS)


def choose_ask() -> str:
    return choice(DEFAULT_ASK)


def create_gesture(name: str, duration=1.0) -> dict:
    return {
        "duration": duration,
        "gesture": name,
        "type": "normal",
        "command": name,
    }


def create_eye(fname: str, duration=1.0) -> dict:
    return {"type": "normal", "image": fname, "duration": duration}
