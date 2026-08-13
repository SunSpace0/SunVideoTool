from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .context import AppContext, build_context
from .exceptions import ConfigError, ProcessingError
from .pipeline import (
    acquire_task_lock,
    make_log_recorder,
    release_task_lock,
    run_download,
    run_separation_pipeline,
)
from .services.files import (
    clear_video_records,
    delete_video_record,
    get_video_path,
    get_video_sidecar_path,
    list_output_records,
    list_video_records,
    read_json_file,
)
from .settings import apply_settings


class DownloadRequest(BaseModel):
    url: str


class SeparateRequest(BaseModel):
    video: str
    output_mode: str


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class JobState:
    def __init__(self, job_type: str = "idle") -> None:
        self.job_type = job_type
        self.status = "idle"
        self.logs: list[str] = []
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.output_file: Optional[str] = None
        self.task_id: Optional[str] = None
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_type": self.job_type,
            "status": self.status,
            "logs": list(self.logs),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output_file": self.output_file,
            "task_id": self.task_id,
            "error": self.error,
        }


context: AppContext = build_context()
_job_lock = threading.Lock()
_current_job = {"state": JobState(), "thread": None}


def _start_job(job_type: str, target) -> JobState:
    with _job_lock:
        if _current_job["state"].status == "running":
            raise HTTPException(status_code=409, detail="当前已有任务在运行，请等待任务完成")
        state = JobState(job_type)
        state.status = "running"
        state.started_at = now_iso()
        _current_job["state"] = state

    thread = threading.Thread(target=target, args=(state,), daemon=True)
    _current_job["thread"] = thread
    thread.start()
    return state


def _run_download_job(state: JobState, url: str) -> None:
    acquire_task_lock(context)
    try:
        log_cb = make_log_recorder(context, state.logs)
        log_cb("准备开始下载任务")
        run_download(context, url, log_cb)
        log_cb("下载任务已完成")
        state.status = "completed"
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc).strip() or repr(exc)
        state.logs.append(f"任务失败: {state.error}")
    finally:
        state.finished_at = now_iso()
        release_task_lock(context)


def _run_separation_job(state: JobState, video: str, output_mode: str) -> None:
    acquire_task_lock(context)
    try:
        log_cb = make_log_recorder(context, state.logs)
        log_cb("准备开始分离任务")
        _, _, output_file = run_separation_pipeline(context, video, output_mode, log_cb, state.logs)
        state.output_file = output_file
        state.task_id = Path(output_file).parent.name
        state.status = "completed"
        log_cb("分离任务已完成")
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc).strip() or repr(exc)
        state.logs.append(f"任务失败: {state.error}")
    finally:
        state.finished_at = now_iso()
        release_task_lock(context)


def _output_record(task_id: str) -> Dict[str, Any]:
    for record in list_output_records(context.config):
        if record["task_id"] == task_id:
            return record
    raise HTTPException(status_code=404, detail="输出任务不存在")


app = FastAPI(title="SunVideoTool API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5176", "http://localhost:5176"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "device": context.device}


@app.get("/api/jobs/current")
def current_job() -> Dict[str, Any]:
    with _job_lock:
        return _current_job["state"].to_dict()


@app.post("/api/download", status_code=202)
def start_download(payload: DownloadRequest) -> Dict[str, Any]:
    state = _start_job("download", lambda state: _run_download_job(state, payload.url))
    return state.to_dict()


@app.post("/api/separate", status_code=202)
def start_separate(payload: SeparateRequest) -> Dict[str, Any]:
    state = _start_job(
        "separate",
        lambda state: _run_separation_job(state, payload.video, payload.output_mode),
    )
    return state.to_dict()


@app.get("/api/videos")
def videos() -> list[Dict[str, Any]]:
    return list_video_records(context.config)


@app.delete("/api/videos")
def clear_videos() -> Dict[str, Any]:
    count = clear_video_records(context.config)
    return {"deleted": count}


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
