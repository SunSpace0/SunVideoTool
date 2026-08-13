# SunVideoTool

纯本地 Mac 短视频下载与 AI 音轨分离工具。前端使用 React + Vite，后端使用 FastAPI，下载任务与音轨分离任务可并行异步执行。

## 功能

- 下载 B 站、抖音等 yt-dlp 支持的短视频
- 下载库与输出库展示，可预览封面、视频和音频
- 使用 MDX-Net 模型分离人声和伴奏
- 输出纯人声 MP3、纯伴奏 MP3、带人声 MP4、带伴奏 MP4
- 默认优先使用 Apple MPS，不可用时回退 CPU
- 支持批量并行下载，任务卡片展示实时进度、日志、心跳保活与错误信息
- 支持“下载后立即分离”组合任务，也支持对本地已下载视频单独分离

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

## 一键启动（开发模式，热更新）

```bash
./start.sh
```

脚本会：

- 使用 `.venv`（不存在时自动创建并安装依赖）
- 使用 npm 安装前端依赖
- 启动 FastAPI 后端：`http://127.0.0.1:18880`，并启用 `--reload`
- 启动 Vite 前端：`http://127.0.0.1:18881`，支持 HMR

如需手动运行：

```bash
.venv/bin/python -m uvicorn sunvideotool.api:app --reload --port 18880
npm --prefix frontend run dev -- --port 18881
```

## 生产运行

```bash
npm --prefix frontend run build
.venv/bin/python main.py
```

构建后 FastAPI 会自动托管 `frontend/dist/`，统一从 `http://127.0.0.1:18880` 访问。

## 配置页

顶部导航栏新增“设置”Tab，可保存到本地 `config.yaml`：

- 服务端口与前端开发端口：避免 `3000`、`5173-5176`、`7860`、`8000`、`8080` 等常见端口，修改后需重启
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
│   ├── api.py               # FastAPI 接口
│   ├── settings.py          # 设置保存
│   └── services/
│       ├── download.py      # yt-dlp 下载
│       ├── files.py         # 文件与任务记录
│       ├── media.py         # ffmpeg 音视频处理
│       └── separation.py    # 音轨分离后端
├── frontend/                # React + Vite 前端
└── data/                    # 运行数据，Git 中仅保留目录结构
```

## 当前限制

- 分离模型文件不会自动随代码分发，需要下载或放入本地模型目录
- 任务记录当前保存在内存中，服务重启后任务中心会清空；下载库和输出库仍从本地目录读取

下载库支持“删除选中视频”和“清空下载历史”，会同步删除视频、元数据与封面文件。

## 本地视频导入与浏览器说明

- 分离任务可以从“开始分离”中选择已有视频，也可以点击“选择视频文件”上传本地视频，或输入本机视频绝对路径后加载。
- 下载页会检测当前浏览器。QQ 浏览器无法被 yt-dlp 直接读取 Cookie，界面会给出提示，并要求确认已在设置中填写 Cookie 或改用 Chrome/Edge/Safari。
- 下载任务会展示 yt-dlp 的实时下载百分比；失败任务会在任务卡片中直接显示错误原因。
