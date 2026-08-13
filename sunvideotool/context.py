from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Dict

import torch

from .config import (
    build_runtime_paths,
    ensure_directories,
    load_config,
    require_mapping,
    require_string,
    validate_config,
)
from .exceptions import ConfigError


@dataclass
class AppContext:
    config: Dict[str, Any]
    device: str
    ffmpeg_bin: str
    ffprobe_bin: str
    logger: logging.Logger
    project_root: Path
    source_video_dir: Path
    output_dir: Path
    models_dir: Path
    runtime_dir: Path
    busy_lock: Lock = field(default_factory=Lock)

    @property
    def tmp_dir(self) -> Path:
        return self.runtime_dir / "tmp"


def resolve_device(config: Dict[str, Any]) -> str:
    runtime = require_mapping(config, "runtime")
    preferred = require_string(runtime, "device_preference").lower()
    allow_cpu_fallback = bool(runtime.get("allow_cpu_fallback", True))

    if preferred == "mps":
        if torch.backends.mps.is_available():
            return "mps"
        if not allow_cpu_fallback:
            raise ConfigError("当前机器未检测到可用的 Metal/MPS，且配置中禁用了 CPU fallback")
        return "cpu"

    return preferred


def setup_logger(level_name: str) -> logging.Logger:
    logger = logging.getLogger("SunVideoTool")
    logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level_name.upper(), logging.INFO))
    logger.propagate = False
    return logger


def build_context(config_path: Path | None = None) -> AppContext:
    config = load_config(config_path)
    ensure_directories(config)
    ffmpeg_bin, ffprobe_bin = validate_config(config)
    logger = setup_logger(require_mapping(config, "runtime").get("log_level", "INFO"))
    device = resolve_device(config)
    runtime_paths = build_runtime_paths(config)

    return AppContext(
        config=config,
        device=device,
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        logger=logger,
        project_root=runtime_paths["project_root"],
        source_video_dir=runtime_paths["source_video_dir"],
        output_dir=runtime_paths["output_dir"],
        models_dir=runtime_paths["models_dir"],
        runtime_dir=runtime_paths["runtime_dir"],
    )
