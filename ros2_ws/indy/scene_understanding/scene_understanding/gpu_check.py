# coding: utf-8 -*-
"""起動時に各モデルが実際に GPU で動いているかをログに出す."""

import os

import torch
from rclpy.impl.rcutils_logger import RcutilsLogger


def _visible_devices() -> str:
    return os.environ.get("CUDA_VISIBLE_DEVICES", "(unset)")


def log_torch_device(logger: RcutilsLogger, label: str, model: torch.nn.Module) -> None:
    device = next(model.parameters()).device
    if device.type != "cuda":
        logger.warn(f"{label} runs on CPU ({device})")
        return
    props = torch.cuda.get_device_properties(device)
    bus_id = getattr(props, "pci_bus_id", "?")
    logger.info(
        f"{label} runs on GPU: {props.name} ({device}, pci_bus_id={bus_id}, "
        f"CUDA_VISIBLE_DEVICES={_visible_devices()})"
    )


def log_dlib_device(logger: RcutilsLogger, label: str) -> None:
    import dlib

    # dlib は CUDA 無しでビルドされていると警告なしに CPU で動く
    if not dlib.DLIB_USE_CUDA:
        logger.warn(f"{label} runs on CPU (dlib built without CUDA)")
        return
    num = dlib.cuda.get_num_devices()
    if num == 0:
        logger.warn(f"{label} runs on CPU (dlib found no CUDA device)")
        return
    logger.info(
        f"{label} runs on GPU: dlib CUDA devices={num}, "
        f"CUDA_VISIBLE_DEVICES={_visible_devices()}"
    )


def log_onnx_providers(logger: RcutilsLogger, label: str, providers: list) -> None:
    # onnxruntime は CUDAExecutionProvider が使えないと警告のみで CPU にフォールバックする
    if "CUDAExecutionProvider" in providers:
        logger.info(
            f"{label} runs on GPU: {providers}, "
            f"CUDA_VISIBLE_DEVICES={_visible_devices()}"
        )
    else:
        logger.warn(f"{label} runs on CPU: {providers}")
