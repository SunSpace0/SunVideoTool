from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ..config import normalize_path, require_mapping, require_string
from ..exceptions import ProcessingError, SeparationError
from ..context import AppContext


def ensure_model_available(context: AppContext, log_cb: Callable[[str], None]) -> Path:
    separator_cfg = require_mapping(context.config, "separator")
    model_file = normalize_path(require_string(separator_cfg, "model_file"))
    if model_file.exists():
        return model_file

    if not bool(separator_cfg.get("auto_download_model", False)):
        raise ProcessingError(
            f"未找到分离模型文件: {model_file}。请先把模型放到 models 目录并更新 config.yaml。"
        )

    log_cb(f"本地未找到分离模型，开始自动下载: {model_file.name}")
    try:
        from audio_separator.separator import Separator

        separator = Separator(
            log_level=context.logger.level,
            model_file_dir=str(model_file.parent),
            output_dir=str(model_file.parent),
            output_format="WAV",
            use_autocast=False,
        )
        separator.download_model_and_data(model_file.name)
    except Exception as exc:
        raise ProcessingError(f"自动下载分离模型失败: {exc}") from exc

    if not model_file.exists():
        raise ProcessingError(f"模型下载流程已执行，但仍未找到文件: {model_file}")

    log_cb(f"分离模型已就绪: {model_file.name}")
    return model_file


def find_audio_files(directory: Path) -> List[Path]:
    candidates: List[Path] = []
    for suffix in (".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg"):
        candidates.extend(
            path
            for path in directory.rglob(f"*{suffix}")
            if not path.name.lower().startswith("separation_input")
        )
    return sorted({path.resolve() for path in candidates}, key=lambda item: item.stat().st_mtime)


def pick_stem_file(audio_files: Iterable[Path], preferred_token: str, fallback_token: str) -> Optional[Path]:
    preferred = preferred_token.lower()
    fallback = fallback_token.lower()

    preferred_matches = [path for path in audio_files if preferred in path.name.lower()]
    if preferred_matches:
        return preferred_matches[-1]

    fallback_matches = [path for path in audio_files if fallback in path.name.lower()]
    if fallback_matches:
        return fallback_matches[-1]

    return None


def locate_stems(task_dir: Path, config: Dict[str, Any]) -> Tuple[Path, Path]:
    separator_cfg = require_mapping(config, "separator")
    primary_hint = require_string(separator_cfg, "primary_stem_hint")
    secondary_hint = require_string(separator_cfg, "secondary_stem_hint")
    audio_files = find_audio_files(task_dir)
    if not audio_files:
        raise ProcessingError("分离完成后未找到任何音频输出")

    vocals = pick_stem_file(audio_files, primary_hint, "vocal")
    instrumental = pick_stem_file(audio_files, secondary_hint, "instrument")
    if not vocals or not instrumental:
        raise ProcessingError(
            "已生成分离结果，但未识别到人声/伴奏文件。请检查模型输出命名或调整 config.yaml。"
        )
    return vocals, instrumental


def run_audio_separator_backend(
    context: AppContext,
    audio_path: Path,
    task_dir: Path,
    model_file: Path,
    log_cb: Callable[[str], None],
) -> Optional[Tuple[Path, Path]]:
    try:
        module = importlib.import_module("audio_separator.separator")
    except ImportError:
        return None

    separator_cls = getattr(module, "Separator", None)
    if separator_cls is None:
        raise SeparationError("audio_separator.separator 中未找到 Separator 类")

    log_cb("检测到 audio-separator 后端，开始加载分离模型")
    try:
        separator = separator_cls(
            output_dir=str(task_dir),
            output_format="WAV",
            use_autocast=False,
            model_file_dir=str(model_file.parent),
        )
        separator.load_model(model_filename=model_file.name)
        separator.separate(str(audio_path))
    except Exception as exc:
        raise SeparationError(f"audio-separator 调用失败: {exc}") from exc

    return locate_stems(task_dir, context.config)


def run_custom_backend(
    context: AppContext,
    audio_path: Path,
    task_dir: Path,
    model_file: Path,
    log_cb: Callable[[str], None],
) -> Optional[Tuple[Path, Path]]:
    separator_cfg = require_mapping(context.config, "separator")
    module_name = str(separator_cfg.get("python_api_module", "")).strip()
    callable_name = str(separator_cfg.get("python_api_callable", "")).strip()
    if not module_name or not callable_name:
        return None

    log_cb(f"尝试调用自定义分离接口: {module_name}.{callable_name}")
    try:
        module = importlib.import_module(module_name)
        callable_obj = getattr(module, callable_name)
    except Exception as exc:
        raise SeparationError(f"无法导入自定义分离接口: {exc}") from exc

    try:
        result = callable_obj(
            input_audio=str(audio_path),
            output_dir=str(task_dir),
            model_path=str(model_file),
            device=context.device,
        )
    except TypeError as first_error:
        try:
            result = callable_obj(str(audio_path), str(task_dir), str(model_file), context.device)
        except Exception as second_error:
            raise SeparationError(
                f"自定义分离接口运行失败: {first_error}; 位置参数方式: {second_error}"
            ) from second_error
    except Exception as exc:
        raise SeparationError(f"自定义分离接口运行失败: {exc}") from exc

    if isinstance(result, (list, tuple)) and len(result) >= 2:
        return Path(result[0]).resolve(), Path(result[1]).resolve()

    return locate_stems(task_dir, context.config)


def separate_audio(
    context: AppContext,
    audio_path: Path,
    task_dir: Path,
    log_cb: Callable[[str], None],
) -> Tuple[Path, Path]:
    separator_cfg = require_mapping(context.config, "separator")
    backend = require_string(separator_cfg, "backend").lower()
    model_file = ensure_model_available(context, log_cb)
    log_cb(f"开始音轨分离，后端: {backend}，设备: {context.device}")

    backends = {
        "custom": run_custom_backend,
        "audio-separator": run_audio_separator_backend,
        "auto": None,
    }
    if backend not in backends:
        raise ProcessingError(f"不支持的分离后端: {backend}")

    errors: List[str] = []
    if backend == "auto":
        candidates = [run_custom_backend, run_audio_separator_backend]
    else:
        candidates = [backends[backend]]

    for runner in candidates:
        if runner is None:
            continue
        try:
            result = runner(context, audio_path, task_dir, model_file, log_cb)
        except SeparationError as exc:
            errors.append(str(exc))
            continue

        if result:
            vocals, instrumental = result
            log_cb(f"分离完成: {vocals.name} / {instrumental.name}")
            return vocals, instrumental

    if errors:
        raise ProcessingError("音轨分离失败: " + "；".join(errors))

    raise ProcessingError(
        "未找到可用的分离后端。请安装兼容的音轨分离包，或在 config.yaml 中填写自定义 Python 接口。"
    )
