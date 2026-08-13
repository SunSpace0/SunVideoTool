from __future__ import annotations

import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .context import AppContext, build_context
from .exceptions import ConfigError, ProcessingError
from .pipeline import run_download, run_separation_pipeline
from .services.files import (
    VIDEO_EXTENSIONS,
    clear_video_records,
    delete_video_record,
    get_video_path,
    get_video_sidecar_path,
    list_output_records,
    list_video_records,
    read_json_file,
    sanitize_name,
    write_json_file,
)
from .services.media import generate_video_thumbnail
from .settings import apply_settings


class DownloadRequest(BaseModel):
    url: str


class SeparateRequest(BaseModel):
    video: str
    output_mode: str


class ImportPathRequest(BaseModel):
    path: str


class PipelineRequest(BaseModel):
    url: str
    output_mode: str


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class JobState:
    def __init__(self, job_id: str, job_type: str) -> None:
        self.id = job_id
        self.job_type = job_type
        self.status = "running"
        self.logs: list[str] = []
        self.created_at = now_iso()
        self.started_at = self.created_at
        self.finished_at: Optional[str] = None
        self.last_log_at: Optional[str] = None
        self.last_heartbeat_at = self.created_at
        self.output_file: Optional[str] = None
        self.task_id: Optional[str] = None
        self.error: Optional[str] = None
        self.progress: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "job_type": self.job_type,
            "status": self.status,
            "logs": list(self.logs),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_log_at": self.last_log_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "output_file": self.output_file,
            "task_id": self.task_id,
            "error": self.error,
            "progress": self.progress,
        }


context: AppContext = build_context()
_jobs_lock = threading.Lock()
_jobs: Dict[str, JobState] = {}


def _get_job(job_id: str) -> JobState:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


def _update_job(job_id: str, **fields: Any) -> JobState:
    with _jobs_lock:
        job = _jobs[job_id]
        for key, value in fields.items():
            setattr(job, key, value)
        return job


def _append_log(job_id: str, message: str) -> str:
    line = message.strip()
    context.logger.info(line)
    with _jobs_lock:
        job = _jobs[job_id]
        job.logs.append(line)
        job.last_log_at = now_iso()
        return "\n".join(job.logs)


def _make_job_recorder(job_id: str):
    def recorder(message: str) -> str:
        return _append_log(job_id, message)

    return recorder


def _heartbeat_loop(job_id: str) -> None:
    while True:
        with _jobs_lock:
            job = _jobs.get(job_id)
        if job is None or job.status != "running":
            break
        _update_job(job_id, last_heartbeat_at=now_iso())
        time.sleep(2)


def _start_job(job_type: str, target) -> JobState:
    job_id = uuid.uuid4().hex[:12]
    job = JobState(job_id, job_type)
    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(target=target, args=(job_id,), daemon=True)
    heartbeat = threading.Thread(target=_heartbeat_loop, args=(job_id,), daemon=True)
    thread.start()
    heartbeat.start()
    return job


def _finish_job(job_id: str, status: str, error: Optional[str] = None) -> None:
    _update_job(job_id, status=status, error=error, finished_at=now_iso(), last_heartbeat_at=now_iso())


def _run_download_job(job_id: str, url: str) -> None:
    log_cb = _make_job_recorder(job_id)

    def progress_cb(percent: float) -> None:
        _update_job(job_id, progress=percent)

    try:
        log_cb("准备开始下载任务")
        run_download(context, url, log_cb, progress_cb)
        log_cb("下载任务已完成")
        _update_job(job_id, progress=100.0)
        _finish_job(job_id, "completed")
    except Exception as exc:
        error = str(exc).strip() or repr(exc)
        log_cb(f"任务失败: {error}")
        _finish_job(job_id, "failed", error)


def _run_separation_job(job_id: str, video: str, output_mode: str) -> None:
    log_cb = _make_job_recorder(job_id)
    try:
        log_cb("准备开始分离任务")
        _update_job(job_id, progress=8.0)
        _, _, output_file = run_separation_pipeline(context, video, output_mode, log_cb, _get_job(job_id).logs)
        _update_job(job_id, output_file=output_file, task_id=Path(output_file).parent.name)
        log_cb("分离任务已完成")
        _update_job(job_id, progress=100.0)
        _finish_job(job_id, "completed")
    except Exception as exc:
        error = str(exc).strip() or repr(exc)
        log_cb(f"任务失败: {error}")
        _finish_job(job_id, "failed", error)


def _run_pipeline_job(job_id: str, url: str, output_mode: str) -> None:
    log_cb = _make_job_recorder(job_id)

    def progress_cb(percent: float) -> None:
        _update_job(job_id, progress=min(percent, 42.0))

    try:
        log_cb("开始下载并分离任务")
        _update_job(job_id, progress=2.0)
        downloaded_name, _ = run_download(context, url, log_cb, progress_cb)
        log_cb("下载完成，准备开始音轨分离")
        _update_job(job_id, progress=46.0)
        _, _, output_file = run_separation_pipeline(context, downloaded_name, output_mode, log_cb, _get_job(job_id).logs)
        _update_job(job_id, output_file=output_file, task_id=Path(output_file).parent.name, progress=100.0)
        log_cb("下载并分离任务已完成")
        _finish_job(job_id, "completed")
    except Exception as exc:
        error = str(exc).strip() or repr(exc)
        log_cb(f"任务失败: {error}")
        _finish_job(job_id, "failed", error)


def _output_record(task_id: str) -> Dict[str, Any]:
    for record in list_output_records(context.config):
        if record["task_id"] == task_id:
            return record
    raise HTTPException(status_code=404, detail="输出任务不存在")


def _unique_video_target(source_dir: Path, filename: str) -> Path:
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem
    candidate = source_dir / filename
    counter = 1
    while candidate.exists():
        candidate = source_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _import_local_video(source_path: Path, suggested_name: str | None = None) -> Dict[str, Any]:
    if not source_path.is_file():
        raise ProcessingError(f"本地视频不存在: {source_path}")

    suffix = source_path.suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise ProcessingError(f"不支持的视频格式: {suffix or '未知'}，支持 {', '.join(sorted(VIDEO_EXTENSIONS))}")

    base_name = sanitize_name(Path(suggested_name or source_path.stem).stem)
    target_path = _unique_video_target(context.source_video_dir, f"{base_name}{suffix}")
    shutil.copy2(source_path, target_path)

    thumbnail_path = target_path.with_suffix(".jpg")
    try:
        generate_video_thumbnail(context, target_path, thumbnail_path, lambda _message: None)
    except ProcessingError:
        thumbnail_path = None

    payload = {
        "id": target_path.stem,
        "title": base_name,
        "source_url": "",
        "uploader": "本地导入",
        "duration": None,
        "created_at": now_iso(),
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        "video_path": str(target_path),
    }
    write_json_file(get_video_sidecar_path(target_path), payload)

    for record in list_video_records(context.config):
        if record["filename"] == target_path.name:
            return record
    return {
        "id": target_path.stem,
        "title": base_name,
        "filename": target_path.name,
        "video_path": str(target_path),
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        "source_url": "",
        "uploader": "本地导入",
        "duration": None,
        "created_at": payload["created_at"],
    }


app = FastAPI(title="SunVideoTool API", version="0.3.0")
runtime_cfg = context.config.get("runtime", {})
api_host = str(runtime_cfg.get("host", "127.0.0.1")).strip() or "127.0.0.1"
frontend_port = int(runtime_cfg.get("frontend_port", 18881))
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://{api_host}:{frontend_port}",
        f"http://localhost:{frontend_port}",
        f"http://127.0.0.1:{frontend_port}",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "device": context.device}


@app.get("/api/jobs")
def jobs() -> list[Dict[str, Any]]:
    with _jobs_lock:
        return [job.to_dict() for job in sorted(_jobs.values(), key=lambda item: item.created_at, reverse=True)]


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> Dict[str, Any]:
    return _get_job(job_id).to_dict()


@app.post("/api/download", status_code=202)
def start_download(payload: DownloadRequest) -> Dict[str, Any]:
    job = _start_job("download", lambda job_id: _run_download_job(job_id, payload.url))
    return job.to_dict()


@app.post("/api/separate", status_code=202)
def start_separate(payload: SeparateRequest) -> Dict[str, Any]:
    job = _start_job(
        "separate",
        lambda job_id: _run_separation_job(job_id, payload.video, payload.output_mode),
    )
    return job.to_dict()


@app.post("/api/pipeline", status_code=202)
def start_pipeline(payload: PipelineRequest) -> Dict[str, Any]:
    job = _start_job(
        "download-separate",
        lambda job_id: _run_pipeline_job(job_id, payload.url, payload.output_mode),
    )
    return job.to_dict()


@app.get("/api/videos")
def videos() -> list[Dict[str, Any]]:
    return list_video_records(context.config)


@app.delete("/api/videos")
def clear_videos() -> Dict[str, Any]:
    count = clear_video_records(context.config)
    return {"deleted": count}


@app.post("/api/videos/import", status_code=201)
async def import_video_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    original_name = Path(file.filename or "video.mp4").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的视频格式: {suffix or '未知'}")

    tmp_path = context.tmp_dir / f"upload_{uuid.uuid4().hex}{suffix}"
    context.tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tmp_path.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        record = _import_local_video(tmp_path, Path(original_name).stem)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return record


@app.post("/api/videos/import-path", status_code=201)
def import_video_path(payload: ImportPathRequest) -> Dict[str, Any]:
    source_path = Path(payload.path.strip()).expanduser()
    try:
        record = _import_local_video(source_path)
    except ProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return record


@app.delete("/api/videos/{filename}")
def delete_video(filename: str) -> Dict[str, Any]:
    try:
        message = delete_video_record(context.config, filename)
    except ProcessingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"message": message}


@app.get("/api/outputs")
def outputs() -> list[Dict[str, Any]]:
    return list_output_records(context.config)


@app.get("/api/config")
def get_config() -> Dict[str, Any]:
    return context.config


@app.put("/api/config")
def update_config(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        message = apply_settings(context, payload)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": message, "config": context.config}


@app.get("/api/files/video/{filename}")
def video_file(filename: str) -> FileResponse:
    try:
        path = get_video_path(context.config, filename)
    except ProcessingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)


@app.get("/api/files/thumbnail/{filename}")
def thumbnail_file(filename: str) -> FileResponse:
    try:
        video_path = get_video_path(context.config, filename)
    except ProcessingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    thumbnail = read_json_file(get_video_sidecar_path(video_path)).get("thumbnail_path")
    if not thumbnail or not Path(thumbnail).is_file():
        raise HTTPException(status_code=404, detail="封面不存在")
    return FileResponse(Path(thumbnail))


@app.get("/api/files/output/{task_id}")
def output_file(task_id: str) -> FileResponse:
    record = _output_record(task_id)
    final_output = record.get("final_output_path")
    if not final_output or not Path(final_output).is_file():
        raise HTTPException(status_code=404, detail="成品文件不存在")
    return FileResponse(Path(final_output))


@app.get("/api/files/output-thumbnail/{task_id}")
def output_thumbnail(task_id: str) -> FileResponse:
    record = _output_record(task_id)
    preview = record.get("preview_path")
    if not preview or not Path(preview).is_file():
        raise HTTPException(status_code=404, detail="预览图不存在")
    return FileResponse(Path(preview))


frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
