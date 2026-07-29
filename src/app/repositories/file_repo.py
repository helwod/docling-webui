import aiosqlite
import uuid
from datetime import datetime, timezone
from typing import Optional


class FileRepo:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def create(
        self,
        batch_id: str,
        original_filename: str,
        stored_path: str,
        file_size: int,
        file_type: str,
    ) -> dict:
        file_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            """INSERT INTO files (id, batch_id, original_filename, stored_path,
               file_size, file_type, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_id, batch_id, original_filename, stored_path,
             file_size, file_type, now, now),
        )
        await self.db.commit()
        return await self.get_by_id(file_id)

    async def get_by_id(self, file_id: str) -> Optional[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM files WHERE id = ?",
            (file_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_by_batch(
        self, batch_id: str, page: int = 1, limit: int = 20
    ) -> tuple[list[dict], int]:
        offset = (page - 1) * limit
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM files WHERE batch_id = ?",
            (batch_id,),
        )
        total_row = await cursor.fetchone()
        total = total_row[0] if total_row else 0

        cursor = await self.db.execute(
            """SELECT id, original_filename, file_size, file_type, ocr_status,
               llm_status, created_at FROM files WHERE batch_id = ?
               ORDER BY created_at ASC LIMIT ? OFFSET ?""",
            (batch_id, limit, offset),
        )
        rows = await cursor.fetchall()
        files = [dict(r) for r in rows]
        return files, total

    async def update_ocr_status(
        self, file_id: str, status: str, **kwargs
    ) -> None:
        fields = ["ocr_status = ?"]
        values = [status]
        for key, val in kwargs.items():
            if key in ("ocr_task_id", "ocr_md_content", "ocr_json_content",
                       "ocr_html_content", "ocr_processing_time", "ocr_error"):
                fields.append(f"{key} = ?")
                values.append(val)
        values.append(file_id)
        await self.db.execute(
            f"UPDATE files SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        await self.db.commit()

    async def update_llm_status(
        self, file_id: str, status: str, **kwargs
    ) -> None:
        fields = ["llm_status = ?"]
        values = [status]
        for key, val in kwargs.items():
            if key in ("llm_result", "llm_model", "llm_error"):
                fields.append(f"{key} = ?")
                values.append(val)
        values.append(file_id)
        await self.db.execute(
            f"UPDATE files SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        await self.db.commit()

    async def get_pending_ocr_files(self, batch_id: str) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM files WHERE batch_id = ? AND ocr_status = 'pending'",
            (batch_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_failed_llm_files(self, batch_id: str) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM files WHERE batch_id = ? AND llm_status IN ('pending', 'failed')",
            (batch_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_failed_ocr_files(self, batch_id: str) -> list[dict]:
        """获取 OCR 失败或待处理的文件，用于重新识别。"""
        cursor = await self.db.execute(
            "SELECT * FROM files WHERE batch_id = ? AND ocr_status IN ('failed', 'pending')",
            (batch_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def reset_ocr_status(self, file_id: str) -> None:
        """将文件的 OCR 状态重置为 pending 以便重新识别。"""
        await self.db.execute(
            "UPDATE files SET ocr_status = 'pending', ocr_error = NULL WHERE id = ?",
            (file_id,),
        )
        await self.db.commit()

    async def get_status_counts(self, batch_id: str) -> dict:
        cursor = await self.db.execute(
            """SELECT
               COUNT(*) as total,
               SUM(CASE WHEN ocr_status = 'completed' THEN 1 ELSE 0 END) as ocr_completed,
               SUM(CASE WHEN ocr_status = 'failed' THEN 1 ELSE 0 END) as ocr_failed,
               SUM(CASE WHEN ocr_status IN ('pending', 'processing') THEN 1 ELSE 0 END) as ocr_pending,
               SUM(CASE WHEN llm_status = 'completed' THEN 1 ELSE 0 END) as llm_completed,
               SUM(CASE WHEN llm_status = 'failed' THEN 1 ELSE 0 END) as llm_failed,
               SUM(CASE WHEN llm_status IN ('pending', 'processing') THEN 1 ELSE 0 END) as llm_pending
               FROM files WHERE batch_id = ?""",
            (batch_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return {}
        keys = ["total", "ocr_completed", "ocr_failed", "ocr_pending",
                "llm_completed", "llm_failed", "llm_pending"]
        return {k: (row[i] or 0) for i, k in enumerate(keys)}

    async def count_by_batch(self, batch_id: str) -> int:
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM files WHERE batch_id = ?",
            (batch_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_all_for_consolidated(self, batch_id: str) -> list[dict]:
        """取批次全部文件用于生成汇总表：id/文件名/OCR状态/OCR正文，按上传顺序。"""
        cursor = await self.db.execute(
            """SELECT id, original_filename, ocr_status, ocr_md_content
               FROM files WHERE batch_id = ? ORDER BY created_at ASC""",
            (batch_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def delete_by_batch(self, batch_id: str) -> None:
        await self.db.execute(
            "DELETE FROM files WHERE batch_id = ?",
            (batch_id,),
        )
        await self.db.commit()
