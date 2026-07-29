import aiosqlite
import uuid
from datetime import datetime, timezone
from typing import Optional


class BatchRepo:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def create(self, name: str, source_type: str, enable_llm: int = 1) -> dict:
        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            """INSERT INTO batches (id, name, source_type, status, total_files,
               processed_files, enable_llm, created_at, updated_at)
               VALUES (?, ?, ?, 'created', 0, 0, ?, ?, ?)""",
            (batch_id, name, source_type, 1 if enable_llm else 0, now, now),
        )
        await self.db.commit()
        return await self.get_by_id(batch_id)

    async def get_by_id(self, batch_id: str) -> Optional[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM batches WHERE id = ? AND deleted_at IS NULL",
            (batch_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list(
        self, page: int = 1, limit: int = 20, status: Optional[str] = None
    ) -> tuple[list[dict], int]:
        offset = (page - 1) * limit
        conditions = ["deleted_at IS NULL"]
        params = []
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " AND ".join(conditions)
        count_sql = f"SELECT COUNT(*) FROM batches WHERE {where}"
        cursor = await self.db.execute(count_sql, params)
        total_row = await cursor.fetchone()
        total = total_row[0] if total_row else 0

        data_sql = (
            f"SELECT * FROM batches WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )
        cursor = await self.db.execute(data_sql, params + [limit, offset])
        rows = await cursor.fetchall()
        batches = [dict(r) for r in rows]
        return batches, total

    async def update_status(self, batch_id: str, status: str) -> None:
        await self.db.execute(
            "UPDATE batches SET status = ? WHERE id = ?",
            (status, batch_id),
        )
        await self.db.commit()

    async def update_processed_count(self, batch_id: str) -> None:
        """将 processed_files 设为已处理（OCR 完成或失败）的绝对数量。

        重跑时仅重跑失败/未处理的文件，用绝对计数可避免重复累加导致进度条超 100%。
        """
        await self.db.execute(
            "UPDATE batches SET processed_files = ("
            "SELECT COUNT(*) FROM files WHERE batch_id = ? "
            "AND ocr_status IN ('completed', 'failed')) WHERE id = ?",
            (batch_id, batch_id),
        )
        await self.db.commit()

    async def update_batch_table(self, batch_id: str, table_json: Optional[str]) -> None:
        await self.db.execute(
            "UPDATE batches SET batch_table = ? WHERE id = ?",
            (table_json, batch_id),
        )
        await self.db.commit()

    async def get_batches_by_status(self, status: str) -> list:
        """获取指定状态的所有批次，用于启动恢复。"""
        cursor = await self.db.execute(
            "SELECT * FROM batches WHERE status = ? ORDER BY created_at ASC",
            (status,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_next_queued(self, limit: int) -> list:
        """取队列中下一批待处理批次：未暂停的 created，置顶优先，其次先入队先处理。"""
        cursor = await self.db.execute(
            """SELECT * FROM batches
               WHERE status = 'created' AND COALESCE(paused, 0) = 0 AND deleted_at IS NULL
               ORDER BY COALESCE(priority, 0) DESC, created_at ASC
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def soft_delete(self, batch_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE batches SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (now, batch_id),
        )
        await self.db.commit()
