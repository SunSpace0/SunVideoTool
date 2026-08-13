from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple

from .context import AppContext
from .exceptions import ProcessingError
from .services.download import download_video
from .services.files import (
    get_task_log_path,
    get_task_manifest_path,
    get_video_path,
    get_video_sidecar_path,
    list_local_videos,
    make_task_output_dir,
    read_json_file,
    sanitize_name,
    write_json_file,
)
from .services.media import (
    convert_to_mp3,
    extract_audio_for_separation,
    generate_video_thumbnail,
    mux_video_with_audio,
    verify_video_file,
)
from .services.separation import separate_audio


@dataclass(frozen=True)
class OutputMode:
    value: str
    label: str
    kind: str
    suffix: str
    stem: str


OUTPUT_MODES = {
    "vocal_mp3": OutputMode("vocal_mp3", "纯人声MP3", "audio", "mp3", "vocals"),
    "instrumental_mp3": OutputMode("instrumental_mp3", "纯伴奏MP3", "audio", "mp3", "instrumental"),
    "vocal_video": OutputMode("vocal_video", "带人声原视频MP4", "video", "mp4", "vocals"),
    "instrumental_video": OutputMode("instrumental_video", "带伴奏原视频MP4", "video", "mp4", "instrumental"),
}
OUTPUT_MODE_LABELS = tuple(mode.label for mode in OUTPUT_MODES.values())


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve_output_mode(value: str) -> OutputMode:
    if value in OUTPUT_MODES:
        return OUTPUT_MODES[value]

    for mode in OUTPUT_MODES.values():
        if mode.label == value:
            return mode

    raise ProcessingError("请选择有效的输出模式")


def make_log_recorder(context: AppContext, logs: list[str]) -> Callable[[str], str]:
    def recorder(message: str) -> str:
        line = message.strip()
        context.logger.info(line)
        logs.append(line)
        return "\n".join(logs)

    return recorder


def acquire_task_lock(context: AppContext) -> None:
    if not context.busy_lock.acquire(blocking=False):
        raise ProcessingError("当前已有任务在运行，请等待当前任务完成后再继续")


def release_task_lock(context: AppContext) -> None:
    if context.busy_lock.locked():
        context.busy_lock.release()


def refresh_video_choices(context: AppContext) -> list[str]:
    return list_local_videos(context.config)


def run_download(context: AppContext, url: str, log_cb: Callable[[str], str]) -> Tuple[str, list[str]]:
    download_video(context, url, log_cb)
    choices = refresh_video_choices(context)
    return choices[-1] if choices else "", choices


def build_output(
    context: AppContext,
    mode: OutputMode,
    original_video: Path,
    task_dir: Path,
    vocals: Path,
    instrumental: Path,
    log_cb: Callable[[str], str],
) -> Tuple[Optional[str], Optional[str], str]:
    source_audio = vocals if mode.stem == "vocals" else instrumental
    base_name = sanitize_name(original_video.stem)
    final_path = task_dir / f"{base_name}_{mode.stem}.{mode.suffix}"

    if mode.kind == "audio":
        convert_to_mp3(context, source_audio, final_path, log_cb)
        return str(final_path), None, str(final_path)

    mux_video_with_audio(context, original_video, source_audio, final_path, log_cb)
    return None, str(final_path), str(final_path)


def write_failed_manifest(task_dir: Path, video_path: Path, output_mode: str, started_at: str, error: str) -> None:
    write_json_file(
        get_task_manifest_path(task_dir),
        {
            "task_id": task_dir.name,
            "task_dir": str(task_dir),
            "source_video": video_path.name,
            "source_video_path": str(video_path),
            "output_mode": output_mode,
            "status": "failed",
            "started_at": started_at,
            "finished_at": now_iso(),
            "error": error,
        },
    )


def run_separation_pipeline(
    context: AppContext,
    selected_video: str,
    output_mode: str,
    log_cb: Callable[[str], str],
    logs: list[str] | None = None,
) -> Tuple[Optional[str], Optional[str], str]:
    mode = resolve_output_mode(output_mode)
    video_path = get_video_path(context.config, selected_video)
    source_meta = read_json_file(get_video_sidecar_path(video_path))
    verify_video_file(context, video_path, log_cb)
    task_dir = make_task_output_dir(context.config, video_path)
    started_at = now_iso()
    log_cb(f"输出目录: {task_dir}")

    try:
        separation_input = extract_audio_for_separation(context, video_path, task_dir, log_cb)
        vocals, instrumental = separate_audio(context, separation_input, task_dir, log_cb)
        audio_preview, video_preview, final_output = build_output(
            context,
            mode,
            video_path,
            task_dir,
            vocals,
            instrumental,
            log_cb,
        )
    except Exception as exc:
        details = str(exc).strip() or repr(exc)
        write_failed_manifest(task_dir, video_path, mode.label, started_at, details)
        raise

    final_path = Path(final_output)
    preview_path = source_meta.get("thumbnail_path")
    if video_preview:
        preview_candidate = task_dir / "preview.jpg"
        try:
            generate_video_thumbnail(context, final_path, preview_candidate, log_cb)
            preview_path = str(preview_candidate)
        except ProcessingError:
            pass

    write_json_file(
        get_task_manifest_path(task_dir),
        {
            "task_id": task_dir.name,
            "task_dir": str(task_dir),
            "source_video": video_path.name,
            "source_video_path": str(video_path),
            "output_mode": mode.label,
            "status": "completed",
            "started_at": started_at,
            "finished_at": now_iso(),
            "final_output_path": str(final_path),
            "preview_path": preview_path,
            "vocals_path": str(vocals),
            "instrumental_path": str(instrumental),
            "error": None,
        },
    )
    if logs is not None:
        get_task_log_path(task_dir).write_text("\n".join(logs), encoding="utf-8")

    return audio_preview, video_preview, str(final_path)
