# Docling Serve WebUI - 交付总览

> 状态：开发完成 ✅

## 功能概述

Docling Serve 服务的 WebUI，实现批量图片 / 文档 OCR 并对接语言大模型，整理表格数据并支持导出。

### 功能

| 功能 | 状态 |
|------|------|
| 图片 / PDF / Office 文档上传与 ZIP 批量解压 | ✅ |
| Docling Serve API 对接（异步 + 轮询） | ✅ |
| LLM 表格后处理（OpenAI 兼容，流式 SSE 兼容） | ✅ |
| 任务列表与状态追踪 | ✅ |
| 结果导出（CSV / 带缩略图 HTML / ZIP） | ✅ |
| 单文件预览（图片 & PDF 多页）+ 字段点击高亮定位 | ✅ |

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | 原生 HTML / CSS / JS（多页面，由后端同源托管） |
| 后端 | FastAPI + SQLite + httpx + openai SDK + PyMuPDF（PDF 渲染） |
| 部署 | Docker / Docker Compose 一键启动 |

## 项目结构

```
docling-webui/
├── src/          # 应用目录（后端代码 + 前端静态页 + 配置，统一在此）
│   ├── app/          # 后端代码（入口 main.py 同源托管前端）
│   ├── *.html        # 4 个页面（index / tasks / task / settings）
│   ├── assets/       # 共享 css/js
│   ├── data/         # SQLite 数据库（gitignore）
│   ├── uploads/      # 上传文件（gitignore）
│   └── requirements.txt / .env.example
├── docs/         # 文档 (PRD, Spec, 架构, 设计, ADR)
├── Dockerfile / docker-compose.yml / .dockerignore / .gitignore
└── README.md
```

## 启动方式

### 开发环境
```bash
# 单进程：后端同源托管前端静态页，无需独立前端终端
cd src
pip install -r requirements.txt
cp .env.example .env  # 编辑设置 LLM_API_KEY / DOCLING_BASE_URL
uvicorn app.main:app --reload --port 8001
# 浏览器访问 http://localhost:8001
```

### 生产环境（Docker Compose）
```bash
docker compose up -d
```

## 关键依赖
- Docling Serve（必须运行）：http://localhost:5001
- LLM API Key（可选）：环境变量 LLM_API_KEY
