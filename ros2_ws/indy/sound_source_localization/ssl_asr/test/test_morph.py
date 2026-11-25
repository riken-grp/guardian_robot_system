"""Tests for the Janome morphological analysis (morph.analyze)."""

import pytest

from ssl_asr import morph


def test_to_hiragana():
    assert morph.to_hiragana('ウケツケとトイレ') == 'うけつけとといれ'


def test_analyze():
    pytest.importorskip('janome')
    m = morph.analyze('トイレに行きたい')
    assert m['surface'] == ['トイレ', 'に', '行き', 'たい']
    assert m['base_form'] == ['トイレ', 'に', '行く', 'たい']
    assert m['reading'] == ['といれ', 'に', 'いき', 'たい']
    assert m['pos'][0] == '名詞,一般'
    assert m['span'] == ['トイレ', 'に', '行き', 'たい']


def test_analyze_unknown_word_and_span():
    pytest.importorskip('janome')
    m = morph.analyze('スタバ抹茶')
    # Unknown word: reading = surface form.  Consecutive nouns: one span
    assert m['reading'][0] == 'すたば'
    assert m['span'] == ['スタバ抹茶']
