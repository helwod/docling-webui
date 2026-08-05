import aiosqlite
from pathlib import Path
from app.config import settings

DB_PATH = settings.database_path

_db: aiosqlite.Connection = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        db_dir = Path(DB_PATH).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _init_tables()
    return _db


async def close_db():
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def _init_tables():
    db = _db
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS batches (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK (source_type IN ('zip', 'files')),
            status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'processing', 'completed', 'failed')),
            total_files INTEGER NOT NULL DEFAULT 0,
            processed_files INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at TEXT,
            table_prompt TEXT,
            table_reply TEXT
        );

        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_type TEXT NOT NULL,
            ocr_status TEXT NOT NULL DEFAULT 'pending' CHECK (ocr_status IN ('pending', 'processing', 'completed', 'failed')),
            ocr_task_id TEXT,
            ocr_md_content TEXT,
            ocr_json_content TEXT,
            ocr_html_content TEXT,
            ocr_processing_time REAL,
            ocr_error TEXT,
            llm_status TEXT NOT NULL DEFAULT 'pending' CHECK (llm_status IN ('pending', 'processing', 'completed', 'failed', 'skipped')),
            llm_result TEXT,
            llm_model TEXT,
            llm_error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS batch_chats (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_batch_chats_batch_id_seq ON batch_chats(batch_id, seq);

        CREATE INDEX IF NOT EXISTS idx_files_batch_id ON files(batch_id);
        CREATE INDEX IF NOT EXISTS idx_files_ocr_status ON files(ocr_status);
        CREATE INDEX IF NOT EXISTS idx_files_llm_status ON files(llm_status);
        CREATE INDEX IF NOT EXISTS idx_batches_status ON batches(status);
        CREATE INDEX IF NOT EXISTS idx_batches_created_at ON batches(created_at);

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
    """)

    # Migration: add batch_table column if an older schema exists
    try:
        cursor = await db.execute("PRAGMA table_info(batches)")
        cols = {row[1] for row in await cursor.fetchall()}
        if "batch_table" not in cols:
            await db.execute("ALTER TABLE batches ADD COLUMN batch_table TEXT")
        if "paused" not in cols:
            await db.execute("ALTER TABLE batches ADD COLUMN paused INTEGER NOT NULL DEFAULT 0")
        if "priority" not in cols:
            await db.execute("ALTER TABLE batches ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
        if "enable_llm" not in cols:
            await db.execute("ALTER TABLE batches ADD COLUMN enable_llm INTEGER NOT NULL DEFAULT 1")
        if "table_prompt" not in cols:
            await db.execute("ALTER TABLE batches ADD COLUMN table_prompt TEXT")
        if "table_reply" not in cols:
            await db.execute("ALTER TABLE batches ADD COLUMN table_reply TEXT")
    except Exception:
        pass

    # Migration: 会话表从「单文件」升级为「批次汇总表」层级
    try:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='file_chats'"
        )
        if await cursor.fetchone():
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS batch_chats (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            # 把旧的单文件会话按 files.batch_id 映射回所属批次
            await db.execute(
                """
                INSERT INTO batch_chats (id, batch_id, seq, role, content, created_at)
                SELECT fc.id, f.batch_id, fc.seq, fc.role, fc.content, fc.created_at
                FROM file_chats fc
                JOIN files f ON f.id = fc.file_id
                """
            )
            await db.execute("DROP TABLE file_chats")
    except Exception:
        pass

    await _insert_default_settings(db)
    await db.commit()


async def _insert_default_settings(db: aiosqlite.Connection):
    defaults = [
        ("docling_base_url", settings.docling_base_url),
        ("llm_model", settings.llm_model),
        ("llm_base_url", settings.llm_base_url),
        ("docling_ocr_engine", "rapidocr"),
        ("docling_table_mode", "accurate"),
        ("docling_image_export_mode", "referenced"),
        ("max_concurrent_conversions", "5"),
        ("poll_interval_seconds", "2"),
    ]
    for key, value in defaults:
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
