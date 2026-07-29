# ADR-002: 使用 FastAPI 作为后端框架

## Status: Accepted (2026-07-22)

## Background

后端需要编排三个核心流程：
1. 接收文件上传（包括 ZIP 解压）
2. 调用 Docling Serve API 进行 OCR 转换（异步任务轮询）
3. 调用 LLM API 进行表格数据提取
4. 打包导出 ZIP 文件

Docling Serve 本身是 Python 服务。后端需要处理异步任务轮询、文件流式上传/下载、外部 API 调用等场景。

## Decision

选择 **FastAPI (Python)** 作为后端框架。

技术栈：
- FastAPI (Web 框架)
- Uvicorn (ASGI 服务器)
- Pydantic v2 (数据验证)
- httpx (异步 HTTP 客户端，调用 Docling/LLM)
- openai SDK (LLM API 调用)
- aiosqlite (异步 SQLite 驱动)
- aiofiles (异步文件操作)
- python-multipart (文件上传)

## Consequences

### 正面后果
- 原生异步支持，适合轮询 Docling 异步任务
- 自动生成 OpenAPI 文档（Swagger UI），前后端联调方便
- Pydantic 提供运行时数据验证，减少 bug
- Python 生态中 openai SDK 直接可用，无需封装
- 与 Docling Serve 同为 Python 生态，技术栈统一
- 样板代码少，开发速度快

### 负面后果
- Python GIL 限制 CPU 密集型并发（本场景 I/O 密集，影响不大）
- 单进程 Uvicorn 在高并发下性能不如 Go/Node.js（内部工具可接受）
- 需要管理 Python 虚拟环境

## Related ADRs
- ADR-001 (前端框架)
- ADR-003 (数据库)
- ADR-005 (ZIP 处理方案)
