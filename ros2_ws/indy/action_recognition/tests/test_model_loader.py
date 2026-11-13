import sys
from types import SimpleNamespace

import pytest

from action_recognition.model_loader import resolve_model_path


def _fake_hub(monkeypatch, calls):
    def hf_hub_download(repo_id, filename, revision=None):
        calls.append((repo_id, filename, revision))
        return f"/cache/{repo_id}/{filename}"

    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=hf_hub_download)
    )


def test_local_file_has_priority(tmp_path, monkeypatch):
    calls = []
    _fake_hub(monkeypatch, calls)
    local = tmp_path / "wheelchair_model.joblib"
    local.write_bytes(b"")
    assert resolve_model_path(str(local), repo_id="user/repo") == str(local)
    assert calls == []


def test_download_when_local_file_is_missing(tmp_path, monkeypatch):
    calls = []
    _fake_hub(monkeypatch, calls)
    missing = str(tmp_path / "models" / "wheelchair_model.joblib")
    path = resolve_model_path(missing, repo_id="user/repo", revision="v1")
    assert path == "/cache/user/repo/wheelchair_model.joblib"
    assert calls == [("user/repo", "wheelchair_model.joblib", "v1")]


def test_explicit_filename(monkeypatch):
    calls = []
    _fake_hub(monkeypatch, calls)
    resolve_model_path("", repo_id="user/repo", filename="looking_at_model.joblib")
    assert calls == [("user/repo", "looking_at_model.joblib", "main")]


def test_no_repo_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve_model_path(str(tmp_path / "none.joblib"), repo_id="")
