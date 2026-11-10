"""Local web shell for Study Hall. Binds to this machine only unless the owner says otherwise."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from studyhall import __version__
from studyhall.config import default_data_dir, load_config
from studyhall.discover import discover
from studyhall.hall import Hall, lookup_topic
from studyhall.reader import PoliteClient, Reading, extract_pdf

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


def create_app(data_dir: Path | None = None) -> FastAPI:
    hall = Hall(data_dir) if data_dir is not None else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        root = data_dir if data_dir is not None else default_data_dir()
        app.state.hall = hall or Hall(root)
        config = load_config()
        app.state.client = PoliteClient(min_interval=float(config.get("min_interval") or 1.5))
        yield
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

    return app


def room_client(app: FastAPI) -> PoliteClient:
    return app.state.client
