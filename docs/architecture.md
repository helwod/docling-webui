# Docling Serve WebUI - 技术架构文档

## 1. 技术选型对比矩阵

### 1.1 前端框架对比

| 维度 | React + Vite | Next.js 15 | Vue 3 + Vite |
|------|-------------|------------|--------------|
| 学习成本 | 低（团队熟悉 React） | 中（App Router 概念多） | 低 |
| 生态成熟度 | 高（最大生态） | 高（Vercel 生态） | 中高 |
| 部署成本 | 低（纯静态 SPA） | 中（需 Node 运行时或 Vercel） | 低 |
| SEO 支持 | 无（CSR） | 原生 SSR/SSG | 无（CSR） |
| 适用场景 | 内部工具/管理后台 | 内容站/电商 | 内部工具/管理后台 |
| 团队熟悉度 | 高 | 中 | 中 |
| 构建速度 | 极快（esbuild） | 快（Turbopack） | 极快（esbuild） |

**结论：React + Vite**

理由：本项目是个人/内部工具，无 SEO 需求，纯 SPA 即可。React 生态最大，Vite 构建极快，部署简单（静态文件）。Next.js 的 SSR/SSG 对内部工具是过度设计。

### 1.2 后端框架对比

| 维度 | FastAPI (Python) | Express (Node.js) | NestJS (Node.js) |
|------|------------------|--------------------|-------------------|
| 学习成本 | 低（几小时上手） | 低 | 高（DI、装饰器、模块化） |
| 生态成熟度 | 高（89k+ stars） | 高 | 高（72k+ stars） |
| 部署成本 | 低（uvicorn 单进程） | 低 | 中 |
| 自动文档 | 原生 Swagger UI + ReDoc | 需 swagger-jsdoc | 需 @nestjs/swagger |
| 类型安全 | Pydantic 运行时验证 | 弱 | class-validator |
| 异步支持 | 原生 async/await | 原生 | 原生 |
| Python 生态 | ML/AI 库直接可用 | 无 | 无 |
| 样板代码 | 少 | 少 | 多 |
| 团队熟悉度 | 中 | 中 | 低 |

**结论：FastAPI (Python)**

理由：Docling Serve 本身是 Python 服务，用 Python 后端编排更自然。FastAPI 原生异步支持适合轮询 Docling 任务，自动生成 OpenAPI 文档省去手写，Pydantic 提供运行时验证。LLM API 调用在 Python 生态中有 openai SDK 直接可用。

### 1.3 数据库对比

| 维度 | SQLite | PostgreSQL |
|------|--------|------------|
| 部署成本 | 零（嵌入式，单文件） | 中（需安装+配置服务） |
| 并发写入 | 单写者（WAL 模式） | 多写者（MVCC） |
| 并发读取 | 无限 | 无限 |
| 维护成本 | 零 | 需 DBA 知识 |
| 备份 | 复制文件 | pg_dump/WAL |
| 适用场景 | 单机/内部工具/桌面应用 | 多用户/高并发/生产 Web |
| 数据量上限 | 281TB（理论） | 无限 |
| 迁移成本 | 低 | 高 |

**结论：SQLite (WAL 模式)**

理由：个人/内部工具，单用户使用，写并发极低。SQLite 零配置、零维护、备份只需复制文件。WAL 模式下读写不互相阻塞，完全满足需求。

### 1.4 图标库对比

| 维度 | Lucide React | Heroicons | Tabler Icons |
|------|-------------|-----------|--------------|
| 图标数量 | 1700+ | ~300/风格 | 5000+ |
| Tree-shaking | 完全支持 | 支持 | 支持 |
| 包大小（单个图标） | 极小 | 极小 | 小 |
| 设计风格 | 现代简洁（Feather 升级版） | 极简 | 专业 |
| 可定制性 | stroke-width/color/size | 有限 | stroke-width |
| 框架支持 | React/Vue/Svelte 等 | React/Vue | React/Vue/Svelte |
| 许可证 | ISC | MIT | MIT |
| 与 Tailwind 集成 | 优秀 | 原生（Tailwind 团队出品） | 优秀 |
| 社区活跃度 | 高（22.6k stars） | 高（23.5k stars） | 高（18k stars） |
| shadcn/ui 默认集成 | 是 | 否 | 否 |

**结论：Lucide React（锁定）**

理由：1700+ 图标覆盖所有场景需求，Tree-shaking 完全支持确保按需加载，是 shadcn/ui 默认图标库，与 React + Tailwind 生态完美融合。可定制性强（stroke-width/color/size），现代简洁风格适合内部工具。

### 1.5 前端 UI 组件库

**结论：shadcn/ui + Tailwind CSS**

理由：shadcn/ui 不是传统组件库，而是可复制粘贴的组件集合，代码完全可控。与 Lucide 图标库原生集成，基于 Radix UI 提供无障碍支持，Tailwind CSS 原子化样式便于定制。

---

## 2. 分层架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser (SPA)                          │
│    React 18 + Vite + Tailwind CSS + Lucide React           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Upload   │ │ Batch    │ │ Result   │ │ Export &      │  │
│  │ View     │ │ List     │ │ Viewer   │ │ Download      │  │
│  │          │ │ View     │ │ View     │ │ View          │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  State: Zustand | Data: TanStack Query | Router:     │   │
│  │  React Router | HTTP: axios                           │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/JSON (REST API)
┌────────────────────────┴────────────────────────────────────┐
│                   FastAPI Backend (Python)                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   API Layer (Routers)                 │   │
│  │  /batches  /files  /process  /export  /config         │   │
│  └────────────────────────┬─────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                Service Layer (Business Logic)         │   │
│  │  UploadService | DoclingService | LLMService |        │   │
│  │  ExportService | TaskPoller                           │   │
│  └──────────┬──────────────┬──────────────┬─────────────┘   │
│  ┌──────────┴──────────────┴──────────────┴─────────────┐   │
│  │                Data Layer (Repository)                │   │
│  │  SQLite (WAL mode) | File Storage (local disk)        │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────┬────────────────────────────┬────────────────────┘
            │                            │
            ▼                            ▼
┌───────────────────────┐    ┌───────────────────────────┐
│   Docling Serve       │    │   LLM API                 │
│   http://localhost:5001│   │   (OpenAI-compatible)      │
│                       │    │                           │
│   POST /v1/convert/   │    │   POST /v1/chat/completions│
│     file/async        │    │   (JSON mode for tables)   │
│   GET  /v1/status/    │    │                           │
│     poll/{task_id}    │    │                           │
│   GET  /v1/result/    │    │                           │
│     {task_id}         │    │                           │
└───────────────────────┘    └───────────────────────────┘
```

### 2.1 分层职责

| 层 | 职责 | 约束 |
|----|------|------|
| 表现层 (Frontend SPA) | 用户交互、状态管理、数据展示 | 不直接调用 Docling/LLM，只调 WebUI 后端 API |
| API 层 (Routers) | 请求路由、参数校验、响应格式化 | 不含业务逻辑，只做编排 |
| 服务层 (Services) | 核心业务逻辑：上传编排、OCR 调度、LLM 调用、导出打包 | 可调用外部服务（Docling/LLM），可调用数据层 |
| 数据层 (Repository) | 数据持久化（SQLite）、文件存储（磁盘） | 不含业务逻辑，只做 CRUD |

### 2.2 目录结构约束

```
docling-webui/
├── frontend/                    # 前端 SPA
│   ├── src/
│   │   ├── components/          # 通用组件（单个文件 <= 300 行）
│   │   │   ├── ui/              # shadcn/ui 基础组件
│   │   │   ├── upload/          # 上传相关组件
│   │   │   ├── batch/           # 批次列表相关组件
│   │   │   └── result/          # 结果查看相关组件
│   │   ├── pages/               # 页面组件（路由入口，只做装配）
│   │   ├── hooks/               # 自定义 Hooks
│   │   ├── lib/                 # 工具函数（api client, utils）
│   │   ├── store/               # Zustand 状态管理
│   │   └── types/               # TypeScript 类型定义
│   ├── public/
│   ├── package.json
│   └── vite.config.ts
│
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── main.py              # 应用入口（只做装配）
│   │   ├── config.py            # 配置管理
│   │   ├── routers/             # API 路由（按资源分包）
│   │   │   ├── batches.py
│   │   │   ├── files.py
│   │   │   ├── process.py
│   │   │   ├── export.py
│   │   │   └── config.py
│   │   ├── services/            # 业务逻辑（单个文件 <= 300 行）
│   │   │   ├── upload_service.py
│   │   │   ├── docling_service.py
│   │   │   ├── llm_service.py
│   │   │   ├── export_service.py
│   │   │   └── task_poller.py
│   │   ├── models/              # Pydantic 模型（请求/响应）
│   │   ├── repositories/        # 数据访问层
│   │   │   ├── batch_repo.py
│   │   │   ├── file_repo.py
│   │   │   └── setting_repo.py
│   │   ├── db/                  # 数据库初始化和迁移
│   │   │   ├── database.py
│   │   │   └── migrations/
│   │   └── utils/               # 工具函数
│   ├── uploads/                 # 上传文件存储目录
│   ├── requirements.txt
│   └── pyproject.toml
│
├── docs/                        # 项目文档
│   ├── architecture.md          # 本文件
│   ├── api-spec.yaml            # OpenAPI 3.0 规范
│   ├── database-schema.md       # 数据库设计
│   └── decisions/               # ADR 文档
│       ├── ADR-001-frontend-framework.md
│       ├── ADR-002-backend-framework.md
│       ├── ADR-003-database.md
│       ├── ADR-004-icon-library.md
│       └── ADR-005-zip-processing.md
│
├── .env.example                 # 环境变量模板
└── docker-compose.yml           # 一键启动
```

---

## 3. 核心功能技术可行性验证

### 3.1 ZIP 文件批量上传和解析

**方案：后端解压**

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 前端解压 | 减少服务器压力 | 浏览器兼容性差、无法安全验证、大文件内存溢出 | 不采用 |
| 后端解压 | 安全可控、可校验文件类型/大小、防止 zip bomb | 需服务器磁盘空间 | 采用 |

**实现要点：**
- FastAPI 接收 ZIP 文件（multipart/form-data），流式写入磁盘
- 使用 Python `zipfile` 模块解压，包含安全检查：
  - 文件数量限制（最大 500 个）
  - 解压后总大小限制（最大 500MB）
  - 压缩比检查（防止 zip bomb，最大 100:1）
  - 路径遍历检查（拒绝 `..` 和绝对路径）
- 解压后逐个文件验证 MIME 类型（仅允许图片和 PDF）
- 将有效文件存入 `uploads/` 目录，记录到数据库

### 3.2 Docling Serve 异步任务轮询机制

**方案：异步提交 + 轮询 + WebSocket（可选）**

```
1. 前端上传文件 -> 后端创建 batch 记录
2. 后端调用 Docling POST /v1/convert/file/async（逐文件提交）
3. 后端启动 asyncio 后台任务轮询 GET /v1/status/poll/{task_id}
   - 轮询间隔：2 秒
   - 最大轮询时间：10 分钟
   - 状态：pending -> started -> success / failure
4. 任务完成后 GET /v1/result/{task_id} 获取结果
5. 将 md_content / json_content 存入数据库
6. 前端通过轮询 GET /api/v1/batches/:id/status 获取进度
```

**并发控制：**
- 单个 batch 内最多 5 个文件同时提交 Docling 转换（asyncio.Semaphore）
- 避免大量并发请求压垮 Docling Serve

### 3.3 LLM 表格数据整理的 Prompt 工程

**方案：OpenAI 兼容 API + JSON Mode + Few-shot Prompting**

```python
SYSTEM_PROMPT = """You are a table data extraction assistant.
Your task is to analyze OCR-processed markdown content and extract
structured table data into JSON format.

Rules:
1. Only extract table data, ignore non-table content
2. Preserve original column headers
3. Each row becomes a JSON object in an array
4. If no table is found, return empty array
5. Return ONLY valid JSON, no explanations

Output format:
{
  "tables": [
    {
      "table_index": 0,
      "headers": ["column1", "column2", ...],
      "rows": [
        {"column1": "value1", "column2": "value2", ...},
        ...
      ]
    }
  ]
}"""

USER_PROMPT_TEMPLATE = """Here is the OCR markdown content:

{ocr_md_content}

Extract all tables from the above content into structured JSON format."""
```

**技术要点：**
- 使用 `response_format={"type": "json_object"}` 强制 JSON 输出
- `temperature=0` 确保结果确定性
- Pydantic 模型验证 LLM 返回的 JSON 结构
- 请求超时 60 秒，失败后自动重试 1 次
- 支持 GPT-4o / GPT-4o-mini / 任何 OpenAI 兼容模型

### 3.4 导出功能（含原始图片的 ZIP 打包）

**方案：Python zipfile + StreamingResponse**

```
导出 ZIP 内容结构：
export_{batch_name}_{timestamp}.zip
├── original_images/
│   ├── 001_image1.png
│   ├── 002_image2.jpg
│   └── ...
├── ocr_results/
│   ├── 001_image1.md
│   ├── 001_image1.json
│   ├── 002_image2.md
│   └── ...
├── llm_tables/
│   ├── 001_image1_tables.json
│   ├── 001_image1_tables.csv
│   └── ...
└── summary.json    # 批次摘要信息
```

**实现要点：**
- 使用 `tempfile.NamedTemporaryFile` 创建临时 ZIP 文件
- `zipfile.ZIP_DEFLATED` 压缩
- `StreamingResponse` 流式返回，避免内存溢出
- `BackgroundTask` 在响应完成后清理临时文件
- 支持单个文件导出和整批导出

---

## 4. 技术约束清单

| 编号 | 约束 | 说明 |
|------|------|------|
| C-01 | Docling Serve 必须运行 | 默认地址 http://localhost:5001，可通过环境变量配置 |
| C-02 | LLM API Key 必须配置 | 环境变量 `LLM_API_KEY`，兼容 OpenAI API 格式 |
| C-03 | Python >= 3.11 | FastAPI 异步特性需要 |
| C-04 | Node.js >= 18 | Vite 构建需要 |
| C-05 | 单文件大小限制 50MB | 防止内存溢出 |
| C-06 | ZIP 文件大小限制 200MB | 防止磁盘耗尽 |
| C-07 | 单批次最大文件数 500 | 防止 Docling Serve 过载 |
| C-08 | 支持文件类型 | PNG, JPG, JPEG, PDF, TIFF, BMP, GIF, WEBP |
| C-09 | Docling 轮询间隔 2 秒 | 平衡及时性和服务器压力 |
| C-10 | LLM 请求超时 60 秒 | 防止长时间阻塞 |
| C-11 | 并发 Docling 转换上限 5 | asyncio.Semaphore 控制 |
| C-12 | SQLite WAL 模式 | 启用 Write-Ahead Logging 提升并发读 |
| C-13 | 图标库锁定 Lucide React | 全项目统一使用，禁止混用其他图标库 |
| C-14 | 禁止 emoji 作为功能图标 | 所有 UI 图标必须使用 Lucide React SVG 组件 |

---

## 5. 技术栈锁定清单

### 前端依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| react | ^18.3 | UI 框架 |
| react-dom | ^18.3 | React DOM 渲染 |
| react-router-dom | ^6.26 | 客户端路由 |
| vite | ^5.4 | 构建工具 |
| @vitejs/plugin-react | ^4.3 | Vite React 插件 |
| typescript | ^5.5 | 类型系统 |
| tailwindcss | ^3.4 | 原子化 CSS |
| lucide-react | ^0.400 | SVG 图标库（锁定） |
| @tanstack/react-query | ^5.51 | 服务端状态管理 |
| zustand | ^4.5 | 客户端状态管理 |
| axios | ^1.7 | HTTP 客户端 |
| class-variance-authority | ^0.7 | shadcn/ui 依赖 |
| clsx | ^2.1 | className 合并 |
| tailwind-merge | ^2.4 | Tailwind class 去重 |
| @radix-ui/react-* | latest | shadcn/ui 底层无障碍组件 |

### 后端依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| fastapi | ^0.111 | Web 框架 |
| uvicorn[standard] | ^0.30 | ASGI 服务器 |
| python-multipart | ^0.0.9 | 文件上传支持 |
| aiofiles | ^24.1 | 异步文件操作 |
| httpx | ^0.27 | 异步 HTTP 客户端（调用 Docling/LLM） |
| openai | ^1.35 | LLM API SDK |
| pydantic | ^2.7 | 数据验证 |
| pydantic-settings | ^2.3 | 配置管理 |
| aiosqlite | ^0.20 | 异步 SQLite 驱动 |
| python-dotenv | ^1.0 | 环境变量加载 |

---

## 6. 环境变量配置

```bash
# .env.example

# Docling Serve
DOCLING_BASE_URL=http://localhost:5001

# LLM API (OpenAI-compatible)
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# Database
DATABASE_PATH=./data/docling_webui.db

# File Storage
UPLOAD_DIR=./uploads
MAX_FILE_SIZE_MB=50
MAX_ZIP_SIZE_MB=200
MAX_FILES_PER_BATCH=500

# Server
HOST=0.0.0.0
PORT=8000

# 注：表格识别模式(docling_table_mode)、轮询间隔(poll_interval_seconds)、
# OCR 引擎、图片导出模式等均为数据库存储的运行时设置，并非环境变量。
# 容器首次启动由数据库播种默认值，之后可在前端「设置」页修改。
```

---

## 7. 数据流设计

### 7.1 上传 + OCR + LLM 完整流程

```
用户上传 ZIP/图片
       │
       ▼
[1] POST /api/v1/batches (multipart/form-data)
       │
       ▼
[2] UploadService: 保存文件到磁盘，创建 batch + files 记录
       │
       ▼
[3] POST /api/v1/batches/:id/process
       │
       ▼
[4] DoclingService: 逐文件调用 POST /v1/convert/file/async
       │  (asyncio.Semaphore 限制并发 5)
       ▼
[5] TaskPoller: 后台轮询 GET /v1/status/poll/{task_id}
       │  (间隔 2s, 超时 10min)
       ▼
[6] 任务完成 -> GET /v1/result/{task_id}
       │
       ▼
[7] 存储 ocr_md_content / ocr_json_content 到 files 表
       │
       ▼
[8] LLMService: 调用 LLM API 提取表格数据
       │  (temperature=0, JSON mode, timeout=60s)
       ▼
[9] Pydantic 验证 -> 存储 llm_result 到 files 表
       │
       ▼
[10] 前端轮询 GET /api/v1/batches/:id/status 获取进度
       │
       ▼
[11] 用户查看结果 / 导出 ZIP
```

### 7.2 导出流程

```
用户点击导出
       │
       ▼
[1] GET /api/v1/batches/:id/export
       │
       ▼
[2] ExportService: 查询 batch + 所有 files
       │
       ▼
[3] 创建 tempfile ZIP
       │
       ▼
[4] 写入 original_images/ (原始文件)
       │
       ▼
[5] 写入 ocr_results/ (md + json)
       │
       ▼
[6] 写入 llm_tables/ (json + csv)
       │
       ▼
[7] 写入 summary.json (批次摘要)
       │
       ▼
[8] StreamingResponse 返回 ZIP
       │
       ▼
[9] BackgroundTask 清理临时文件
```
