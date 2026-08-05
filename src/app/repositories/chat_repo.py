import aiosqlite
import uuid


class ChatRepo:
    """每个批次（汇总表）的多轮 LLM 会话存储。

    设计：按 batch_id + seq 顺序保存消息。seq 单调递增（不重用），
    编辑/重新生成时通过「截断到某个 seq 之前」实现分支回退，
    而不是覆盖旧消息，避免并发写入导致 seq 错乱。
    """

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def _max_seq(self, batch_id: str) -> int:
        cursor = await self.db.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM batch_chats WHERE batch_id = ?",
            (batch_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_history(self, batch_id: str) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT seq, role, content FROM batch_chats WHERE batch_id = ? ORDER BY seq ASC",
            (batch_id,),
        )
        rows = await cursor.fetchall()
        return [{"seq": r["seq"], "role": r["role"], "content": r["content"]} for r in rows]

    async def add_message(self, batch_id: str, role: str, content: str) -> dict:
        seq = await self._max_seq(batch_id) + 1
        msg_id = str(uuid.uuid4())
        await self.db.execute(
            """INSERT INTO batch_chats (id, batch_id, seq, role, content, created_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (msg_id, batch_id, seq, role, content),
        )
        await self.db.commit()
        return {"seq": seq, "role": role, "content": content}

    async def add_messages(self, batch_id: str, messages: list[dict]) -> list[dict]:
        """批量追加（user + assistant 成对），保持 seq 连续递增。"""
        saved = []
        for m in messages:
            saved.append(await self.add_message(batch_id, m["role"], m["content"]))
        return saved

    async def truncate_after(self, batch_id: str, seq: int) -> None:
        """删除 seq 严格大于该值的全部消息（用于编辑/重新生成回退）。"""
        await self.db.execute(
            "DELETE FROM batch_chats WHERE batch_id = ? AND seq > ?",
            (batch_id, seq),
        )
        await self.db.commit()

    async def clear(self, batch_id: str) -> None:
        await self.db.execute("DELETE FROM batch_chats WHERE batch_id = ?", (batch_id,))
        await self.db.commit()
