"""Background research. The loop stays up until the process stops. Missions pause only when the owner says so."""
from __future__ import annotations

import asyncio
import os
import time

from studyhall.frontier import work_once
from studyhall.live import chat_event, lesson_event, proposal_event, short_turn
from studyhall.missions import list_missions, running_missions, save_mission
from studyhall.reader import Reading


def automate_enabled() -> bool:
    raw = (os.environ.get("STUDYHALL_AUTOMATE") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


class ResearchRunner:
    def __init__(self, hall, client):
        self.hall = hall
        self.client = client
        self.backlog: list[dict] = []
        self.subscribers: list[asyncio.Queue] = []
        self._task: asyncio.Task | None = None
        self._last_pace_log = 0.0

    def publish(self, event: str, data: dict) -> None:
        item = {"event": event, "data": data}
        self.backlog.append(item)
        self.backlog = self.backlog[-200:]
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                continue

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    def frames(self) -> list[str]:
        from studyhall.live import sse

        return [sse(item["event"], item["data"]) for item in self.backlog]

    async def start(self) -> None:
        standing = next((item for item in list_missions(self.hall.store) if item.get("standing")), None)
        title = (standing or {}).get("title") or "Study Hall"
        self.publish("looking", {
            "title": title,
            "url": "",
            "text": (
                "The standing mission is on. The room reads public pages about memory, voice, "
                "grounding, tool safety, and how people talk about assistants. "
                "Lesson cards stay drafts until you file them."
            ),
            "highlight": "Lesson cards stay drafts until you file them.",
            "why": "This mission runs until you pause or stop it.",
            "from_url": "",
            "kind": "mission",
            "relevance": 1,
        })
        intro = chat_event(
            "llama3.1:8b",
            "I’m here with the readers. Tell me what to look into, or leave the standing mission running. Nothing is filed until you say so.",
            role="moderator",
        )
        self.publish(intro["event"], intro["data"])
        if automate_enabled():
            self._task = asyncio.create_task(self._loop())

    async def shutdown(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                wait = await self._round()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.publish("activity", {"message": "The room hit an error and will try again.", "url": ""})
                wait = 5
            await asyncio.sleep(max(0.2, min(wait, 30)))

    async def _round(self) -> float:
        missions = running_missions(self.hall.store)
        if not missions:
            return 1.0
        wait = 0.4
        for mission in missions:
            frontier = self.hall.store.read_items("frontier.json")
            reads_at = [
                float(item["read_at"])
                for item in frontier
                if item.get("mission_id") == mission["mission_id"] and item.get("read_at")
            ]
            step = await work_once(
                mission=mission,
                frontier=frontier,
                fetch=self.client.fetch,
                study=lambda source, mission=mission: self._study(source, mission),
                now=time.time(),
                reads_at=reads_at,
            )
            self.hall.store.write_items("frontier.json", step.frontier)
            self._publish_progress(step.events[-1]["data"].get("url", "") if step.events else "")
            if step.edges:
                graph = self.hall.store.read_items("graph.json")
                graph.extend(step.edges)
                self.hall.store.write_items("graph.json", graph[-400:])
            if step.communities:
                known = {item.get("url") for item in mission.get("communities") or []}
                for community in step.communities:
                    if community.get("url") not in known:
                        mission.setdefault("communities", []).append(community)
                        known.add(community.get("url"))
            save_mission(self.hall.store, mission)
            for event in step.events:
                if step.action == "pace" and event.get("event") == "activity":
                    if time.time() - self._last_pace_log < 180:
                        continue
                    self._last_pace_log = time.time()
                self.publish(event["event"], event["data"])
                if event["event"] == "activity":
                    rows = self.hall.store.read_items("activity.json")
                    rows.append({"mission_id": mission["mission_id"], **event["data"], "at": time.time()})
                    self.hall.store.write_items("activity.json", rows[-200:])
            wait = max(wait, step.wait or 0)
        return wait

    def _publish_progress(self, fetching: str = "") -> None:
        frontier = self.hall.store.read_items("frontier.json")
        lessons = self.hall.store.read_items("lessons.json")
        index = {"wikipedia", "arxiv", "openalex", "semanticscholar", "crossref", "hn", "reddit", "duckduckgo", "bluesky", "searxng"}
        pages = sum(1 for item in frontier if item.get("status") == "read" and item.get("kind") not in index)
        self.publish("progress", {
            "fetching": fetching or "",
            "pages_read": pages,
            "leads_queued": sum(1 for item in frontier if item.get("status") == "queued"),
            "lessons_drafted": len(lessons),
        })

    def _remember(self, message: dict) -> None:
        rows = self.hall.store.read_items("chat.json")
        rows.append({k: v for k, v in message.items() if k != "color" or True})
        self.hall.store.write_items("chat.json", rows[-160:])

    async def _study(self, source: dict, mission: dict) -> dict:
        def on_note(note) -> None:
            text = short_turn(note.round, note.parsed, note.text, placeholder=note.placeholder, model=note.model)
            role = "moderator" if note.round == "pin" else "reader"
            event = chat_event(note.model, text, role=role, kind=note.kind, placeholder=note.placeholder)
            self.publish(event["event"], event["data"])
            self._remember(event["data"])

        reading = Reading(
            status="ok",
            url=source.get("url") or "",
            title=source.get("title") or "",
            date=source.get("date") or "",
            text=source.get("text") or "",
            kind=source.get("kind") or "article",
        )
        added = self.hall.add_reading(reading, origin="automate")
        source_row = added.get("source")
        if not added.get("stored") or not source_row:
            return {"events": []}
        tag = mission.get("tag") or ""
        try:
            result = await self.hall.study(source_row["source_id"], engine="auto", tag=tag, focus=tag, on_note=on_note)
        except RuntimeError:
            result = await self.hall.study(source_row["source_id"], engine="practice", tag=tag, focus=tag, on_note=on_note)
        events = []
        events.append(lesson_event(result["lesson"]))
        for proposal in result.get("proposals") or []:
            events.append(proposal_event(proposal))
        return {"events": events}
