"""Mongo persistence for connectors. Imported only on the live path."""
from __future__ import annotations

from typing import Any, Optional

from deps import db


class MongoConnectorStore:
    async def list_connectors(self, user_id: str) -> list[dict[str, Any]]:
        cursor = db.connectors.find({"user_id": user_id}, {"_id": 0}).sort("created_at", 1)
        return await cursor.to_list(length=20)

    async def get_connector(self, user_id: str, provider: str) -> Optional[dict[str, Any]]:
        return await db.connectors.find_one(
            {"user_id": user_id, "provider": provider},
            {"_id": 0},
        )

    async def upsert_connector(self, doc: dict[str, Any]) -> None:
        clean = {k: v for k, v in doc.items() if k != "_id"}
        await db.connectors.replace_one(
            {"user_id": clean["user_id"], "provider": clean["provider"]},
            clean,
            upsert=True,
        )

    async def delete_connector(self, user_id: str, provider: str) -> bool:
        result = await db.connectors.delete_one({"user_id": user_id, "provider": provider})
        return result.deleted_count > 0
