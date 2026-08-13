from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Generator

import gradio as gr

from .context import AppContext
from .pipeline import (
    OUTPUT_MODE_LABELS,
    acquire_task_lock,
    make_log_recorder,
    refresh_video_choices,
    release_task_lock,
    run_download,
    run_separation_pipeline,
)
from .services.files import list_output_records, list_video_records


class WebApp:
    STAGE_LABELS = [
        "准备任务",
        "校验视频",
        "提取音轨",
        "准备模型",
        "音轨分离",
        "导出成品",
    ]

    def __init__(self, context: AppContext) -> None:
        self.context = context

    def _build_progress_text(self, stage_index: int, started_at: float, heartbeat: str = "") -> str:
        total = len(self.STAGE_LABELS)
        safe_index = max(1, min(stage_index, total))
        filled = "#" * safe_index
        empty = "-" * (total - safe_index)
        elapsed_seconds = int(time.monotonic() - started_at)
        minutes, seconds = divmod(elapsed_seconds, 60)
        lines = [
            f"[{filled}{empty}] {safe_index}/{total}",
            f"当前阶段：{self.STAGE_LABELS[safe_index - 1]}",
            f"已运行：{minutes:02d}:{seconds:02d}",
        ]
        if heartbeat:
            lines.append(heartbeat)
        return "\n".join(lines)

    def _infer_stage_index(self, logs: list[str]) -> int:
        joined = "\n".join(logs)
        if "成品已生成" in joined or "分离任务已完成" in joined:
            return 6
        if "开始音轨分离" in joined or "检测到 audio-separator 后端" in joined or "分离完成:" in joined:
            return 5
        if "分离模型已就绪" in joined or "本地未找到分离模型" in joined:
            return 4
        if "已提取分离音轨" in joined:
            return 3
        if "视频校验通过" in joined:
            return 2
        return 1

    def _dropdown_update(self) -> gr.update:
        choices = refresh_video_choices(self.context)
        value = choices[0] if choices else None
        return gr.update(choices=choices, value=value)

    def refresh_dropdown(self) -> gr.update:
        return self._dropdown_update()

    def video_library_dataframe(self) -> list[list]:
        return [
            [
                item["filename"],
                item["title"],
                item.get("uploader") or "",
                item.get("duration") or "",
                item.get("created_at") or "",
            ]
            for item in list_video_records(self.context.config)
        ]

    def output_library_dataframe(self) -> list[list]:
        return [
            [
                item["task_id"],
                item.get("source_video") or "",
                item.get("output_mode") or "",
                item.get("status") or "",
                item.get("finished_at") or item.get("started_at") or "",
            ]
            for item in list_output_records(self.context.config)
        ]

    @staticmethod
    def _selected_record(event: gr.SelectData, records: list[dict]):
        if event.index is None:
            return None
        row_index = event.index[0] if isinstance(event.index, tuple) else event.index
        if row_index < 0 or row_index >= len(records):
            return None
        return records[row_index]

    @staticmethod
    def _format_video_details(item: dict) -> str:
        return "\n".join(
            [
                f"标题：{item['title']}",
                f"作者：{item.get('uploader') or '-'}",
                f"时长：{item.get('duration') or '-'}",
                f"时间：{item.get('created_at') or '-'}",
                f"来源：{item.get('source_url') or '-'}",
            ]
        )

    @staticmethod
    def _format_output_details(item: dict) -> str:
        return "\n".join(
            [
                f"任务：{item['task_id']}",
                f"源视频：{item.get('source_video') or '-'}",
                f"模式：{item.get('output_mode') or '-'}",
                f"状态：{item.get('status') or '-'}",
                f"完成时间：{item.get('finished_at') or item.get('started_at') or '-'}",
                f"错误：{item.get('error') or '-'}",
            ]
        )

    def show_video_record(self, event: gr.SelectData):
        item = self._selected_record(event, list_video_records(self.context.config))
        if item is None:
            return None, "", None
        return item.get("thumbnail_path"), self._format_video_details(item), item["video_path"]

    def show_output_record(self, event: gr.SelectData):
        item = self._selected_record(event, list_output_records(self.context.config))
        if item is None:
            return "", None, None, None

        details = self._format_output_details(item)
        final_output = item.get("final_output_path")
        if final_output and Path(final_output).suffix.lower() == ".mp4":
            return details, item.get("preview_path"), final_output, final_output
        if final_output:
            return details, item.get("preview_path"), None, final_output
        return details, item.get("preview_path"), None, None

    def handle_download(self, url: str) -> Generator:
        logs: list[str] = []
        acquired = False
        try:
            acquire_task_lock(self.context)
            acquired = True
            log_cb = make_log_recorder(self.context, logs)
            log_cb("准备开始下载任务")
            yield "\n".join(logs), self._dropdown_update(), self.video_library_dataframe()

            selected, choices = run_download(self.context, url, log_cb)
            log_cb("下载任务已完成")
            yield (
                "\n".join(logs),
                gr.update(choices=choices, value=selected),
                self.video_library_dataframe(),
            )
        except Exception as exc:
            logs.append(f"任务失败: {exc}")
            yield "\n".join(logs), self._dropdown_update(), self.video_library_dataframe()
        finally:
            if acquired:
                release_task_lock(self.context)

    def handle_separation(self, selected_video: str, output_mode: str) -> Generator:
        logs: list[str] = []
        acquired = False
        started_at = time.monotonic()
        last_log_count = 0
        last_heartbeat_at = started_at
        heartbeat_text = ""
        state = {"done": False, "output_file": None, "error": None}

        try:
            acquire_task_lock(self.context)
            acquired = True
            log_cb = make_log_recorder(self.context, logs)
            log_cb("准备开始分离任务")
            yield self._build_progress_text(1, started_at), "\n".join(logs), None, self.output_library_dataframe()

            def worker() -> None:
                try:
                    _, _, output_file = run_separation_pipeline(
                        self.context,
                        selected_video,
                        output_mode,
                        log_cb,
                        logs,
                    )
                    state["output_file"] = output_file
                    log_cb("分离任务已完成")
                except Exception as exc:
                    state["error"] = str(exc).strip() or repr(exc)
                    log_cb(f"任务失败: {state['error']}")
                finally:
                    state["done"] = True

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()

            while not state["done"]:
                if len(logs) != last_log_count:
                    last_log_count = len(logs)
                    last_heartbeat_at = time.monotonic()
                    heartbeat_text = ""
                elif time.monotonic() - last_heartbeat_at >= 8:
                    heartbeat_text = "保活检测：任务仍在运行，正在等待当前阶段完成"

                stage_index = self._infer_stage_index(logs)
                yield (
                    self._build_progress_text(stage_index, started_at, heartbeat_text),
                    "\n".join(logs),
                    None,
                    self.output_library_dataframe(),
                )
                time.sleep(1)

            final_stage = 6 if not state["error"] else self._infer_stage_index(logs)
            if state["error"] and not any(line.endswith(state["error"]) for line in logs):
                log_cb(f"任务失败: {state['error']}")
            yield (
                self._build_progress_text(final_stage, started_at),
                "\n".join(logs),
                state["output_file"],
                self.output_library_dataframe(),
            )
        except Exception as exc:
            logs.append(f"任务失败: {exc}")
            stage_index = self._infer_stage_index(logs)
            yield (
                self._build_progress_text(stage_index, started_at),
                "\n".join(logs),
                None,
                self.output_library_dataframe(),
            )
        finally:
            if acquired:
                release_task_lock(self.context)

    def build(self) -> gr.Blocks:
        initial_choices = refresh_video_choices(self.context)
        initial_value = initial_choices[0] if initial_choices else None

        with gr.Blocks(title="SunVideoTool") as demo:
            gr.Markdown("# SunVideoTool\n纯本地 Mac M1 短视频下载与 AI 音轨分离")

            with gr.Tabs():
                with gr.Tab("任务"):
                    with gr.Row():
                        download_url = gr.Textbox(label="视频链接", placeholder="粘贴 B 站或抖音链接")
                        download_button = gr.Button("下载视频", variant="primary")

                    with gr.Row():
                        video_dropdown = gr.Dropdown(
                            choices=initial_choices,
                            value=initial_value,
                            label="本地视频",
                            allow_custom_value=False,
                        )
                        refresh_button = gr.Button("刷新列表")

                    output_mode = gr.Dropdown(
                        choices=list(OUTPUT_MODE_LABELS),
                        value="纯人声MP3",
                        label="输出模式",
                        allow_custom_value=False,
                    )
                    separate_button = gr.Button("开始分离", variant="primary")
                    progress_box = gr.Textbox(label="任务进度", value="等待开始", interactive=False)
                    log_box = gr.Textbox(label="实时日志", lines=18, interactive=False)
                    output_file = gr.File(label="成品下载", interactive=False)

                with gr.Tab("下载库"):
                    video_library = gr.Dataframe(
                        headers=["文件名", "标题", "作者", "时长", "下载时间"],
                        value=self.video_library_dataframe(),
                        interactive=False,
                    )
                    with gr.Row():
                        source_cover = gr.Image(label="封面预览", interactive=False)
                        source_video = gr.Video(label="视频预览")
                    source_details = gr.Textbox(label="视频信息", lines=6, interactive=False)
                    refresh_video_library = gr.Button("刷新下载库")

                with gr.Tab("输出库"):
                    output_library = gr.Dataframe(
                        headers=["任务目录", "源视频", "输出模式", "状态", "完成时间"],
                        value=self.output_library_dataframe(),
                        interactive=False,
                    )
                    with gr.Row():
                        output_cover = gr.Image(label="封面预览", interactive=False)
                        output_video = gr.Video(label="视频预览")
                    output_audio = gr.Audio(label="音频预览", interactive=False)
                    output_details = gr.Textbox(label="任务信息", lines=6, interactive=False)
                    refresh_output_library = gr.Button("刷新输出库")

            download_button.click(
                self.handle_download,
                inputs=[download_url],
                outputs=[log_box, video_dropdown, video_library],
                show_progress=True,
            )
            refresh_button.click(self.refresh_dropdown, outputs=[video_dropdown], show_progress=False)
            separate_button.click(
                self.handle_separation,
                inputs=[video_dropdown, output_mode],
                outputs=[progress_box, log_box, output_file, output_library],
                show_progress=True,
            )
            refresh_video_library.click(
                self.video_library_dataframe,
                outputs=[video_library],
                show_progress=False,
            )
            refresh_output_library.click(
                self.output_library_dataframe,
                outputs=[output_library],
                show_progress=False,
            )
            video_library.select(self.show_video_record, outputs=[source_cover, source_details, source_video])
            output_library.select(self.show_output_record, outputs=[output_details, output_cover, output_video, output_audio])

        return demo
