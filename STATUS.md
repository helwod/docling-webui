# Docling Serve WebUI — Gradio 前端修复与端到端验证状态

> 2026-07-22 | 前端技术栈已切到 Gradio 6（Python），后端保留 FastAPI

## 已修复的关键问题

### 1. 后端 `POST /api/v1/batches` 返回 500（阻断创建批次）
- **根因**：`backend/app/services/upload_service.py` 误用 `await aiofiles.open(...)`，再对返回值做 `async with`，触发
  `TypeError: 'AsyncBufferedIOBase' object does not support the async context manager protocol`。
- **修复**：`_open_write` 改为普通方法返回 `aiofiles.open(path,"wb")`（本身是异步上下文管理器），调用处去掉多余 `await`。
- **验证**：TestClient 与真实 HTTP 均返回 `201 Created`。

### 2. 配置漂移：Docling 地址指向不可达的 localhost
- **根因**：后端配置以 DB `settings` 表为准，首建库时用 `INSERT OR IGNORE` 种入当时 `.env` 的 `localhost:5001`；之后 `.env` 改为可达的 `10.0.0.22:5001` 但 DB 未更新，`GET /config` 仍返回不可达地址。
- **修复**：经 `PUT /api/v1/config` 把 `docling_base_url` 校正为 `http://10.0.0.22:5001`（即 Settings 页的做法）。
- **经验**：改 `.env` 后必须再经 Settings 页/API 同步，否则不生效。

### 3. 后端双实例收敛
- 此前有两个 uvicorn 同时监听 8000（一个 loopback、一个 0.0.0.0），请求被非确定性转发。已合并为单个 `--reload` 实例。

## 端到端验证结论（全链路打通）

| 环节 | 结果 |
|------|------|
| 服务健康 | 后端 `:8000` = 200，前端 Gradio `:7860` = 200 |
| 创建批次 | `POST /batches` → 201 |
| 列表 / 详情 / 状态 / 配置 | 全部通过（信封 `{code,data}` 解析正确） |
| OCR 真机 | create → process(`enable_llm=false`) → 轮询 Docling `10.0.0.22:5001` → `ocr_status=completed` |
| 原图回看 | `GET /files/{fid}/image` 返回有效 PNG |
| 导出 | `GET /batches/{id}/export?format=both` → zip（`original_images/*.png` + `ocr_results/*.json` + `summary.json`） |

**未跑（依赖用户配置）**：LLM 表格整理需要真实 OpenAI Key。在 Settings 页填入 Key 后，`process` 带 `enable_llm=true` 才会执行 LLM 整理；当前无 Key 时该步骤会失败/跳过。

## 运行方式
- 后端：`cd backend && C:/python311/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- 前端：`C:/Users/Administrator/.workbuddy/binaries/python/envs/gradio/Scripts/python.exe -m gradio_app`（端口 7860）
- 当前两服务均在后台运行；浏览器打开 `http://localhost:7860` 即可使用。

## 下一步建议
1. 在 Settings 页填入真实 LLM API Key，验证 LLM 表格整理全链路。
2. 准备几张真实含表格的图片做一轮业务级验收（而非 1×1 测试 PNG）。
3. 视需要补充 `README` 启动说明，或清理旧的 `frontend/`（React）目录。
