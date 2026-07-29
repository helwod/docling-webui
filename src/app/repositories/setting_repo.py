import aiosqlite
from datetime import datetime, timezone
from typing import Optional


class SettingRepo:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get(self, key: str) -> Optional[str]:
        cursor = await self.db.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def set(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (key, value, now),
        )
        await self.db.commit()

    async def get_all(self) -> dict:
        cursor = await self.db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}

    async def get_multi(self, keys: list[str]) -> dict:
        placeholders = ",".join("?" for _ in keys)
        cursor = await self.db.execute(
            f"SELECT key, value FROM settings WHERE key IN ({placeholders})",
            keys,
        )
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}
