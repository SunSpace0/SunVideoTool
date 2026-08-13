from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .context import build_context
from .web import WebApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SunVideoTool 本地短视频下载与音轨分离工具")
    parser.add_argument("--config", type=Path, default=None, help="自定义 config.yaml 路径")
    parser.add_argument("--host", default=None, help="覆盖监听地址")
    parser.add_argument("--port", type=int, default=None, help="覆盖监听端口")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    context = build_context(args.config)
    runtime = context.config["runtime"]
    host = args.host or runtime.get("host", "127.0.0.1")
    port = args.port or int(runtime.get("port", 7860))
    if port in {5173, 8000}:
        raise SystemExit("5173 和 8000 端口已被其他项目占用，请更换端口")
    if not 1024 <= port <= 65535:
        raise SystemExit("服务端口应在 1024-65535 之间")

    context.logger.info("启动 SunVideoTool，当前设备: %s", context.device)
    if context.device == "cpu":
        context.logger.info("未检测到可用的 Metal/MPS，将自动回退到 CPU")

    app = WebApp(context).build()
    app.queue(default_concurrency_limit=1, max_size=1)
    app.launch(
        server_name=host,
        server_port=port,
        inbrowser=not args.no_browser,
        show_error=True,
    )


if __name__ == "__main__":
    main()
