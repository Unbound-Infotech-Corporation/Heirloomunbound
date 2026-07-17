"""Archive export — full JSON dump + printable HTML memoir (Save as PDF in browser)."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse, JSONResponse

from deps import db, get_current_user

router = APIRouter(prefix="/export", tags=["export"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/archive.json")
async def export_archive_json(user: dict = Depends(get_current_user)):
    """Full portable archive for heirs / lawyers / backups."""
    uid = user["user_id"]
    entries = await db.entries.find({"user_id": uid}, {"_id": 0}).sort("created_at", 1).to_list(length=5000)
    facts = await db.memory_facts.find({"user_id": uid}, {"_id": 0}).to_list(length=200)
    heirs = await db.heirs.find(
        {"user_id": uid},
        {"_id": 0, "release_token": 0},
    ).to_list(length=200)
    letters = await db.sealed_letters.find({"user_id": uid}, {"_id": 0}).to_list(length=500)
    photos = await db.photos.find({"user_id": uid, "deleted": {"$ne": True}}, {"_id": 0}).to_list(length=1000)

    payload = {
        "exported_at": _now_iso(),
        "format": "heirloom.archive.v1",
        "owner": {
            "user_id": uid,
            "name": user.get("name"),
            "email": user.get("email"),
        },
        "counts": {
            "entries": len(entries),
            "facts": len(facts),
            "heirs": len(heirs),
            "letters": len(letters),
            "photos": len(photos),
        },
        "entries": entries,
        "identity_facts": facts,
        "heirs": heirs,
        "letters": letters,
        "photos": photos,
    }
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="heirloom-archive-{uid[:8]}.json"',
        },
    )


@router.get("/memoir.html")
async def export_memoir_html(user: dict = Depends(get_current_user)):
    """Chaptered HTML memoir — open and Print → Save as PDF."""
    uid = user["user_id"]
    name = html.escape(user.get("name") or "Untitled life")
    entries = await db.entries.find({"user_id": uid}, {"_id": 0}).sort("created_at", 1).to_list(length=2000)
    facts = await db.memory_facts.find({"user_id": uid}, {"_id": 0}).limit(40).to_list(length=40)

    by_type: dict[str, list] = {}
    for e in entries:
        by_type.setdefault(e.get("type") or "note", []).append(e)

    chapters = []
    order = ["story", "memory", "value", "advice", "quote", "chapter", "voice", "note", "import"]
    for t in order:
        items = by_type.pop(t, [])
        if not items:
            continue
        chapters.append((t, items))
    for t, items in sorted(by_type.items()):
        chapters.append((t, items))

    fact_html = ""
    if facts:
        lis = "".join(f"<li>{html.escape(f.get('fact',''))}</li>" for f in facts if f.get("fact"))
        fact_html = f"<section><h2>What I hold onto</h2><ul>{lis}</ul></section>"

    body_parts = [fact_html]
    for t, items in chapters:
        blocks = []
        for e in items:
            title = html.escape(e.get("title") or "(untitled)")
            content = html.escape(e.get("content") or "").replace("\n", "<br/>")
            when = html.escape((e.get("created_at") or "")[:10])
            blocks.append(
                f'<article><h3>{title}</h3><div class="meta">{when}</div><p>{content}</p></article>'
            )
        body_parts.append(
            f'<section><h2>{html.escape(t.title())}</h2>{"".join(blocks)}</section>'
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{name} — Memoir · Heirloom</title>
<style>
  @page {{ margin: 2cm; }}
  body {{ font-family: Georgia, serif; color: #1a1714; max-width: 42rem; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.55; }}
  h1 {{ font-weight: 400; font-size: 2.4rem; margin-bottom: 0.25rem; }}
  .sub {{ color: #666; margin-bottom: 2.5rem; font-size: 0.95rem; }}
  h2 {{ font-weight: 400; border-bottom: 1px solid #ddd; padding-bottom: 0.35rem; margin-top: 2.5rem; }}
  h3 {{ font-weight: 600; font-size: 1.1rem; margin: 1.4rem 0 0.3rem; }}
  .meta {{ color: #888; font-size: 0.8rem; margin-bottom: 0.4rem; }}
  article {{ page-break-inside: avoid; }}
  @media print {{
    body {{ margin: 0; }}
    .noprint {{ display: none; }}
  }}
  .noprint button {{
    background: #1a1714; color: #f5f2ec; border: 0; padding: 0.65rem 1.1rem;
    font-size: 0.9rem; cursor: pointer; border-radius: 2px;
  }}
</style>
</head>
<body>
  <div class="noprint" style="margin-bottom:1.5rem">
    <button onclick="window.print()">Print / Save as PDF</button>
  </div>
  <h1>{name}</h1>
  <p class="sub">A memoir from Heirloom · exported {_now_iso()[:10]} · {len(entries)} entries</p>
  {"".join(body_parts) or "<p><em>No archive entries yet.</em></p>"}
  <footer style="margin-top:3rem;color:#999;font-size:0.8rem">Generated by Heirloom · Unbound Infotech</footer>
</body>
</html>"""
    return HTMLResponse(
        content=page,
        headers={"Content-Disposition": f'inline; filename="heirloom-memoir-{uid[:8]}.html"'},
    )
