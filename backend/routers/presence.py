"""Owner presence API. Heirs receive 404. Embeddings are never returned."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deps import get_current_user
from presence_access import require_owner
from presence_match import best_match
from presence_store import (
    PresenceStore,
    decode_photo,
    presence_dir,
    presence_enabled,
    status_public,
)

router = APIRouter(prefix="/presence", tags=["presence"])


class PersonReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    relationship: str = Field(..., min_length=1, max_length=40)
    greeting: str = Field("", max_length=200)
    consent: bool = False


class PersonPatch(BaseModel):
    name: str | None = Field(None, max_length=80)
    relationship: str | None = Field(None, max_length=40)
    greeting: str | None = Field(None, max_length=200)


class SampleReq(BaseModel):
    embedding: list[float] | None = None
    image_base64: str | None = None


class TestReq(BaseModel):
    embedding: list[float] | None = None
    live: bool = False


class SettingsReq(BaseModel):
    threshold: float | None = None
    debounce_minutes: float | None = None
    depart_seconds: float | None = None
    unknown_debounce_minutes: float | None = None
    unknown_thumbnails: bool | None = None
    quiet_hours: str | None = None
    sample_fps: float | None = None
    motion_threshold: float | None = None


def _store(user: dict) -> PresenceStore:
    require_owner(user)
    return PresenceStore(presence_dir())


def _require_enabled(store: PresenceStore) -> PresenceStore:
    if not presence_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    return store


@router.get("/status")
async def presence_status(user: dict = Depends(get_current_user)):
    store = _store(user)
    return status_public(store)


@router.get("/now")
async def presence_now(user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    payload = status_public(store)
    return {"present": payload.get("present") or [], "paused": payload.get("paused")}


@router.get("/people")
async def list_people(user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    return {"people": store.list_people()}


@router.post("/people")
async def create_person(body: PersonReq, user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    try:
        person = store.create_person(
            name=body.name,
            relationship=body.relationship,
            greeting=body.greeting,
            consent=body.consent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"person": person}


@router.patch("/people/{person_id}")
async def patch_person(person_id: str, body: PersonPatch, user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    try:
        person = store.update_person(person_id, body.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"person": person}


@router.delete("/people/{person_id}")
async def delete_person(person_id: str, user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    try:
        store.delete_person(person_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": person_id}


@router.post("/people/{person_id}/samples")
async def add_sample(person_id: str, body: SampleReq, user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    if body.embedding is not None:
        try:
            person = store.add_sample(person_id, body.embedding)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"person": person, "stored": "embedding"}
    if body.image_base64:
        try:
            photo = decode_photo(body.image_base64)
            job = store.enqueue("photo", person_id=person_id, photo=photo)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"job": job, "stored": "queued"}
    raise HTTPException(status_code=400, detail="Add an embedding or a JPEG")


@router.post("/people/{person_id}/capture")
async def capture_sample(person_id: str, user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    try:
        job = store.enqueue("capture", person_id=person_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job": job}


@router.get("/people/{person_id}/thumb")
async def person_thumb(person_id: str, user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    try:
        path = store.thumb_path(person_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    return FileResponse(path, media_type="image/jpeg")


@router.post("/test")
async def test_recognition(body: TestReq, user: dict = Depends(get_current_user)):
    """Match a vector, or ask the camera service to look once. Never enrolls."""
    store = _require_enabled(_store(user))
    if body.live or body.embedding is None:
        job = store.enqueue("test")
        return {"job": job, "stored": False}
    try:
        found = best_match(body.embedding, store.enrolled_vectors(), store.read_settings()["threshold"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if found is None:
        return {"matched": False, "stored": False}
    return {
        "matched": True,
        "stored": False,
        "person_id": found.person_id,
        "name": found.name,
        "relationship": found.relationship,
        "score": found.score,
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    store.expire_jobs()
    try:
        job = store.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    return {"job": job}


@router.get("/events")
async def list_events(user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    return {"events": store.read_events()}


@router.get("/unknown")
async def list_unknown(user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    store.purge_unknown()
    return {"unknown": store.list_unknown()}


@router.get("/unknown/{stamp}")
async def unknown_thumb(stamp: str, user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    try:
        path = store.unknown_thumb_path(stamp)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    return FileResponse(path, media_type="image/jpeg")


@router.post("/pause")
async def pause(user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    from box_pause import share_pause

    share_pause(True, "web")
    state = store.set_paused(True, "web")
    return {"paused": True, "reason": state.get("reason") or "web"}


@router.post("/resume")
async def resume(user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    from box_pause import share_pause

    share_pause(False, "")
    store.set_paused(False, "")
    return {"paused": False}


@router.post("/forget")
async def forget(user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    return store.forget_everyone()


@router.put("/settings")
async def put_settings(body: SettingsReq, user: dict = Depends(get_current_user)):
    store = _require_enabled(_store(user))
    try:
        settings = store.write_settings(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"settings": settings}
