"""Japanese morphological analysis of ASR results with Janome.

Provides the same kind of information as kad/asr's juman_* fields, using
Janome (pure Python, pip only).  Without Janome, :func:`analyze` returns None.
"""

try:
    from janome.tokenizer import Tokenizer
except ImportError:  # pragma: no cover - janome is optional
    Tokenizer = None

_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None and Tokenizer is not None:
        _tokenizer = Tokenizer()  # loading the dictionary takes ~0.1 s: only once
    return _tokenizer


def to_hiragana(text: str) -> str:
    """Katakana converted to hiragana (other characters unchanged)."""
    return ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in text)


def analyze(text: str) -> dict | None:
    """Morphological analysis of ``text``.

    Returns a dict of per-morpheme lists (all the same length except span):
      surface: surface forms
      base_form: base forms (e.g. 行き -> 行く)
      reading: readings in hiragana (the surface form for unknown words)
      pos: parts of speech (IPADIC, e.g. "名詞,一般")
      span: consecutive morphemes of the same major part of speech joined
    None if Janome is not available.
    """
    tokenizer = _get_tokenizer()
    if tokenizer is None:
        return None

    surface, base_form, reading, pos = [], [], [], []
    span, prev_major = [], None
    for t in tokenizer.tokenize(text):
        surface.append(t.surface)
        base_form.append(t.base_form if t.base_form != '*' else t.surface)
        reading.append(to_hiragana(t.reading if t.reading != '*' else t.surface))
        p = [x for x in t.part_of_speech.split(',') if x != '*']
        pos.append(','.join(p))
        major = p[0] if p else ''
        if span and major == prev_major:
            span[-1] += t.surface
        else:
            span.append(t.surface)
        prev_major = major
    return {
        'surface': surface,
        'base_form': base_form,
        'reading': reading,
        'pos': pos,
        'span': span,
    }
