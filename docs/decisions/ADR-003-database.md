# ADR-003: 使用 SQLite (WAL 模式) 作为数据库

## Status: Accepted (2026-07-22)

## Background

Docling Serve WebUI 是个人/内部工具，单用户使用。数据存储需求：
- 批次元数据（名称、状态、文件数）
- 文件元数据（文件名、路径、MIME 类型）
- OCR 结果（Markdown、JSON、HTML 内容）
- LLM 提取结果（表格 JSON）
- 系统配置（Docling URL、LLM 模型等）

写入场景：上传文件时创建记录、OCR/LLM 完成时更新记录。
读取场景：列表查询、详情查看、状态轮询。

## Decision

选择 **SQLite (WAL 模式)** 作为数据库。

配置：
- `PRAGMA journal_mode=WAL` (读写不互相阻塞)
- `PRAGMA foreign_keys=ON` (启用外键约束)
- 数据库文件路径通过环境变量 `DATABASE_PATH` 配置
- 使用 aiosqlite 异步驱动

## Consequences

### 正面后果
- 零配置、零维护，无需安装数据库服务
- 备份只需复制 .db 文件
- 单文件部署，降低运维复杂度
- WAL 模式下读写不互相阻塞，满足轮询场景的并发读需求
- 无网络开销，查询延迟极低
- 数据库与应用同进程，无连接池管理开销

### 负面后果
- 单写者限制（本场景写并发极低，不影响）
- 无内置复制/高可用（内部工具不需要）
- 无用户权限系统（内部工具不需要）
- 大量数据时 VACUUM 较慢（MVP 阶段数据量可控）

## Related ADRs
- ADR-002 (后端框架)
