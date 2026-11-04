# coding: utf-8
"""Kanji/kana -> Hepburn-romaji conversion, replacing pykakasi (GPL) with janome (Apache-2.0).

janome only provides morphological analysis and katakana readings; the
reading -> romaji table below fills in what pykakasi used to do internally.
"""

from janome.tokenizer import Tokenizer

_LONG_VOWEL = "ー"
_SMALL_TSU = "ッ"
_VOWELS = "aiueo"

_YOON = {
    "キャ": "kya", "キュ": "kyu", "キョ": "kyo",
    "ギャ": "gya", "ギュ": "gyu", "ギョ": "gyo",
    "シャ": "sha", "シュ": "shu", "ショ": "sho",
    "ジャ": "ja", "ジュ": "ju", "ジョ": "jo",
    "チャ": "cha", "チュ": "chu", "チョ": "cho",
    "ヂャ": "ja", "ヂュ": "ju", "ヂョ": "jo",
    "ニャ": "nya", "ニュ": "nyu", "ニョ": "nyo",
    "ヒャ": "hya", "ヒュ": "hyu", "ヒョ": "hyo",
    "ビャ": "bya", "ビュ": "byu", "ビョ": "byo",
    "ピャ": "pya", "ピュ": "pyu", "ピョ": "pyo",
    "ミャ": "mya", "ミュ": "myu", "ミョ": "myo",
    "リャ": "rya", "リュ": "ryu", "リョ": "ryo",
    "ファ": "fa", "フィ": "fi", "フェ": "fe", "フォ": "fo",
    "ウィ": "wi", "ウェ": "we", "ウォ": "wo",
    "ティ": "ti", "トゥ": "tu",
    "ディ": "di", "ドゥ": "du",
    "ヴァ": "va", "ヴィ": "vi", "ヴェ": "ve", "ヴォ": "vo",
    "シェ": "she", "ジェ": "je", "チェ": "che",
    "ツァ": "tsa", "ツィ": "tsi", "ツェ": "tse", "ツォ": "tso",
}

_MORA = {
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヲ": "o", "ン": "n",
    "ヴ": "vu", "ヰ": "i", "ヱ": "e",
}

_tokenizer = Tokenizer()


def _next_romaji(katakana: str, idx: int) -> str:
    if idx >= len(katakana):
        return ""
    pair = katakana[idx:idx + 2]
    if pair in _YOON:
        return _YOON[pair]
    return _MORA.get(katakana[idx], "")


def katakana_to_romaji(katakana: str) -> str:
    """Convert a katakana string to Hepburn-style romaji."""
    parts = []
    i = 0
    n = len(katakana)
    while i < n:
        ch = katakana[i]

        if ch == _LONG_VOWEL:
            if parts and parts[-1]:
                parts.append(parts[-1][-1])
            i += 1
            continue

        if ch == _SMALL_TSU:
            nxt = _next_romaji(katakana, i + 1)
            if nxt and nxt[0] not in _VOWELS:
                parts.append(nxt[0])
            i += 1
            continue

        pair = katakana[i:i + 2]
        if pair in _YOON:
            parts.append(_YOON[pair])
            i += 2
            continue

        if ch in _MORA:
            parts.append(_MORA[ch])
            i += 1
            continue

        # Not kana (already romaji, punctuation, unknown symbol): keep as-is.
        parts.append(ch)
        i += 1

    return "".join(parts)


def get_reading(text: str) -> str:
    """Return the katakana reading of text using janome's morphological analysis."""
    readings = []
    for token in _tokenizer.tokenize(text):
        reading = token.reading
        if not reading or reading == "*":
            reading = token.surface
        readings.append(reading)
    return "".join(readings)


def to_hepburn(text: str) -> str:
    """Romanize Japanese text (kanji/kana) to Hepburn-style romaji."""
    return katakana_to_romaji(get_reading(text))
