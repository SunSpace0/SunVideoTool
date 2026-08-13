from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from ..config import require_mapping
from ..exceptions import ProcessingError
from ..context import AppContext


def run_command(command: list[str], log_cb: Callable[[str], None]) -> subprocess.CompletedProcess:
    log_cb("执行命令: " + " ".join(command))
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout).strip()
        raise ProcessingError(stderr or "外部命令执行失败")

    return result


def probe_media_duration(context: AppContext, media_path: Path) -> float | None:
    command = [
        context.ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        return None
    try:
        return float((result.stdout or "").strip())
    except ValueError:
        return None


def generate_video_thumbnail(
    context: AppContext,
    video_path: Path,
    thumbnail_path: Path,
    log_cb: Callable[[str], None],
) -> Path:
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        context.ffmpeg_bin,
        "-y",
        "-ss",
        "00:00:01",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(thumbnail_path),
    ]
    run_command(command, log_cb)
    return thumbnail_path


def verify_video_file(context: AppContext, video_path: Path, log_cb: Callable[[str], None]) -> None:
    duration = probe_media_duration(context, video_path)
    if duration is None:
        raise ProcessingError(f"视频校验失败: {video_path.name}")
    log_cb(f"视频校验通过: {video_path.name}")


def extract_audio_for_separation(
    context: AppContext,
    video_path: Path,
    task_dir: Path,
    log_cb: Callable[[str], None],
) -> Path:
    separator_cfg = require_mapping(context.config, "separator")
    sample_rate = int(separator_cfg.get("sample_rate", 44100))
    channels = int(separator_cfg.get("channels", 2))
    extension = str(separator_cfg.get("internal_audio_format", "wav")).strip().lower()
    audio_codec = "flac" if extension == "flac" else "pcm_s16le"
    audio_path = task_dir / f"separation_input.{extension}"
    command = [
        context.ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-c:a",
        audio_codec,
        str(audio_path),
    ]
    run_command(command, log_cb)
    log_cb(f"已提取分离音轨: {audio_path.name}")
    return audio_path


def convert_to_mp3(
    context: AppContext,
    source_audio: Path,
    destination: Path,
    log_cb: Callable[[str], None],
) -> Path:
    separator_cfg = require_mapping(context.config, "separator")
    bitrate = str(separator_cfg.get("mp3_bitrate", "320k"))
    command = [
        context.ffmpeg_bin,
        "-y",
        "-i",
        str(source_audio),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        str(destination),
    ]
    run_command(command, log_cb)
    return destination


def mux_video_with_audio(
    context: AppContext,
    original_video: Path,
    source_audio: Path,
    destination: Path,
    log_cb: Callable[[str], None],
) -> Path:
    command = [
        context.ffmpeg_bin,
        "-y",
        "-i",
        str(original_video),
        "-i",
        str(source_audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    run_command(command, log_cb)
    return destination
