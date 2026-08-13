# SunVideoTool

纯本地 Mac 短视频下载与 AI 音轨分离工具。使用 Gradio 提供本地 Web 界面，下载任务与音轨分离任务串行执行。

## 功能

- 下载 B 站、抖音等 yt-dlp 支持的短视频
- 下载库与输出库展示，可预览封面、视频和音频
- 使用 MDX-Net 模型分离人声和伴奏
- 输出纯人声 MP3、纯伴奏 MP3、带人声 MP4、带伴奏 MP4
- 默认优先使用 Apple MPS，不可用时回退 CPU

## 环境要求

- macOS（当前以 M1/MPS 为默认目标）
- Python 3.10+
- ffmpeg / ffprobe

## 安装

```bash
conda create -n SunVideoTool python=3.11 -y
conda activate SunVideoTool
brew install ffmpeg
pip install -e .
# 完整功能（含 audio-separator）
pip install -e ".[separation]"
```

如果 conda 源不可用，也可以直接用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[separation]"
```

`audio-separator` 是默认可选分离后端，如果使用本地 UVR5 自定义接口，也可以跳过：

```bash
pip install -e ".[separation]"
```

## 配置

首次运行前复制配置模板：

```bash
cp config.example.yaml config.yaml
```

`config.yaml` 已被 `.gitignore` 忽略，不会把本机 Cookie 或模型路径提交到 GitHub。

主要配置项：

- `paths.*`：下载目录、输出目录、模型目录、ffmpeg 路径
- `yt_dlp.*`：下载参数和 B 站认证方式
- `separator.*`：分离后端、模型路径、人声/伴奏命名提示
- `runtime.*`：设备偏好、日志级别、Web 地址与端口
- `llm.*`：大模型服务预留配置，可在 Web 设置页中填写

把 MDX-Net 模型文件放到 `data/models/`，并确保 `separator.model_file` 指向正确文件名。

## 启动

```bash
python main.py
# 或
python -m sunvideotool
# 安装后也可以
sunvideotool
```

可选参数：

```bash
python main.py --config /path/to/config.yaml --port 7860 --no-browser
```

默认打开 `http://127.0.0.1:7860`。

## Web 设置页

顶部导航栏新增“设置”Tab，可保存到本地 `config.yaml`：

- 服务端口：不能使用 `5173` 或 `8000`，修改后需重启
- 分离后端与模型路径
- B 站 Cookie 认证
- 大模型服务商、API Base、API Key、模型名称（预留）

## 认证与下载

`yt_dlp` 支持三种本地认证方式，优先级与配置顺序一致：

- `cookiesfrombrowser`：读取本机浏览器 Cookie，例如 `chrome`
- `cookiefile`：填写本地 `cookies.txt` 路径
- `cookie_header`：粘贴浏览器复制出的 Cookie 字符串

B 站下载出现 `HTTP Error 412` 时，优先确认指定浏览器已登录 B 站；仍失败时，把 Cookie 手工贴到 `cookie_header`。

## 项目结构

```text
SunVideoTool/
├── main.py                  # 入口
├── config.example.yaml      # 配置模板
├── pyproject.toml           # 依赖与安装信息
├── sunvideotool/
│   ├── cli.py               # 命令行入口
│   ├── config.py            # 配置加载与校验
│   ├── context.py           # 运行时上下文与设备检测
│   ├── pipeline.py          # 下载/分离任务编排
│   ├── web.py               # Gradio 界面
│   └── services/
│       ├── download.py      # yt-dlp 下载
│       ├── files.py         # 文件与任务记录
│       ├── media.py         # ffmpeg 音视频处理
│       └── separation.py    # 音轨分离后端
└── data/                    # 运行数据，Git 中仅保留目录结构
```

## 当前限制

- 同一时间只允许一个任务运行
- 分离模型文件不会自动随代码分发，需要下载或放入本地模型目录

下载库支持“删除选中视频”和“清空下载历史”，会同步删除视频、元数据与封面文件。
