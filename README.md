# Docling Serve WebUI

> 批量图片 / 文档 OCR 识别 + AI 表格整理 —— 对小白友好的可视化工具

把一堆图片（身份证、发票、合同、截图等）或 PDF / Office 文档**批量拖进去**，系统自动：

1. **OCR 识别 + 版面解析** → 用 [Docling Serve](https://github.com/docling-project/docling-serve) 把图片 / PDF 里的文字、表格、版式提取出来
2. **AI 整理成表格**（可选）→ 用 OpenAI 兼容 LLM 按文件提取结构化信息，一张表「每行 = 一个文件」
3. **导出** → CSV / 带缩略图 HTML / ZIP

不需要写代码，浏览器操作即可。

---

## 系统架构

```
┌──────────────────────────────────────────────────────────┐
│  浏览器  http://<host>:8001                               │
│                                                            │
│   Docling Serve WebUI  (单进程 FastAPI, :8001)            │
│   ├─ REST API   (/api/v1/...)                             │
│   └─ 静态前端   (/ , /tasks , /task , /settings)          │
│              │                             │                │
│              ▼                             ▼                │
│   Docling Serve (:5001)          OpenAI 兼容 LLM (可选)    │
│   【独立 OCR 服务，必需】         【AI 表格整理，可选】     │
└──────────────────────────────────────────────────────────┘
```

- **WebUI 本身不含 OCR 模型**，它只是一个「调度 + 界面」，所有识别都由 Docling Serve 完成。
- Docling Serve 可以跑在**同一台机器**（推荐本地体验），也可以跑在另一台机器 / 容器里（生产部署）。
- LLM 不填也能用：上传时取消「启用 LLM 表格整理」即可只做 OCR。
- 前端是原生网页（HTML / CSS / JS），由后端同源托管，无需独立前端构建步骤。

---

## 环境要求

| 组件 | 要求 |
|------|------|
| Python | 3.11+（WebUI 后端） |
| Docling Serve | 任意可访问的实例（本机 / 远程 / Docker 均可） |
| LLM | 可选；OpenAI 兼容的 API（DeepSeek / 通义 / 智谱 / OpenAI 等） |
| 操作系统 | Windows / Linux / macOS 均可；Docker 部署不限宿主机 |

---

## 一、安装并启动 Docling Serve（OCR 引擎，必需）

> WebUI 只负责调度和展示，**必须先有一个可用的 Docling Serve**。下面两种安装方式任选其一。

### 方式 A：pip 直接安装（适合本机快速体验）

```bash
# 建议先建一个独立虚拟环境
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install "docling-serve[ui]"  # [ui] 可选，会带上演示用 Web UI

# 启动服务（默认监听 0.0.0.0:5001，API 在 /v1）
docling-serve run

# 想要自带的可视化演示界面，加 --enable-ui：
docling-serve run --enable-ui
```

- 首次启动会**自动下载模型权重**（布局检测、表格结构、OCR 等），需要联网，可能耗时几分钟，请耐心等待日志出现 `Application startup complete`。
- 启动后：
  - REST API：`http://localhost:5001`（接口文档 `http://localhost:5001/docs`）
  - 演示 UI：`http://localhost:5001/ui`（仅 `--enable-ui` 时）
  - 健康检查：`http://localhost:5001/health`（**只有 `/health` 这一个路径**）

### 方式 B：Docker / Podman 运行（推荐，免装 Python 依赖）

```bash
# 纯 CPU（最省事，开箱即用）
docker run -p 5001:5001 -e DOCLING_SERVE_ENABLE_UI=1 \
  quay.io/docling-project/docling-serve

# NVIDIA GPU 加速（需宿主机装好 nvidia-container-toolkit）
docker run --gpus all -p 5001:5001 -e DOCLING_SERVE_ENABLE_UI=1 \
  quay.io/docling-project/docling-serve-cu128
```

可用的官方镜像变体：

| 镜像 | 说明 | 适用 |
|------|------|------|
| `quay.io/docling-project/docling-serve` | 基础镜像（含 CUDA 运行时，有 GPU 自动用） | 通用 |
| `quay.io/docling-project/docling-serve-cpu` | 仅 CPU，镜像更小 | 无 GPU 的机器 |
| `quay.io/docling-project/docling-serve-cu128` | CUDA 12.8 构建 | NVIDIA GPU |
| `quay.io/docling-project/docling-serve-cu130` | CUDA 13.0 构建 | NVIDIA GPU（新驱动） |

> GPU 镜像需用**显式版本标签**，例如 `docling-serve-cu128:1.12.0`；`latest` 标签仅基础 / CPU 镜像提供。
> 分布式（多机 / 多 Worker）部署需要 Redis + `docling-serve rq-worker`，详见 Docling Serve 官方文档，一般单机用不到。

### 验证 Docling Serve 已就绪

```bash
curl http://localhost:5001/health
# 期望返回 HTTP 200（body 任意，只要状态码是 200）
```

或在浏览器打开 `http://localhost:5001/ui` 看演示界面能否上传文件并解析。

---

## 二、安装并启动 WebUI

### 1. 获取代码

```bash
git clone <your-repo-url> docling-webui
cd docling-webui
```

### 2. 安装依赖

```bash
cd src
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 配置

```bash
cp .env.example .env      # 然后按需编辑 .env
```

`.env` 关键项（详见文末「配置项说明」）：

```ini
# Docling Serve 地址（OCR 引擎，必须有）
# 填到「端口」即可，不要带 /v1 或 /ui 后缀
DOCLING_BASE_URL=http://localhost:5001

# LLM（AI 表格整理，可选）
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

> 如果 Docling Serve 跑在**另一台机器**，把 `DOCLING_BASE_URL` 改成 `http://<那台机器IP>:5001`。
> 前端「设置」页修改的参数会写入数据库，**优先级高于** `.env`。

### 4. 启动（前端由同一进程托管）

```bash
# 在 src/ 目录下执行（注意端口用 8001，8000 常被系统占用）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

启动成功日志末尾类似：

```
INFO:     Uvicorn running on http://0.0.0.0:8001
INFO:     Application startup complete.
```

### 5. 打开浏览器

访问 **http://localhost:8001**

- `/`             → 上传并解析（默认首页）
- `/tasks`        → 任务列表
- `/task?batch_id=xxx` → 任务详情
- `/settings`     → 设置（Docling / LLM 配置、测试连接）

---

## 三、使用流程

1. **上传文件**：在首页拖入图片 / PDF / Office 文档，支持多选或传一个 ZIP；按需勾选「启用 LLM 表格整理」。
2. **开始处理**：提交后自动入队；在「任务列表」选中批次 → 点「开始处理」，状态自动刷新，变 `completed` 即可。
3. **查看结果**：进「任务详情」→ 顶部是**批次汇总表**（AI 把每个文件的信息合成一张表），下方按文件看**原图 / PDF 原页 + OCR 原文**；点击右侧识别字段可在原图 / 原页上高亮定位（PDF 自动跳到对应页）。
4. **导出**：
   | 按钮 | 内容 | 适合 |
   |------|------|------|
   | 导出汇总表 CSV | 纯数据，无图 | Excel |
   | 导出汇总表 HTML | 带 base64 缩略图的网页表 | 直观查看 |
   | 导出批次 ZIP | 原图 + OCR + 表格完整包 | 存档 |
5. **重跑**：单文件识别失败 → 详情页选中它点「重新识别(OCR)」；整批重试 → 任务列表选批次再点「开始处理」。

---

## 四、Docker 部署（推荐生产 / 一键编排）

### 仅部署 WebUI（Docling Serve 已在别处运行）

```bash
# 构建镜像
docker build -t docling-webui .

# 运行（把 DOCLING_BASE_URL 指向你已有的 Docling Serve）
docker run -d --name docling-webui -p 8001:8001 \
  -e DOCLING_BASE_URL=http://<docling-host>:5001 \
  -e LLM_API_KEY=sk-xxx \
  -e LLM_BASE_URL=https://api.openai.com/v1 \
  -e LLM_MODEL=gpt-4o-mini \
  -v docling-webui-data:/app/src/data \
  -v docling-webui-uploads:/app/src/uploads \
  docling-webui
```

访问 http://localhost:8001 。数据（SQLite）和上传文件通过卷持久化。

### 一体编排（WebUI + Docling Serve，一条命令跑起来）

项目自带 `docker-compose.yml`，已把两个服务连好：

```bash
# 可选：把 LLM 配置写进环境变量或 .env，再启动
docker compose up -d
```

- WebUI：http://localhost:8001
- Docling Serve：http://localhost:5001 （含演示 UI）
- WebUI 通过内部服务名 `http://docling:5001` 自动连接 OCR 引擎，无需手动填地址。

> 想用 GPU 加速 OCR，把 `docker-compose.yml` 里 docling 服务的 `image` 换成
> `quay.io/docling-project/docling-serve-cu128`，并在 `docling` 服务下加 `deploy.resources.reservations.devices` 或 `docker run --gpus all` 等价配置（详见 Docker 文档）。

---

## 五、配置项说明

`src/.env` 全部可配项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DOCLING_BASE_URL` | `http://localhost:5001` | **必填**。Docling Serve 地址，填到端口，不要带 `/v1`、`/ui` |
| `DOCLING_TABLE_MODE` | `accurate` | 表格识别模式：`fast`（快）或 `accurate`（准） |
| `POLL_INTERVAL_SECONDS` | `2` | 轮询 Docling 任务状态的间隔（秒） |
| `LLM_API_KEY` | `your-api-key-here` | LLM 的 API Key，可在设置页改 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM 服务地址，必须带 `/v1` |
| `LLM_MODEL` | `gpt-4o-mini` | 模型名 |
| `DATABASE_PATH` | `./data/docling_webui.db` | SQLite 数据库路径（相对 src/） |
| `UPLOAD_DIR` | `./uploads` | 上传文件目录（相对 src/） |
| `MAX_FILE_SIZE_MB` | `50` | 单文件大小上限（MB） |
| `MAX_ZIP_SIZE_MB` | `200` | ZIP 包上限（MB） |
| `MAX_FILES_PER_BATCH` | `500` | 每批最多文件数 |

> Docker 部署时，上述任意项都可用 `-e 环境变量` / compose `environment` 覆盖 `.env`。
> 注意 `PORT` 在容器里固定为 `8001`（见 Dockerfile `CMD`），无需改。

---

## 六、常见问题

**Q：页面提示 Docling 连接失败 / OCR 一直 processing？**
A：先 `curl http://<docling-host>:5001/health` 确认 Docling Serve 在线；再检查 `.env` 里 `DOCLING_BASE_URL` 是否填对（到端口、不带 `/v1`）。也可用设置页的「测试 Docling」按钮验证。Docling Serve 只有 `/health` 这一个健康路径。

**Q：LLM 汇总表生成失败？**
A：常见原因——LLM 端点返回的是流式(SSE)响应，或 Key / 模型名填错。本程序已对 SSE 流式响应做兼容（使用 `stream=True` 并累加 `delta.content`）。在设置页点「测试连接」确认可用；汇总表对模型返回格式较敏感，建议使用支持 JSON 输出的模型。

**Q：端口被占用？**
A：WebUI 默认跑在 `8001`（8000 常被系统占用）。换端口启动：`uvicorn app.main:app --port <新端口>`，并同步修改访问地址。

**Q：重启后端后，正在处理的批次没了？**
A：后端启动时会把中断的 `processing` 批次自动重置为 `created`，交给调度器续跑；在任务列表重新点「开始处理」即可。

**Q：导出汇总表为什么没有图片？**
A：CSV 只有文字；**HTML 格式**才内嵌 base64 缩略图，适合直观查看。

**Q：Docling Serve 启动慢 / 占资源？**
A：首次会下载模型权重；纯 CPU 推理较慢但能跑，生产建议上 GPU 镜像（`-cu128` / `-cu130`）。

**Q：PDF 怎么预览和定位？**
A：后端用 PyMuPDF 把 PDF 每页实时渲染成图片并缓存，前端按页展示；点击识别字段会自动跳到对应页并在原页上画高亮框。首次打开某 PDF 会稍慢（取决于页数），之后走缓存。

---

## 七、目录结构

```
├── src/                  # 应用目录（后端 + 前端合并，FastAPI 同源托管静态页）
│   ├── app/
│   │   ├── main.py          # 入口：API 路由 + 静态前端托管
│   │   ├── config.py        # 配置（读取 .env）
│   │   ├── db/              # 数据库（aiosqlite）
│   │   ├── routers/         # API 路由（batches / files / config）
│   │   ├── services/        # 业务（docling_service / llm_service / export / queue_scheduler）
│   │   ├── repositories/    # 数据访问
│   │   ├── models/          # 数据模型
│   │   └── utils/
│   ├── index.html           # 上传并解析（默认首页）
│   ├── tasks.html           # 任务列表
│   ├── task.html            # 任务详情（图片/PDF 预览 + 字段高亮）
│   ├── settings.html        # 设置
│   ├── assets/              # 共享 css/js（由 /assets 挂载）
│   ├── data/                # SQLite 数据库文件（持久化，gitignore）
│   ├── uploads/             # 上传文件（持久化，gitignore）
│   ├── requirements.txt
│   ├── .env.example
│   └── .env                 # 本地配置（不入库）
├── Dockerfile             # WebUI 镜像构建
├── docker-compose.yml     # WebUI + Docling Serve 一体编排
├── .dockerignore
├── .gitignore
└── README.md
```

---

## 相关链接

- Docling Serve 官方文档：https://docling-project.github.io/docling/usage/api_server/deployment
- Docling Serve 仓库：https://github.com/docling-project/docling-serve
- Docling 论文：https://arxiv.org/abs/2501.17887
