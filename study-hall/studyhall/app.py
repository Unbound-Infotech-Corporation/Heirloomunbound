"""Local web shell for Study Hall. Binds to this machine only unless the owner says otherwise."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from studyhall import __version__
from studyhall.config import default_data_dir, load_config
from studyhall.discover import discover
from studyhall.chat import apply_instruction, login_wall, urls_in
from studyhall.frontier import enqueue, seed_leads
from studyhall.hall import Hall, lookup_topic
from studyhall.live import sse
from studyhall.missions import get_mission, list_missions, save_mission, set_status
from studyhall.reader import PoliteClient, Reading, extract_pdf
from studyhall.runner import ResearchRunner
from studyhall.startup import apply_login_start

STATIC = Path(__file__).resolve().parent / "static"
FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="4" fill="#121110"/>
<path d="M9 6h10l4 4v16H9z" fill="none" stroke="#d4a373" stroke-width="1.5"/>
<path d="M19 6v4h4" fill="none" stroke="#d4a373" stroke-width="1.5"/>
</svg>"""


class UrlBody(BaseModel):
    url: str = ""


class TopicBody(BaseModel):
    topic: str = ""


class ReadBody(BaseModel):
    url: str = ""
    title: str = ""
    date: str = ""
    origin: str = "topic"


class StudyBody(BaseModel):
    source_id: str
    engine: str = Field(default="auto")


class ChatBody(BaseModel):
    text: str = ""


class PaceBody(BaseModel):
    pages_per_hour: int | None = None
    max_depth: int | None = None


class StartupBody(BaseModel):
    enabled: bool = False


def create_app(data_dir: Path | None = None) -> FastAPI:
    hall = Hall(data_dir) if data_dir is not None else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        root = data_dir if data_dir is not None else default_data_dir()
        app.state.hall = hall or Hall(root)
        config = load_config()
        app.state.client = PoliteClient(min_interval=float(config.get("min_interval") or 1.5))
        app.state.runner = ResearchRunner(app.state.hall, app.state.client)
        await app.state.runner.start()
        yield
        await app.state.runner.shutdown()
        await app.state.client.aclose()

    app = FastAPI(title="Heirloom Study Hall", version=__version__, lifespan=lifespan)
    if STATIC.is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC), name="assets")

    def room() -> Hall:
        return app.state.hall

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/favicon.svg")
    def favicon():
        return Response(FAVICON, media_type="image/svg+xml")

    @app.get("/api/health")
    def health():
        return {"ok": True, "name": "Heirloom Study Hall", "version": __version__}

    @app.get("/api/setup")
    def setup():
        config = load_config()
        settings = room().store.read_settings()
        return {
            "version": __version__,
            "acked": bool(settings.get("setup_acked")),
            "data_dir": str(room().store.root),
            "knowledge": str(room().store.knowledge_path),
            "ollama": config.get("ollama") or [],
            "panel": config.get("panel") or {},
            "embed_models": config.get("embed_models") or [],
        }

    @app.post("/api/setup/ack")
    def ack():
        settings = room().store.read_settings()
        settings["setup_acked"] = True
        room().store.write_settings(settings)
        return {"acked": True}

    @app.get("/api/models")
    async def models():
        return await discover(load_config())

    @app.get("/api/library")
    def library():
        return {"sources": room().library()}

    @app.get("/api/library/{source_id}")
    def one_source(source_id: str):
        source = room().source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="That reading is not in the library.")
        return {"source": source}

    @app.post("/api/library/url")
    async def add_url(body: UrlBody):
        url = (body.url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="Paste a link first.")
        reading = await room_client(app).fetch(url)
        result = room().add_reading(reading, origin="url")
        if reading.status == "paywall":
            return {"stored": False, "status": "paywall", "message": reading.message, "citation": reading.citation()}
        if not result.get("stored") and result.get("status") in {"robots", "error", "paywall"}:
            raise HTTPException(status_code=422, detail=result.get("message") or "That page was not read.")
        return result

    @app.post("/api/library/topic")
    async def add_topic(body: TopicBody):
        topic = " ".join((body.topic or "").split())
        if not topic:
            raise HTTPException(status_code=400, detail="Type a topic first.")
        found = await lookup_topic(room_client(app), topic)
        return found

    @app.post("/api/library/read")
    async def read_candidate(body: ReadBody):
        url = (body.url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="Choose a reading first.")
        reading = await room_client(app).fetch(url)
        if body.title and reading.status == "ok" and not reading.title:
            reading.title = body.title
        result = room().add_reading(reading, origin=body.origin or "topic")
        if not result.get("stored") and result.get("status") != "duplicate":
            raise HTTPException(status_code=422, detail=result.get("message") or reading.message or "That page was not read.")
        return result

    @app.post("/api/library/sample")
    def add_sample():
        return room().add_sample()

    @app.post("/api/library/file")
    async def add_file(file: UploadFile = File(...)):
        name = file.filename or "reading"
        data = await file.read()
        if len(data) > 8_000_000:
            raise HTTPException(status_code=413, detail="That file is larger than Study Hall will store.")
        suffix = Path(name).suffix.lower()
        if suffix == ".pdf" or data.startswith(b"%PDF"):
            try:
                extracted = extract_pdf(data)
            except Exception as exc:
                raise HTTPException(status_code=422, detail="This PDF could not be read.") from exc
            if not extracted["text"]:
                raise HTTPException(status_code=422, detail="This PDF has no extractable text.")
            reading = Reading(
                status="ok",
                url=f"file://{name}",
                title=extracted["title"] or name,
                date=extracted["date"],
                text=extracted["text"],
                kind="pdf",
            )
        else:
            try:
                raw = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=422, detail="This file is not text Study Hall can read.") from exc
            extracted = extract_html(raw, name)
            if len(extracted["text"]) < 80:
                extracted["text"] = " ".join(raw.split())
            if len(extracted["text"]) < 80:
                raise HTTPException(status_code=422, detail="This file had almost no readable text.")
            reading = Reading(
                status="ok",
                url=f"file://{name}",
                title=extracted["title"] or name,
                date=extracted["date"],
                text=extracted["text"][:80000],
                kind="doc",
            )
        return room().add_reading(reading, origin="file")

    @app.post("/api/study")
    async def study(body: StudyBody):
        engine = (body.engine or "auto").strip().lower()
        if engine not in {"auto", "practice"}:
            raise HTTPException(status_code=400, detail="Choose the local panel or the practice panel.")
        try:
            return await room().study(body.source_id, engine=engine)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="That reading is not in the library.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "no-models":
                raise HTTPException(
                    status_code=409,
                    detail="No local models answered. You can run the practice panel, or start Ollama and try again.",
                ) from exc
            raise

    @app.get("/api/lessons")
    def lessons():
        return {"lessons": room().lessons()}

    @app.post("/api/lessons/{lesson_id}/file")
    def file_lesson(lesson_id: str):
        try:
            return room().file_lesson(lesson_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="That lesson is not here.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/lessons/{lesson_id}/reject")
    def reject_lesson(lesson_id: str):
        try:
            return room().reject_lesson(lesson_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="That lesson is not here.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/lessons/{lesson_id}/unfile")
    def unfile_lesson(lesson_id: str):
        try:
            return room().unfile_lesson(lesson_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="That lesson is not here.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/queue")
    def queue():
        return {"proposals": room().proposals()}

    @app.post("/api/queue/{proposal_id}/accept")
    def accept_idea(proposal_id: str):
        try:
            return room().accept_proposal(proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="That idea is not in the queue.") from exc

    @app.post("/api/queue/{proposal_id}/decline")
    def decline_idea(proposal_id: str):
        try:
            return room().decline_proposal(proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="That idea is not in the queue.") from exc

    @app.get("/api/receipts")
    def receipts():
        return {"receipts": room().receipts()}

    @app.get("/api/knowledge")
    def knowledge():
        return {"lessons": room().store.read_knowledge(), "path": str(room().store.knowledge_path)}

    @app.get("/api/missions")
    def missions():
        return {"missions": list_missions(room().store)}

    @app.post("/api/missions/{mission_id}/{verb}")
    def mission_verb(mission_id: str, verb: str):
        if verb not in {"pause", "stop", "start"}:
            raise HTTPException(status_code=404, detail="That control is not here.")
        status = {"pause": "paused", "stop": "stopped", "start": "running"}[verb]
        try:
            mission = set_status(room().store, mission_id, status)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="That mission is not here.") from exc
        note = {
            "paused": "Paused. It will sit until you start it.",
            "stopped": "Stopped. Say start when you want it moving again.",
            "running": "Running. It keeps going until you pause or stop it.",
        }[status]
        app.state.runner.publish("activity", {"message": note, "url": ""})
        return {"mission": mission, "note": note}

    @app.patch("/api/missions/{mission_id}")
    def mission_pace(mission_id: str, body: PaceBody):
        mission = get_mission(room().store, mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="That mission is not here.")
        if body.pages_per_hour is not None:
            mission["pages_per_hour"] = max(1, min(int(body.pages_per_hour), 3600))
        if body.max_depth is not None:
            mission["max_depth"] = max(0, min(int(body.max_depth), 6))
        save_mission(room().store, mission)
        return {"mission": mission}

    @app.get("/api/activity")
    def activity():
        return {"activity": room().store.read_items("activity.json")[-80:]}

    @app.get("/api/graph")
    def graph():
        return {"edges": room().store.read_items("graph.json")[-80:]}

    @app.get("/api/live/stream")
    async def live_stream(once: int = 0):
        runner = app.state.runner

        async def gen():
            for item in list(runner.backlog)[-80:]:
                yield sse(item["event"], item["data"])
            yield sse("hello", {"ok": True})
            if once:
                return
            queue = runner.subscribe()
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=12)
                    except asyncio.TimeoutError:
                        yield sse("ping", {"ok": True})
                        continue
                    yield sse(item["event"], item["data"])
            finally:
                runner.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/chat")
    def chat_log():
        return {"messages": room().store.read_items("chat.json")[-40:]}

    @app.post("/api/chat")
    async def chat(body: ChatBody):
        text = " ".join((body.text or "").split())
        if not text:
            raise HTTPException(status_code=400, detail="Say something first.")
        pasted = urls_in(text)
        if pasted:
            result = await _read_owner_url(app, pasted[0])
        else:
            result = apply_instruction(room().store, text)
        if result.get("action") == "research" and result.get("mission"):
            mission = result["mission"]
            leads = seed_leads(mission)
            frontier = enqueue(room().store.read_items("frontier.json"), leads, mission["mission_id"])
            room().store.write_items("frontier.json", frontier)
            save_mission(room().store, mission)
        stamp = datetime.now(timezone.utc).isoformat()
        messages = room().store.read_items("chat.json")
        owner = {"name": "You", "role": "owner", "color": "#f4f0e8", "text": text, "at": stamp}
        reply = {"name": "llama3.1:8b", "role": "moderator", "color": "#f0d2b0", "text": result["reply"], "at": stamp, "citations": result.get("citations") or []}
        messages.extend([owner, reply])
        room().store.write_items("chat.json", messages[-80:])
        app.state.runner.publish("chat", owner)
        app.state.runner.publish("chat", reply)
        return {"reply": result["reply"], "action": result.get("action"), "citations": result.get("citations") or [], "mission": result.get("mission")}

    @app.get("/api/startup")
    def startup_state():
        settings = room().store.read_settings()
        return {"enabled": bool(settings.get("launch_at_login"))}

    @app.post("/api/startup")
    def startup_toggle(body: StartupBody):
        from studyhall.config import package_root

        applied = apply_login_start(body.enabled, package_root())
        settings = room().store.read_settings()
        settings["launch_at_login"] = bool(body.enabled)
        room().store.write_settings(settings)
        return applied

    return app


def room_client(app: FastAPI) -> PoliteClient:
    return app.state.client


async def _read_owner_url(app: FastAPI, url: str) -> dict:
    """Read a link the owner pasted, then draft a lesson. Login walls are named, not guessed."""
    hall = app.state.hall
    if login_wall(url):
        return {
            "reply": (
                f"{url} needs a login. Study Hall does not sign in or join groups. "
                "Paste a public article, a paper, or the text itself."
            ),
            "action": "login",
            "citations": [{"title": url, "url": url}],
            "mission": None,
        }
    app.state.runner.publish("progress", {"fetching": url, "pages_read": 0, "leads_queued": 0, "lessons_drafted": 0})
    reading = await room_client(app).fetch(url)
    if reading.status != "ok":
        plain = reading.message or "That page could not be read."
        if reading.status in {"paywall", "robots"} or "login" in plain.lower() or "sign in" in plain.lower():
            plain = (
                f"That page is not openly readable ({plain}). "
                "Study Hall does not sign in or pass a paywall. Try the publisher’s abstract, an arXiv link, or paste the text."
            )
        return {"reply": plain, "action": "read_url", "citations": [{"title": reading.title or url, "url": url}], "mission": None}
    added = hall.add_reading(reading, origin="owner")
    source = added.get("source") or {}
    app.state.runner.publish("looking", {
        "url": reading.url,
        "title": reading.title,
        "text": (reading.text or "")[:4000],
        "highlight": (reading.text or "")[:240],
        "why": "You pasted this link.",
        "from_url": "",
        "kind": reading.kind,
    })
    lesson = None
    if source.get("source_id") and added.get("stored"):
        try:
            studied = await hall.study(source["source_id"], engine="auto", tag="", focus="")
        except RuntimeError:
            studied = await hall.study(source["source_id"], engine="practice", tag="", focus="")
        lesson = studied.get("lesson")
        if lesson:
            app.state.runner.publish("lesson", lesson)
        for proposal in studied.get("proposals") or []:
            app.state.runner.publish("proposal", proposal)
    title = reading.title or url
    if lesson:
        reply = f"Read “{title}”. A lesson card is drafted and waiting for you to file it."
    elif added.get("status") == "duplicate":
        reply = f"“{title}” is already in the library."
    else:
        reply = f"Read “{title}”."
    return {"reply": reply, "action": "read_url", "citations": [reading.citation()], "mission": None, "lesson": lesson}
