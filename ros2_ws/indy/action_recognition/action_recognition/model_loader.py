"""Model loading shared by the recognition nodes.

A model is loaded from the local ``model_path`` when the file exists.
Otherwise it is downloaded from the Hugging Face Hub (``model_repo_id``,
``model_filename``, ``model_revision``) and cached under
``~/.cache/huggingface`` (or ``$HF_HOME``), so the download happens only once.
Set ``HF_HUB_OFFLINE=1`` to use the cached file without network access.
"""

import os

import joblib

DEFAULT_REPO_ID = "yasutomo57jp/models-for-IndyXe"
DEFAULT_REVISION = "main"


def resolve_model_path(
    model_path: str,
    repo_id: str = DEFAULT_REPO_ID,
    filename: str = "",
    revision: str = DEFAULT_REVISION,
    logger=None,
) -> str:
    """Return a local path of the model, downloading it when necessary.

    :param model_path: local model file, used when it exists
    :param repo_id: Hugging Face model repository (empty: no download)
    :param filename: file name in the repository (empty: basename of model_path)
    :param revision: branch, tag or commit hash in the repository
    """
    if model_path and os.path.isfile(model_path):
        return model_path

    filename = filename or os.path.basename(model_path)
    if not repo_id or not filename:
        raise FileNotFoundError(
            f"model file '{model_path}' not found and no Hugging Face repository is set"
        )

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        raise ImportError(
            f"model file '{model_path}' not found; install huggingface_hub "
            "(pip install huggingface_hub) to download it automatically"
        ) from e

    if logger is not None:
        logger.info(
            f"'{model_path}' not found, fetching {repo_id}/{filename}@{revision}"
        )
    return hf_hub_download(
        repo_id=repo_id, filename=filename, revision=revision or None
    )


def declare_model_parameters(node, default_model_path: str) -> None:
    """Declare the model parameters of a recognition node."""
    node.declare_parameter("model_path", default_model_path)
    node.declare_parameter("model_repo_id", DEFAULT_REPO_ID)
    node.declare_parameter("model_filename", "")
    node.declare_parameter("model_revision", DEFAULT_REVISION)


def load_model_from_node(node):
    """Load the model specified by the parameters of ``node``."""

    def param(name: str) -> str:
        return node.get_parameter(name).get_parameter_value().string_value

    model_path = param("model_path")
    node.get_logger().info(f"Recognizer Model Path: {model_path}")
    path = resolve_model_path(
        model_path,
        repo_id=param("model_repo_id"),
        filename=param("model_filename"),
        revision=param("model_revision"),
        logger=node.get_logger(),
    )
    node.get_logger().info(f"Loading model: {path}")
    return joblib.load(path)
