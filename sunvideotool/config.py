from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml

from .exceptions import ConfigError


CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.yaml"
EXAMPLE_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.example.yaml"
RESERVED_PORTS = {3000, 5173, 5174, 5175, 5176, 7860, 8000, 8080}


def get_config_root(config_path: Path = CONFIG_FILE) -> Path:
    return config_path.resolve().parent


def load_config(config_path: Path | None = None) -> Dict[str, Any]:
    resolved_path = (config_path or CONFIG_FILE).resolve()
    if not resolved_path.exists():
        if resolved_path == CONFIG_FILE.resolve() and EXAMPLE_CONFIG_FILE.exists():
            raise ConfigError(
                "未找到 config.yaml。请先复制 config.example.yaml 为 config.yaml，"
                "并按本机情况填写目录与模型路径。"
            )
        raise ConfigError(f"配置文件不存在: {resolved_path}")

    with resolved_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    if not isinstance(config, dict):
        raise ConfigError("config.yaml 顶层必须是字典结构")

    return config


def save_config(config: Dict[str, Any], config_path: Path | None = None) -> None:
    resolved_path = (config_path or CONFIG_FILE).resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    payload = deepcopy(config)
    with resolved_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)


def require_mapping(config: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"config.yaml 缺少 {key} 配置段")
    return value


def require_string(mapping: Dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"配置项 {key} 不能为空")
    return value.strip()


def normalize_path(value: str, base_dir: Path | None = None) -> Path:
    raw_path = Path(value).expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve()

    base = (base_dir or get_config_root()).resolve()
    return (base / raw_path).resolve()


def build_runtime_paths(config: Dict[str, Any]) -> Dict[str, Path]:
    paths = require_mapping(config, "paths")
    return {
        "project_root": normalize_path(require_string(paths, "project_root")),
        "source_video_dir": normalize_path(require_string(paths, "source_video_dir")),
        "output_dir": normalize_path(require_string(paths, "output_dir")),
        "models_dir": normalize_path(require_string(paths, "models_dir")),
        "runtime_dir": normalize_path(require_string(paths, "runtime_dir")),
    }


def ensure_directories(config: Dict[str, Any]) -> None:
    paths = require_mapping(config, "paths")
    for key in ("project_root", "source_video_dir", "output_dir", "models_dir", "runtime_dir"):
        normalize_path(require_string(paths, key)).mkdir(parents=True, exist_ok=True)

    runtime_dir = normalize_path(require_string(paths, "runtime_dir"))
    for subdir in ("tmp", "logs"):
        (runtime_dir / subdir).mkdir(parents=True, exist_ok=True)


def resolve_binary(binary_value: str, binary_name: str) -> str:
    candidate = Path(binary_value).expanduser()
    if candidate.exists():
        return str(candidate.resolve())

    located = shutil.which(binary_value)
    if located:
        return located

    raise ConfigError(
        f"未找到 {binary_name} 可执行文件: {binary_value}。请先安装或修改 config.yaml。"
    )


def validate_config(config: Dict[str, Any]) -> Tuple[str, str]:
    paths = require_mapping(config, "paths")
    runtime = require_mapping(config, "runtime")
    yt_dlp_cfg = require_mapping(config, "yt_dlp")
    separator_cfg = require_mapping(config, "separator")

    for key in ("project_root", "source_video_dir", "output_dir", "models_dir"):
        require_string(paths, key)

    for key in ("ffmpeg_bin", "ffprobe_bin"):
        require_string(paths, key)

    for key in ("filename_template", "format"):
        require_string(yt_dlp_cfg, key)

    for key in (
        "backend",
        "model_file",
        "task_dir_time_format",
        "primary_stem_hint",
        "secondary_stem_hint",
        "internal_audio_format",
    ):
        require_string(separator_cfg, key)

    for key in ("device_preference", "log_level"):
        require_string(runtime, key)

    try:
        port = int(runtime.get("port", 18880))
    except (TypeError, ValueError):
        raise ConfigError("runtime.port 必须是整数")
    try:
        frontend_port = int(runtime.get("frontend_port", 18881))
    except (TypeError, ValueError):
        raise ConfigError("runtime.frontend_port 必须是整数")
    if port in RESERVED_PORTS or frontend_port in RESERVED_PORTS:
        raise ConfigError("请勿使用 3000/5173/5174/5175/5176/7860/8000/8080 等常见开发端口，请更换 runtime.port / runtime.frontend_port")
    if not 1024 <= port <= 65535:
        raise ConfigError("runtime.port 应在 1024-65535 之间")
    if not 1024 <= frontend_port <= 65535:
        raise ConfigError("runtime.frontend_port 应在 1024-65535 之间")

    ffmpeg_bin = resolve_binary(paths["ffmpeg_bin"], "ffmpeg")
    ffprobe_bin = resolve_binary(paths["ffprobe_bin"], "ffprobe")
    return ffmpeg_bin, ffprobe_bin
