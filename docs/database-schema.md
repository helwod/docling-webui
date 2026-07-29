# Docling Serve WebUI - 数据库设计

## 1. ER 图

```
┌─────────────────────┐         ┌──────────────────────────────┐
│      batches        │         │            files              │
├─────────────────────┤         ├──────────────────────────────┤
│ id (PK)      TEXT   │───┐     │ id (PK)              TEXT    │
│ name         TEXT   │   │     │ batch_id (FK)        TEXT    │
│ source_type  TEXT   │   └────>│ original_filename    TEXT    │
│ status       TEXT   │         │ stored_path          TEXT    │
│ total_files  INT    │         │ file_size            INT     │
│ processed    INT    │         │ file_type            TEXT    │
│ created_at   TEXT   │         │                              │
│ updated_at   TEXT   │         │ -- OCR fields --             │
│ deleted_at   TEXT   │         │ ocr_status           TEXT    │
└─────────────────────┘         │ ocr_task_id          TEXT    │
                                │ ocr_md_content       TEXT    │
                                │ ocr_json_content     TEXT    │
                                │ ocr_html_content     TEXT    │
                                │ ocr_processing_time  REAL    │
                                │ ocr_error            TEXT    │
                                │                              │
                                │ -- LLM fields --             │
                                │ llm_status           TEXT    │
                                │ llm_result           TEXT    │
                                │ llm_model            TEXT    │
                                │ llm_error            TEXT    │
                                │                              │
                                │ created_at           TEXT    │
                                │ updated_at           TEXT    │
                                └──────────────────────────────┘

┌─────────────────────┐
│      settings       │
├─────────────────────┤
│ key (PK)     TEXT   │
│ value        TEXT   │
│ updated_at   TEXT   │
└─────────────────────┘
```

## 2. 表结构定义

### 2.1 batches（批次表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PRIMARY KEY | UUID |
| name | TEXT | NOT NULL | 批次名称（ZIP 文件名或用户自定义） |
| source_type | TEXT | NOT NULL, CHECK | 上传来源：'zip' 或 'files' |
| status | TEXT | NOT NULL, DEFAULT 'created' | created / processing / completed / failed |
| total_files | INTEGER | DEFAULT 0 | 批次内文件总数 |
| processed_files | INTEGER | DEFAULT 0 | 已处理文件数 |
| created_at | TEXT | NOT NULL, DEFAULT now | 创建时间（ISO 8601） |
| updated_at | TEXT | NOT NULL, DEFAULT now | 更新时间（ISO 8601） |
| deleted_at | TEXT | NULL | 软删除时间 |

### 2.2 files（文件表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PRIMARY KEY | UUID |
| batch_id | TEXT | NOT NULL, FK -> batches.id | 所属批次 |
| original_filename | TEXT | NOT NULL | 原始文件名 |
| stored_path | TEXT | NOT NULL | 服务器存储路径 |
| file_size | INTEGER | NOT NULL | 文件大小（字节） |
| file_type | TEXT | NOT NULL | MIME 类型 |
| ocr_status | TEXT | DEFAULT 'pending' | pending / processing / completed / failed |
| ocr_task_id | TEXT | NULL | Docling Serve 任务 ID |
| ocr_md_content | TEXT | NULL | OCR Markdown 结果 |
| ocr_json_content | TEXT | NULL | OCR JSON 结果（序列化存储） |
| ocr_html_content | TEXT | NULL | OCR HTML 结果 |
| ocr_processing_time | REAL | NULL | OCR 处理耗时（秒） |
| ocr_error | TEXT | NULL | OCR 错误信息 |
| llm_status | TEXT | DEFAULT 'pending' | pending / processing / completed / failed / skipped |
| llm_result | TEXT | NULL | LLM 提取的表格数据（JSON 序列化） |
| llm_model | TEXT | NULL | 使用的 LLM 模型名称 |
| llm_error | TEXT | NULL | LLM 错误信息 |
| created_at | TEXT | NOT NULL, DEFAULT now | 创建时间 |
| updated_at | TEXT | NOT NULL, DEFAULT now | 更新时间 |

### 2.3 settings（系统配置表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| key | TEXT | PRIMARY KEY | 配置键名 |
| value | TEXT | NOT NULL | 配置值（JSON 序列化） |
| updated_at | TEXT | NOT NULL, DEFAULT now | 更新时间 |

## 3. 索引清单

| 索引名 | 表 | 字段 | 类型 | 说明 |
|--------|------|------|------|------|
| idx_files_batch_id | files | batch_id | B-tree | 按批次查询文件 |
| idx_files_ocr_status | files | ocr_status | B-tree | 查询待处理/失败文件 |
| idx_files_llm_status | files | llm_status | B-tree | 查询待处理/失败文件 |
| idx_batches_status | batches | status | B-tree | 按状态筛选批次 |
| idx_batches_created_at | batches | created_at | B-tree | 按时间排序批次列表 |

## 4. DDL 语句

```sql
-- Enable WAL mode for better concurrent read performance
PRAGMA journal_mode=WAL;

-- batches table
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('zip', 'files')),
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'processing', 'completed', 'failed')),
    total_files INTEGER NOT NULL DEFAULT 0,
    processed_files INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);

-- files table
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    file_type TEXT NOT NULL,

    -- OCR fields
    ocr_status TEXT NOT NULL DEFAULT 'pending' CHECK (ocr_status IN ('pending', 'processing', 'completed', 'failed')),
    ocr_task_id TEXT,
    ocr_md_content TEXT,
    ocr_json_content TEXT,
    ocr_html_content TEXT,
    ocr_processing_time REAL,
    ocr_error TEXT,

    -- LLM fields
    llm_status TEXT NOT NULL DEFAULT 'pending' CHECK (llm_status IN ('pending', 'processing', 'completed', 'failed', 'skipped')),
    llm_result TEXT,
    llm_model TEXT,
    llm_error TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE
);

-- settings table
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_files_batch_id ON files(batch_id);
CREATE INDEX IF NOT EXISTS idx_files_ocr_status ON files(ocr_status);
CREATE INDEX IF NOT EXISTS idx_files_llm_status ON files(llm_status);
CREATE INDEX IF NOT EXISTS idx_batches_status ON batches(status);
CREATE INDEX IF NOT EXISTS idx_batches_created_at ON batches(created_at);

-- Trigger: auto-update updated_at
CREATE TRIGGER IF NOT EXISTS trg_batches_updated_at
    AFTER UPDATE ON batches
    FOR EACH ROW
BEGIN
    UPDATE batches SET updated_at = datetime('now') WHERE id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_files_updated_at
    AFTER UPDATE ON files
    FOR EACH ROW
BEGIN
    UPDATE files SET updated_at = datetime('now') WHERE id = OLD.id;
END;
```

## 5. 初始配置数据

```sql
INSERT INTO settings (key, value) VALUES
    ('docling_base_url', 'http://localhost:5001'),
    ('llm_model', 'gpt-4o-mini'),
    ('llm_base_url', 'https://api.openai.com/v1'),
    ('docling_ocr_engine', 'rapidocr'),
    ('docling_table_mode', 'accurate'),
    ('docling_image_export_mode', 'referenced'),
    ('max_concurrent_conversions', '5'),
    ('poll_interval_seconds', '2');
```
