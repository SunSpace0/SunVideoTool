from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from .config import RESERVED_PORTS, save_config
from .context import AppContext
from .exceptions import ConfigError


def apply_settings(context: AppContext, payload: Dict[str, Any]) -> str:
    runtime = payload.get("runtime") or {}
    separator = payload.get("separator") or {}
    yt_dlp_cfg = payload.get("yt_dlp") or {}
    llm = payload.get("llm") or {}

    host = str(runtime.get("host", "")).strip()
    port = runtime.get("port")
    frontend_port = runtime.get("frontend_port")
    separator_backend = str(separator.get("backend", "")).strip()
    model_file = str(separator.get("model_file", "")).strip()

    try:
        port_number = int(port)
    except (TypeError, ValueError) as exc:
        raise ConfigError("runtime.port 必须是整数") from exc

    try:
        frontend_port_number = int(frontend_port)
    except (TypeError, ValueError) as exc:
        raise ConfigError("runtime.frontend_port 必须是整数") from exc

    if port_number in RESERVED_PORTS or frontend_port_number in RESERVED_PORTS:
        raise ConfigError("请勿使用 3000/5173/5174/5175/5176/7860/8000/8080 等常见开发端口，请更换端口")
    if not 1024 <= port_number <= 65535:
        raise ConfigError("runtime.port 应在 1024-65535 之间")
    if not 1024 <= frontend_port_number <= 65535:
        raise ConfigError("runtime.frontend_port 应在 1024-65535 之间")
    if not host:
        raise ConfigError("监听地址不能为空")
    if separator_backend not in {"auto", "audio-separator", "custom"}:
        raise ConfigError("分离后端无效")
    if not model_file:
        raise ConfigError("分离模型文件路径不能为空")

    updated = deepcopy(context.config)
    updated.setdefault("runtime", {})
    updated["runtime"]["host"] = host
    updated["runtime"]["port"] = port_number
    updated["runtime"]["frontend_port"] = frontend_port_number

    updated.setdefault("separator", {})
    updated["separator"]["backend"] = separator_backend
    updated["separator"]["model_file"] = model_file

    updated.setdefault("yt_dlp", {})
    updated["yt_dlp"]["cookiesfrombrowser"] = str(yt_dlp_cfg.get("cookiesfrombrowser", "")).strip()
    updated["yt_dlp"]["cookie_header"] = str(yt_dlp_cfg.get("cookie_header", "")).strip()

    updated.setdefault("llm", {})
    updated["llm"]["provider"] = str(llm.get("provider", "")).strip()
    updated["llm"]["api_base"] = str(llm.get("api_base", "")).strip()
    updated["llm"]["api_key"] = str(llm.get("api_key", "")).strip()
    updated["llm"]["model"] = str(llm.get("model", "")).strip()

    save_config(updated)
    context.config = updated
    return "配置已保存。端口等运行参数将在下次启动时生效。"
