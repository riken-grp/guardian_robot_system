"""attribute_recognition_node: the model is downloaded from Hugging Face when not found."""

import sys
from types import SimpleNamespace

import pytest
import rclpy
from rclpy.parameter import Parameter

import scene_understanding.attribute_recognition_node as arn


@pytest.fixture
def env(monkeypatch, tmp_path):
    downloads = []

    def hf_hub_download(repo_id, filename, revision=None):
        downloads.append((repo_id, filename, revision))
        return str(tmp_path / "cache" / filename)

    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=hf_hub_download)
    )
    loaded = []

    class FakeRecognizer:
        def __init__(self, model_file):
            loaded.append(model_file)
            self.model = None

    monkeypatch.setattr(arn, "AttributeRecognizer", FakeRecognizer)
    monkeypatch.setattr(arn, "log_torch_device", lambda *a: None)
    monkeypatch.chdir(tmp_path)
    rclpy.init()
    nodes = []
    yield SimpleNamespace(downloads=downloads, loaded=loaded, tmp=tmp_path, nodes=nodes)
    for n in nodes:
        n.destroy_node()
    rclpy.shutdown()


def make_node(env, **params):
    """Create the node; parameters are read in __init__, so pass overrides."""
    from rclpy.node import Node

    overrides = [Parameter(k, value=v) for k, v in params.items()]
    orig = Node.__init__

    def init(self, name, **kw):
        orig(self, name, parameter_overrides=overrides, **kw)

    Node.__init__ = init
    try:
        n = arn.AttributeRecognitionNode()
    finally:
        Node.__init__ = orig
    env.nodes.append(n)
    return n


def test_downloads_when_not_found(env):
    make_node(env)
    assert env.downloads == [("yasutomo57jp/models-for-IndyXe", "attributes_pa100kb.pth", "main")]
    assert env.loaded == [str(env.tmp / "cache" / "attributes_pa100kb.pth")]


def test_local_file_is_used(env):
    (env.tmp / "attributes_pa100kb.pth").write_bytes(b"x")
    make_node(env)
    assert env.downloads == []
    assert env.loaded == ["attributes_pa100kb.pth"]


def test_repository_parameters(env):
    make_node(env, model_file="/nowhere/a.pth", model_repo_id="me/models",
              model_filename="attr/b.pth", model_revision="v1")
    assert env.downloads == [("me/models", "attr/b.pth", "v1")]


def test_no_repository(env):
    with pytest.raises(FileNotFoundError):
        make_node(env, model_file="/nowhere/a.pth", model_repo_id="")
