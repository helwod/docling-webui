# Docling Serve 接口说明与调用文档

> 基于真实环境 `http://10.0.0.22:5001`（Docling Serve **1.27.0**）实测核实。
> 所有请求/响应结构均已用真机跑通验证，非推测。

---

## 1. 重要：同一服务有两个接口，别配错

你贴的 `http://10.0.0.22:5001/ui/` 是 **Gradio 演示界面**的客户端 API（`@gradio/client` 的 `client.predict(...)`），主要给浏览器 JS 直连用。

我们的 WebUI 后端对接的是同一进程上的 **REST API（FastAPI）**，路径在 `/v1/...`。

| 接口 | 地址 | 用途 | 我们是否使用 |
|------|------|------|------|
| REST API | `http://10.0.0.22:5001/v1/convert/file/async` | 服务端编排、批量 | **使用** ✅ |
| Gradio UI | `http://10.0.0.22:5001/ui/` | 人工网页操作 / JS 直连 | 不使用 |

**配置时 `DOCLING_BASE_URL` 只填到端口根地址，不要带 `/ui/`：**
```
DOCLING_BASE_URL=http://10.0.0.22:5001      # 正确
DOCLING_BASE_URL=http://10.0.0.22:5001/ui/  # 错误，会 404
```

验证两个接口都在线（真机返回）：
```
GET /docs            -> 200   (FastAPI Swagger)
GET /openapi.json    -> 200
GET /v1/convert/file/async (POST) -> 405 (端点存在，需 POST)
GET /ui/             -> Gradio 界面
```

---

## 2. 我们后端实际调用的 3 个端点

### 2.1 提交异步转换
```
POST {DOCLING_BASE_URL}/v1/convert/file/async
Content-Type: multipart/form-data
```
**表单字段（务必照此）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `files` | 文件（**复数** `files`） | 上传的图片/PDF。**字段名必须是 `files`**，单数 `file` 会被忽略 |
| `to_formats` | 字符串列表 | 重复字段：`to_formats=md`、`to_formats=json`、`to_formats=html`。**不能传 JSON 字符串**，会被枚举校验拒绝 |
| `do_ocr` | `"true"`/`"false"` | 开启 OCR |
| `force_ocr` | `"false"` | 强制重做 OCR |
| `table_mode` | `"fast"`/`"accurate"` | 表格识别模式 |
| `image_export_mode` | `"placeholder"`/`"embedded"`/`"referenced"` | 图片导出方式 |

**成功响应（200）：**
```json
{
  "task_id": "a88a14bf-813b-40cd-b1d2-22b2e6fd1533",
  "task_type": "convert",
  "task_status": "pending",
  "task_position": 1,
  "task_meta": null,
  "error_message": null,
  "failure": null
}
```
> 取 `task_id` 用于后续轮询。

### 2.2 轮询任务状态
```
GET {DOCLING_BASE_URL}/v1/status/poll/{task_id}
```
**响应（200）：**
```json
{
  "task_id": "...",
  "task_type": "convert",
  "task_status": "started",        // 注意字段是 task_status，不是 status
  "task_position": 1,
  "task_meta": null,
  "error_message": null,
  "failure": null
}
```
**`task_status` 枚举值：**
| 值 | 含义 | 我们的处理 |
|----|------|------|
| `pending` | 排队中 | 继续轮询 |
| `started` | 处理中 | 继续轮询 |
| `success` | 成功 | 取结果 ✅ |
| `partial_success` | 部分成功（有结果但有警告） | 取结果 ✅（与 success 同等处理） |
| `failure` | 失败 | 标记失败 ❌ |
| `skipped` | 跳过 | 标记失败 ❌ |

> ⚠️ 历史代码曾用 `data.get("status")` 且只认 `success`/`completed`，会导致 **partial_success 永远轮询到超时**。已修复为识别 `task_status` 且把 `partial_success` 视为成功。

### 2.3 获取转换结果
```
GET {DOCLING_BASE_URL}/v1/result/{task_id}
```
**响应（200，application/json）：**
```json
{
  "document": {                    // 内容嵌套在 document 下，不是顶层！
    "filename": "test_ocr.png",
    "md_content": "# ...markdown...",
    "json_content": { "...": "DoclingDocument 对象" },
    "html_content": "<html>...</html>",
    "text_content": "...",
    "doctags_content": "...",
    "doclang_content": "..."
  },
  "status": "success",
  "errors": [],
  "processing_time": 1.23,
  "timings": {},
  "confidence": null
}
```
> ⚠️ 历史代码曾读顶层 `md_content`（`data.get("md_content")`），真实结构在 `document.md_content`，会导致 **内容全空**。已修复。

### 2.4 健康检查
```
GET {DOCLING_BASE_URL}/health        # 正确端点
# 注：不存在 /v1/health，历史代码用错会 404
```

---

## 3. 真机验证过的 curl 示例

```bash
# 1) 提交（files 复数 + 重复 to_formats）
curl -X POST "http://10.0.0.22:5001/v1/convert/file/async" \
  -F "files=@demo.png;type=image/png" \
  -F "to_formats=md" -F "to_formats=json" -F "to_formats=html" \
  -F "do_ocr=true" -F "table_mode=accurate" -F "image_export_mode=placeholder"
# -> 返回 {"task_id": "..."}

# 2) 轮询（用 task_status 字段）
curl "http://10.0.0.22:5001/v1/status/poll/<task_id>"
# -> {"task_status":"success", ...}

# 3) 取结果（从 document 下取）
curl "http://10.0.0.22:5001/v1/result/<task_id>" | python -c "import sys,json;d=json.load(sys.stdin);print(d['document']['md_content'])"
```

---

## 4. 连通性自检（设置页「测试连接」用的就是它）
```
GET {DOCLING_BASE_URL}/health  -> 200 表示 Docling Serve 可达
```

---

## 5. 附：Gradio `/ui/` 客户端调用（仅供参考，本系统不用）

如果你将来想在纯前端直连 Docling（绕过我们后端），可以用你贴的 `@gradio/client` 方式：
```js
import { Client } from "@gradio/client";
const client = await Client.connect("http://10.0.0.22:5001/ui");
const result = await client.predict("/process_file", {
  auth: "", files: exampleFile,
  to_formats: ["json", "md"], image_export_mode: "embedded",
  pipeline: "standard", ocr: true, force_ocr: false, ocr_engine: "auto",
  ocr_lang: "en,fr,de,es", pdf_backend: "docling_parse", table_mode: "accurate",
  abort_on_error: false, return_as_file: false,
  do_code_enrichment: false, do_formula_enrichment: false,
  do_picture_classification: false, do_picture_description: false,
});
// 返回 task_id，再调 /wait_task_finish 拿结果
```
> 这只适合简单前端直连场景；本系统的批量编排、数据库、LLM 后处理、导出等能力都依赖我们自己的后端 REST 对接，不走这条路径。

---

## 6. 已知坑（已修复，记录在案）

| 坑 | 错误写法 | 正确写法 |
|----|----------|----------|
| 上传字段名 | `file`（单数） | `files`（复数） |
| to_formats 格式 | `to_formats='["md","json"]'`（JSON 串） | 重复字段 `to_formats=md` |
| 结果提取 | `data["md_content"]` | `data["document"]["md_content"]` |
| 轮询状态字段 | `data["status"]` | `data["task_status"]` |
| 部分成功 | 未处理 `partial_success` | 视为成功取结果 |
| 健康检查端点 | `/v1/health` | `/health` |
| httpx 异步上传 | `files={"f": open(...)}` 同步文件对象 | 先 `read()` 成 bytes 再传 |
