"""Owner-only VR setup catalog and OpenXR probe for Heirloom Rooms."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from deps import get_current_user
from vr_compat import probe_host, public_catalog

router = APIRouter(prefix="/rooms/vr", tags=["rooms-vr"])


def _owner_gate(user: dict) -> None:
    if user.get("account_status") == "refunded":
        raise HTTPException(status_code=403, detail="account_inactive")


@router.get("/catalog")
async def vr_catalog(user: dict = Depends(get_current_user)):
    """Headset × path matrix. Links official free software only — no binaries."""
    _owner_gate(user)
    return public_catalog()


@router.get("/probe")
async def vr_probe(user: dict = Depends(get_current_user)):
    """Filesystem OpenXR self-check for the machine running the API."""
    _owner_gate(user)
    return probe_host()
