"""Mongo persistence for assignments and approvals. Imported only on the live path."""
from __future__ import annotations

from typing import Any, Optional

from deps import db


class MongoAssignmentStore:
    async def insert_assignment(self, doc: dict[str, Any]) -> None:
        await db.assignments.insert_one(dict(doc))

    async def replace_assignment(self, doc: dict[str, Any]) -> None:
        clean = {k: v for k, v in doc.items() if k != "_id"}
        await db.assignments.replace_one(
            {"assignment_id": clean["assignment_id"], "user_id": clean["user_id"]},
            clean,
        )

    async def get_assignment(self, user_id: str, assignment_id: str) -> Optional[dict[str, Any]]:
        return await db.assignments.find_one(
            {"assignment_id": assignment_id, "user_id": user_id},
            {"_id": 0},
        )

    async def list_assignments(self, user_id: str) -> list[dict[str, Any]]:
        cursor = (
            db.assignments.find({"user_id": user_id}, {"_id": 0})
            .sort("updated_at", -1)
            .limit(50)
        )
        return await cursor.to_list(length=50)

    async def insert_approval(self, doc: dict[str, Any]) -> None:
        await db.approvals.insert_one(dict(doc))

    async def replace_approval(self, doc: dict[str, Any]) -> None:
        clean = {k: v for k, v in doc.items() if k != "_id"}
        await db.approvals.replace_one(
            {"approval_id": clean["approval_id"], "user_id": clean["user_id"]},
            clean,
        )

    async def get_approval(self, user_id: str, approval_id: str) -> Optional[dict[str, Any]]:
        return await db.approvals.find_one(
            {"approval_id": approval_id, "user_id": user_id},
            {"_id": 0},
        )

    async def list_approvals(
        self,
        user_id: str,
        *,
        status: Optional[str] = None,
        assignment_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"user_id": user_id}
        if status:
            query["status"] = status
        if assignment_id:
            query["assignment_id"] = assignment_id
        cursor = db.approvals.find(query, {"_id": 0}).sort("created_at", 1).limit(50)
        return await cursor.to_list(length=50)
