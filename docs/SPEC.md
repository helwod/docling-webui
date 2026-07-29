# Spec - Docling Serve WebUI v1.0

> 生成日期：2026-07-22
> 基于：PRD v1.0 + 架构文档 v1.0 + UIUX 文档 v1.0
> 状态：已确认

---

## 1. 产品定义

- **一句话描述**：Docling Serve 服务的 WebUI，实现批量图片 OCR 并对接语言大模型，整理表格数据并支持导出。
- **目标用户**：企业数据分析/财务/运营专员（无代码背景），以及已部署 Docling Serve 的开发/IT人员。
- **核心问题**：企业用户需要从大量扫描图片批量提取表格数据，现有工具要么手动录入低效，要么 OCR 不理解表格结构，要么不支持批量处理和合并导出。

## 2. MVP 范围（锁定——不在此列表的功能一律不做）

| 优先级 | 功能 | 验收标准摘要 | RICE 评分 |
|--------|------|-------------|-----------|
| P0 | 图片上传与 ZIP 批量解压 | 支持单张/多张/ZIP 包上传，自动解压后列出图片 | 10.0 |
| P0 | Docling Serve API 对接 | 异步提交 + 轮询状态，支持 do_ocr、table_mode=accurate | 10.0 |
| P0 | 任务列表与状态追踪 | 实时显示状态（排队/OCR中/LLM中/完成/失败） | 10.0 |
| P0 | 结果导出（ZIP 含原图+解析结果） | 导出为 ZIP，包含 original_images + ocr_results + llm_tables | 10.0 |
| P0 | 单张图片预览与结果对比 | 左右分栏查看原图和解析结果 | 8.0 |
| P0 | LLM 表格后处理 | OpenAI 兼容 API 整理表格数据，JSON mode + temperature=0 | 6.0 |

## 3. 明确不做（Out-of-Scope — 锁定）

| 不做的功能 | 原因 | 何时考虑 |
|------------|------|----------|
| OCR/表格模式配置(fast/accurate切换) | MVP 阶段固定 accurate 即可 | 用户反馈 need |
| LLM 自定义提示词配置界面 | MVP 阶段固定 prompt | 用户反馈 need |
| 解析历史记录与搜索 | MVP 阶段任务列表足够 | v1.1 |
| 多用户任务隔离 | 个人/内部工具，单用户 | v2.0 |
| 批量 PDF 处理 | MVP 聚焦图片格式 | v1.1 |
| 结果在线编辑与修正 | MVP 阶段只需导出后处理 | v2.0 |
| 用户登录认证 | 内部工具，部署即用 | 需要时再添加 |

## 4. 技术架构（锁定 — 含版本锚定）

| 层 | 技术 | 锁定版本 | 锁定原因 |
|----|------|----------|----------|
| 前端框架 | React | ^18.3 | 内部工具 SPA，无 SEO 需求 |
| 构建工具 | Vite | ^5.4 | esbuild 极快构建 |
| CSS | Tailwind CSS | ^3.4 | 原子化 CSS，shadcn/ui 原生集成 |
| UI 组件 | shadcn/ui | latest | 代码可控，Radix UI 无障碍支持 |
| 图标库 | Lucide React | ^0.400 | 1700+ 图标，ISC 许可，shadcn/ui 默认 |
| 状态管理 | Zustand | ^4.5 | 轻量客户端状态 |
| 数据获取 | TanStack Query | ^5.51 | 服务端状态 + 轮询 |
| 后端框架 | FastAPI | ^0.111 | 原生 async + OpenAPI 自动生成 |
| ASGI 服务器 | uvicorn[standard] | ^0.30 | FastAPI 标准 |
| ORM/数据库 | aiosqlite + SQLite WAL | - | 零配置个人工具 |
| LLM SDK | openai | ^1.35 | OpenAI 兼容 API |
| HTTP 客户端 | httpx | ^0.27 | 异步 HTTP 调用 Docling/LLM |
| 文件上传 | python-multipart | ^0.0.9 | FastAPI 上传支持 |
| 部署 | Docker Compose | - | 一键启动前后端 |

## 5. API 端点清单（锁定——开发时以此为唯一依据）

| Method | Path | 功能 | 认证 | 请求体 | 响应体 |
|--------|------|------|------|--------|--------|
| POST | /api/v1/batches | 上传文件/ZIP创建批次 | 无 | multipart/form-data files | {batch_id, files[], status} |
| GET | /api/v1/batches | 批次列表 | 无 | query: page, limit | {batches[], total, page} |
| GET | /api/v1/batches/:id | 批次详情 | 无 | - | {batch detail} |
| DELETE | /api/v1/batches/:id | 删除批次 | 无 | - | {success} |
| GET | /api/v1/batches/:id/files | 批次内文件列表 | 无 | - | {files[]} |
| GET | /api/v1/batches/:id/files/:fid | 文件详情 | 无 | - | {file detail with OCR + LLM} |
| POST | /api/v1/batches/:id/process | 触发 OCR+LLM 处理 | 无 | - | {task_id, status} |
| GET | /api/v1/batches/:id/status | 获取处理进度 | 无 | - | {status, progress} |
| POST | /api/v1/files/:fid/llm | 重新运行 LLM | 无 | - | {task_id} |
| GET | /api/v1/files/:fid/llm | 获取 LLM 结果 | 无 | - | {llm_result} |
| GET | /api/v1/batches/:id/export | 导出整批 ZIP | 无 | - | ZIP binary |
| GET | /api/v1/files/:fid/export | 导出单文件 ZIP | 无 | - | ZIP binary |
| GET | /api/v1/files/:fid/image | 获取原图 | 无 | - | image binary |
| GET | /api/v1/config | 获取系统配置 | 无 | - | {docling_url, llm_model} |
| PUT | /api/v1/config | 更新系统配置 | 无 | {config} | {success} |

## 6. 数据库表清单（锁定）

| 表名 | 核心字段 | 索引 | 关联 |
|------|----------|------|------|
| batches | id(UUID PK), name, source_type, status, total_files, processed_files, created_at, updated_at | idx_batches_status, idx_batches_created_at | - |
| files | id(UUID PK), batch_id(FK), original_filename, stored_path, file_type, file_size, ocr_status, ocr_md_content, ocr_json_content, ocr_html_content, llm_status, llm_result, llm_model, created_at, updated_at | idx_files_batch_id, idx_files_status, idx_files_ocr_status | batches.id |
| settings | key(TEXT PK), value(TEXT), updated_at | sqlite auto PK | - |

## 7. 页面清单（锁定）

| 页面 | 路由 | 核心组件 | 对应 API | 设计 Token 主题 |
|------|------|----------|----------|-----------------|
| 上传页 | /upload | DragDropZone, FilePreview, StartButton | POST /batches | upload (design-system/pages/upload.md) |
| 任务列表页 | /tasks | TaskTable, StatusBadge, ActionButtons | GET /batches, GET /batches/:id/status | tasks (design-system/pages/tasks.md) |
| 任务详情页 | /tasks/:id | ImageViewer, ResultPanel, LLMTable | GET /batches/:id, GET batches/:id/files/:fid | master |
| 设置页 | /settings | ConfigForm, ConnectionTest | GET /config, PUT /config | master |

## 8. 设计 Token（锁定）

- **主题**：深色优先（Dark-first），默认为深色
- **主色**：--accent: #2563EB (Blue 600)
- **语义色**：--success: #3FB950, --warn: #D29922, --danger: #F85149
- **字体**：Inter + Noto Sans SC 显示/正文，JetBrains Mono 等宽
- **图标库**：Lucide React（锁定一套，不混用）
- **图标尺寸**：16px（行内）/ 20px（按钮内）/ 24px（独立图标）
- **圆角**：sm(6px) / md(8px) / lg(12px) / xl(16px)
- **间距**：4px 网格（4/8/12/16/20/24/32/40/48/64/80）
- **对标品牌**：Linear / Vercel / GitHub
- **完整 Token**：在 `docs/DESIGN.md` 和 `docs/design-system/` 中定义

## 9. 验收标准（锁定——QA 测试时以此为唯一依据）

| 编号 | 功能 | 验收标准 | 优先级 |
|------|------|----------|--------|
| AC-01 | 上传 | 用户选择单张/多张图片(ZIP)，系统显示文件列表和缩略图 | P0 |
| AC-02 | 上传 | 用户上传 ZIP，系统自动解压并列出有效图片文件 | P0 |
| AC-03 | 上传 | ZIP 无有效图片时显示错误提示 | P0 |
| AC-04 | 解析 | 用户点击"开始解析"，系统调用 Docling 进行异步转换 | P0 |
| AC-05 | 解析 | 解析过程中任务列表实时更新状态（排队/OCR中/LLM中/完成/失败） | P0 |
| AC-06 | 解析 | Docling 服务不可达时显示错误并标记任务失败 | P0 |
| AC-07 | 解析 | 图片无表格时跳过 LLM 步骤，保存文本结果 | P0 |
| AC-08 | 解析 | LLM API 不可用时保留原始 OCR 结果，允许跳过 LLM | P0 |
| AC-09 | 查看 | 用户点击任务可查看左右分栏：原图 vs 解析结果 | P0 |
| AC-10 | 查看 | 表格结果以结构化格式渲染显示 | P0 |
| AC-11 | 导出 | 单文件导出 ZIP 包含 original_images + ocr_results + llm_tables | P0 |
| AC-12 | 导出 | 整批导出 ZIP 按文件分文件夹打包 | P0 |
| AC-13 | 空状态 | 无任务时显示引导提示和上传按钮 | P0 |
| AC-14 | 设置 | 用户可在设置页配置 Docling 地址和 LLM 参数 | P1 |
| AC-15 | 设置 | 配置修改后立即生效，无需重启 | P1 |

## 10. 边界与约束

- 单文件大小限制：50MB
- ZIP 文件大小限制：200MB
- 单批次最大文件数：500
- ZIP 解压安全：zip bomb 防护（压缩比 < 100:1）、路径遍历检查
- 支持文件类型：PNG, JPG, JPEG, TIFF, BMP, GIF, WEBP
- Docling 轮询间隔：2 秒
- Docling 轮询超时：10 分钟
- LLM 请求超时：60 秒
- Docling 并发上限：5（asyncio.Semaphore）
- 前端兼容：Chrome/Safari/Firefox 最新 2 个版本
- 移动端兼容：响应式布局，最低 iPhone SE

## 11. 内嵌已知坑

| 坑 | 技术栈指纹 | 根因 | 修法 |
|----|------------|------|------|
| FastAPI 文件上传超时 | fastapi, python-multipart | 大文件上传默认超时短 | 增大 uvicorn timeout_keep_alive 和默认超时配置 |
| CSV 中文乱码 | export, csv | Excel 打开 UTF-8 CSV 乱码 | 导出 CSV 时写入 UTF-8 BOM (\ufeff) |
| SQLite 并发写冲突 | sqlite, aiosqlite | 多协程同时写 SQLite | 使用 WAL 模式 + aiosqlite 的事务重试机制 |
| Vite proxy CORS | vite, react | 前后端分离部署时跨域 | 开发环境用 Vite proxy，生产用 nginx 反向代理 |

## 12. 端到端验证步骤

```bash
# 1. 构建后端
cd backend
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 设置 LLM_API_KEY 和 DOCLING_BASE_URL

# 2. 启动后端
uvicorn app.main:app --reload --port 8000
# 等待 "Uvicorn running on http://127.0.0.1:8000"

# 3. 构建前端
cd ../frontend
npm install
npm run dev
# 等待 "VITE ready on http://localhost:5173"

# 4. 访问
# 浏览器打开 http://localhost:5173

# 5. 核心成功流
# 5a. 上传一张测试图片（含表格的截图）
# 5b. 点击"开始解析"
# 5c. 查看任务列表，等待状态变为"已完成"
# 5d. 点击任务查看左右分栏结果
# 5e. 点击导出，下载 ZIP
# 5f. 解压 ZIP，验证包含 original_images/ ocr_results/ llm_tables/

# 6. 关键错误流
# 6a. 停止 Docling Serve 服务
# 6b. 上传图片并尝试解析
# 6c. 断言：显示"Docling Serve 连接失败"错误提示
# 6d. 重新启动 Docling Serve
# 6e. 重试：成功解析
```

## 13. 变更记录

| 日期 | 变更内容 | 原因 | 影响范围 |
|------|----------|------|----------|
| 2026-07-22 | 初始创建 | 基于已确认的三文档生成 | 全局 |
