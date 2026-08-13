from __future__ import annotations

import copy
import http.cookiejar
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Dict, Set, Tuple

from yt_dlp import YoutubeDL
from yt_dlp.networking.impersonate import ImpersonateTarget
from yt_dlp.utils import DownloadError

from ..config import normalize_path, require_mapping, require_string
from ..exceptions import ProcessingError
from ..context import AppContext
from .files import VIDEO_EXTENSIONS, get_video_sidecar_path, sanitize_name, write_json_file
from .media import generate_video_thumbnail


def current_files(directory: Path) -> Set[Path]:
    return {path.resolve() for path in directory.rglob("*") if path.is_file()}


def build_cookiefile_from_header(cookie_header: str, runtime_tmp_dir: Path) -> str:
    cookie_jar = http.cookiejar.MozillaCookieJar()
    runtime_tmp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = NamedTemporaryFile(
        prefix="sunvideotool-cookies-",
        suffix=".txt",
        delete=False,
        dir=runtime_tmp_dir,
    )
    temp_file.close()

    for pair in cookie_header.split(";"):
        item = pair.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        cookie = http.cookiejar.Cookie(
            version=0,
            name=name.strip(),
            value=value.strip(),
            port=None,
            port_specified=False,
            domain=".bilibili.com",
            domain_specified=True,
            domain_initial_dot=True,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        cookie_jar.set_cookie(cookie)

    cookie_jar.filename = temp_file.name
    cookie_jar.save(ignore_discard=True, ignore_expires=True)
    return temp_file.name


def build_ytdlp_options(context: AppContext) -> Tuple[Dict[str, Any], Path | None]:
    paths = require_mapping(context.config, "paths")
    yt_dlp_cfg = copy.deepcopy(require_mapping(context.config, "yt_dlp"))
    source_dir = normalize_path(paths["source_video_dir"])
    filename_template = require_string(yt_dlp_cfg, "filename_template")
    yt_dlp_cfg["outtmpl"] = str(source_dir / filename_template)

    cookiefile = str(yt_dlp_cfg.get("cookiefile", "")).strip()
    cookiesfrombrowser = str(yt_dlp_cfg.get("cookiesfrombrowser", "")).strip()
    cookie_header = str(yt_dlp_cfg.get("cookie_header", "")).strip()
    impersonate = str(yt_dlp_cfg.get("impersonate", "")).strip()
    temp_cookie_path: Path | None = None

    if cookie_header:
        temp_cookie_path = Path(build_cookiefile_from_header(cookie_header, context.tmp_dir))
        yt_dlp_cfg["cookiefile"] = str(temp_cookie_path)
    elif not cookiefile:
        yt_dlp_cfg.pop("cookiefile", None)

    if cookiesfrombrowser:
        yt_dlp_cfg["cookiesfrombrowser"] = (cookiesfrombrowser, None, None, None)
    else:
        yt_dlp_cfg.pop("cookiesfrombrowser", None)

    if impersonate:
        yt_dlp_cfg["impersonate"] = ImpersonateTarget.from_str(impersonate)
    else:
        yt_dlp_cfg.pop("impersonate", None)

    return yt_dlp_cfg, temp_cookie_path


def download_video(context: AppContext, url: str, log_cb: Callable[[str], None]) -> Path:
    if not url.strip():
        raise ProcessingError("请输入视频链接")

    source_dir = context.source_video_dir
    before_files = current_files(source_dir)
    options, temp_cookie_path = build_ytdlp_options(context)
    log_cb("开始解析并下载视频")

    info: Dict[str, Any] | None = None
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url.strip(), download=True)
    except DownloadError as exc:
        raise ProcessingError(f"下载失败: {exc}") from exc
    except Exception as exc:
        details = str(exc).strip() or repr(exc)
        raise ProcessingError(f"下载异常: {details}") from exc
    finally:
        if temp_cookie_path and temp_cookie_path.exists():
            temp_cookie_path.unlink(missing_ok=True)

    after_files = current_files(source_dir)
    new_files = sorted(after_files - before_files, key=lambda item: item.stat().st_mtime)
    video_candidates = [path for path in new_files if path.suffix.lower() in VIDEO_EXTENSIONS]
    if not video_candidates:
        raise ProcessingError("下载完成，但未在 source_video 中发现新的视频文件")

    downloaded = video_candidates[-1]
    thumbnail_path = downloaded.with_suffix(".jpg")
    try:
        generate_video_thumbnail(context, downloaded, thumbnail_path, log_cb)
    except ProcessingError:
        thumbnail_path = None

    payload = {
        "id": (info or {}).get("id") or downloaded.stem,
        "title": (info or {}).get("title") or sanitize_name(downloaded.stem),
        "source_url": url.strip(),
        "webpage_url": (info or {}).get("webpage_url") or url.strip(),
        "uploader": (info or {}).get("uploader"),
        "duration": (info or {}).get("duration"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        "video_path": str(downloaded),
    }
    write_json_file(get_video_sidecar_path(downloaded), payload)

    log_cb(f"下载完成: {downloaded.name}")
    return downloaded
