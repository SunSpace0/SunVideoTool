from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..config import normalize_path, require_mapping, require_string
from ..exceptions import ProcessingError


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
_task_dir_lock = threading.Lock()


def read_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def write_json_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def get_video_sidecar_path(video_path: Path) -> Path:
    return video_path.with_suffix(video_path.suffix + ".json")


def get_task_manifest_path(task_dir: Path) -> Path:
    return task_dir / "task.json"


def get_task_log_path(task_dir: Path) -> Path:
    return task_dir / "task.log"


def list_local_videos(config: Dict[str, Any]) -> List[str]:
    source_dir = normalize_path(require_mapping(config, "paths")["source_video_dir"])
    if not source_dir.exists():
        return []
    return sorted(
        path.name
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )


def list_video_records(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    source_dir = normalize_path(require_mapping(config, "paths")["source_video_dir"])
    records: List[Dict[str, Any]] = []
    if not source_dir.exists():
        return records
    for path in sorted(source_dir.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        sidecar = read_json_file(get_video_sidecar_path(path))
        stat = path.stat()
        records.append(
            {
                "id": sidecar.get("id") or path.stem,
                "title": sidecar.get("title") or path.stem,
                "video_path": str(path),
                "thumbnail_path": sidecar.get("thumbnail_path"),
                "source_url": sidecar.get("source_url"),
                "uploader": sidecar.get("uploader"),
                "duration": sidecar.get("duration"),
                "created_at": sidecar.get("created_at") or datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "size": stat.st_size,
                "filename": path.name,
            }
        )
    return records


def list_output_records(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    output_dir = normalize_path(require_mapping(config, "paths")["output_dir"])
    records: List[Dict[str, Any]] = []
    if not output_dir.exists():
        return records

    for task_dir in sorted([item for item in output_dir.iterdir() if item.is_dir()], key=lambda item: item.stat().st_mtime, reverse=True):
        manifest = read_json_file(get_task_manifest_path(task_dir))
        final_output = manifest.get("final_output_path")
        preview_path = manifest.get("preview_path")
        records.append(
            {
                "task_id": manifest.get("task_id") or task_dir.name,
                "task_dir": str(task_dir),
                "source_video": manifest.get("source_video") or task_dir.name,
                "output_mode": manifest.get("output_mode"),
                "status": manifest.get("status") or "unknown",
                "final_output_path": final_output,
                "preview_path": preview_path,
                "started_at": manifest.get("started_at"),
                "finished_at": manifest.get("finished_at"),
                "error": manifest.get("error"),
            }
        )
    return records


def get_video_path(config: Dict[str, Any], selected_name: str) -> Path:
    if not selected_name:
        raise ProcessingError("请先在下拉框中选择本地视频")

    source_dir = normalize_path(require_mapping(config, "paths")["source_video_dir"])
    video_path = source_dir / selected_name
    if not video_path.is_file():
        raise ProcessingError(f"未找到本地视频: {selected_name}")
    return video_path


def _remove_video_record(video_path: Path) -> None:
    sidecar = read_json_file(get_video_sidecar_path(video_path))
    thumbnail_path = sidecar.get("thumbnail_path")
    if thumbnail_path:
        Path(thumbnail_path).unlink(missing_ok=True)
    get_video_sidecar_path(video_path).unlink(missing_ok=True)
    video_path.unlink(missing_ok=True)


def delete_video_record(config: Dict[str, Any], selected_name: str) -> str:
    video_path = get_video_path(config, selected_name)
    _remove_video_record(video_path)
    return f"已删除: {selected_name}"


def clear_video_records(config: Dict[str, Any]) -> int:
    source_dir = normalize_path(require_mapping(config, "paths")["source_video_dir"])
    if not source_dir.exists():
        return 0

    video_paths = [
        path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    for video_path in video_paths:
        _remove_video_record(video_path)
    return len(video_paths)


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    return cleaned or "untitled"


def make_task_output_dir(config: Dict[str, Any], video_path: Path) -> Path:
    paths = require_mapping(config, "paths")
    separator_cfg = require_mapping(config, "separator")
    output_dir = normalize_path(paths["output_dir"])
    time_format = require_string(separator_cfg, "task_dir_time_format")
    with _task_dir_lock:
        base_name = f"{datetime.now().strftime(time_format)}_{sanitize_name(video_path.stem)}"
        task_dir = output_dir / base_name
        counter = 1
        while task_dir.exists():
            task_dir = output_dir / f"{base_name}_{counter}"
            counter += 1
        task_dir.mkdir(parents=True, exist_ok=False)
        return task_dir
