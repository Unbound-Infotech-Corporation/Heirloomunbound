"""Google Docs and Sheets for the twin. OAuth only — no passwords.

Writes always preview first. We only create files (drive.file) — we do not
browse the owner's whole Drive.
"""
from __future__ import annotations

from typing import Any

import requests

DOCS_RECONNECT = (
    "Docs and Sheets aren't shared yet. Tap Connect Gmail again — Google will ask "
    "for Docs this time. We never see your password."
)
DOCS_EXPIRED = (
    "Google sign-in expired. Tap Connect Gmail again. Never ask for their password."
)
MAX_DOC_CHARS = 40000
MAX_SHEET_ROWS = 80
MAX_CELL = 200
MAX_FILES = 8

DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"

GOOGLE_WORKSPACE_SCOPES = f"{DOCS_SCOPE} {SHEETS_SCOPE} {DRIVE_FILE_SCOPE}"


def scope_has_docs(scope: str) -> bool:
    """True only when Google actually granted Docs — not Drive-file alone."""
    return "documents" in (scope or "").lower()


def scope_has_sheets(scope: str) -> bool:
    return "spreadsheets" in (scope or "").lower()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _raise_google(resp: requests.Response, expired: str, reconnect: str) -> None:
    if resp.status_code == 401:
        raise RuntimeError(expired)
    if resp.status_code == 403:
        raise RuntimeError(reconnect)
    if resp.status_code >= 400:
        raise RuntimeError(f"Google said no ({resp.status_code}). Try Connect Gmail again.")


def doc_preview(title: str, body: str) -> str:
    snippet = (body or "").strip()
    if len(snippet) > 900:
        snippet = snippet[:900] + "…"
    return (
        "I drafted this Google Doc. Ask them to confirm, then call write_google_doc again "
        "with confirmed=true.\n"
        f"Title: {title}\n---\n{snippet or '(empty — add the words before confirming)'}"
    )


def sheet_preview(title: str, headers: list[str], rows: list[list[str]]) -> str:
    head = ", ".join(headers) if headers else "(no columns)"
    sample = rows[:4]
    lines = [" | ".join(r) for r in sample]
    extra = f"\n…and {len(rows) - 4} more rows" if len(rows) > 4 else ""
    return (
        "I drafted this spreadsheet. Ask them to confirm, then call write_google_sheet again "
        "with confirmed=true.\n"
        f"Title: {title}\nColumns: {head}\n"
        + ("\n".join(lines) if lines else "(no rows yet)")
        + extra
    )


def normalize_headers(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
        return [p[:MAX_CELL] for p in parts if p][:20]
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            text = str(item).strip()[:MAX_CELL]
            if text:
                out.append(text)
            if len(out) >= 20:
                break
        return out
    return [str(raw).strip()[:MAX_CELL]] if str(raw).strip() else []


def normalize_rows(raw: object, *, column_count: int) -> list[list[str]]:
    if raw is None:
        return []
    rows_in: list[object]
    if isinstance(raw, str):
        rows_in = [line for line in raw.splitlines() if line.strip()]
    elif isinstance(raw, list):
        rows_in = raw
    else:
        return []
    cols = max(1, min(int(column_count or 1), 20))
    out: list[list[str]] = []
    for item in rows_in[:MAX_SHEET_ROWS]:
        if isinstance(item, dict):
            cells = [str(v).strip()[:MAX_CELL] for v in item.values()]
        elif isinstance(item, list):
            cells = [str(v).strip()[:MAX_CELL] for v in item]
        else:
            cells = [p.strip()[:MAX_CELL] for p in str(item).split(",")]
        if not any(cells):
            continue
        if len(cells) < cols:
            cells = cells + [""] * (cols - len(cells))
        out.append(cells[:cols])
    return out


def business_plan_outline(name: str, offering: str = "", audience: str = "") -> str:
    title = (name or "Business plan").strip() or "Business plan"
    offer = (offering or "").strip() or "(what you sell — fill this in)"
    who = (audience or "").strip() or "(who it's for — fill this in)"
    return (
        f"{title}\n\n"
        f"1. What we do\n{offer}\n\n"
        f"2. Who it's for\n{who}\n\n"
        "3. Why us\n(what we do that others don't)\n\n"
        "4. How we make money\n(price, what they buy, how often)\n\n"
        "5. First customers\n(who we already know, and how we reach them)\n\n"
        "6. Next 90 days\n- Month 1:\n- Month 2:\n- Month 3:\n\n"
        "7. What we need\n(time, money, help)\n"
    )


def create_google_document(access_token: str, title: str, body: str) -> dict[str, str]:
    title = (title or "Untitled").strip()[:120] or "Untitled"
    body = (body or "").strip()[:MAX_DOC_CHARS]
    resp = requests.post(
        "https://docs.googleapis.com/v1/documents",
        headers=_headers(access_token),
        json={"title": title},
        timeout=25,
    )
    _raise_google(resp, DOCS_EXPIRED, DOCS_RECONNECT)
    data = resp.json() if resp.content else {}
    doc_id = str(data.get("documentId") or "")
    if not doc_id:
        raise RuntimeError("Google created a Doc but didn't return a link. Try again.")
    if body:
        upd = requests.post(
            f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
            headers=_headers(access_token),
            json={"requests": [{"insertText": {"location": {"index": 1}, "text": body}}]},
            timeout=25,
        )
        _raise_google(upd, DOCS_EXPIRED, DOCS_RECONNECT)
    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    return {"id": doc_id, "url": url, "title": title, "kind": "doc"}


def create_google_spreadsheet(
    access_token: str,
    title: str,
    headers: list[str],
    rows: list[list[str]],
) -> dict[str, str]:
    title = (title or "Untitled sheet").strip()[:120] or "Untitled sheet"
    values: list[list[str]] = []
    if headers:
        values.append(headers)
    values.extend(rows)
    if not values:
        values = [["Column A"]]
    resp = requests.post(
        "https://sheets.googleapis.com/v4/spreadsheets",
        headers=_headers(access_token),
        json={"properties": {"title": title}},
        timeout=25,
    )
    _raise_google(resp, DOCS_EXPIRED, DOCS_RECONNECT)
    data = resp.json() if resp.content else {}
    sheet_id = str(data.get("spreadsheetId") or "")
    if not sheet_id:
        raise RuntimeError("Google created a Sheet but didn't return a link. Try again.")
    put = requests.put(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/A1",
        headers=_headers(access_token),
        params={"valueInputOption": "USER_ENTERED"},
        json={"values": values},
        timeout=25,
    )
    _raise_google(put, DOCS_EXPIRED, DOCS_RECONNECT)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    return {"id": sheet_id, "url": url, "title": title, "kind": "sheet"}


def list_google_workspace_files(access_token: str) -> list[dict[str, Any]]:
    resp = requests.get(
        "https://www.googleapis.com/drive/v3/files",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "pageSize": str(MAX_FILES),
            "orderBy": "modifiedTime desc",
            "fields": "files(id,name,mimeType,webViewLink,modifiedTime)",
            "q": "trashed = false",
        },
        timeout=20,
    )
    _raise_google(resp, DOCS_EXPIRED, DOCS_RECONNECT)
    files = (resp.json() or {}).get("files") or []
    out: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        mime = str(item.get("mimeType") or "")
        kind = "doc" if "document" in mime else ("sheet" if "spreadsheet" in mime else "file")
        out.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or "Untitled"),
            "kind": kind,
            "url": str(item.get("webViewLink") or ""),
            "modified": str(item.get("modifiedTime") or ""),
        })
    return out


def format_file_list(files: list[dict[str, Any]]) -> str:
    if not files:
        return "No Docs or Sheets from Heirloom yet."
    lines = []
    for item in files:
        kind = item.get("kind") or "file"
        url = item.get("url") or ""
        lines.append(f"- {item.get('name')} ({kind}) {url}".strip())
    return "Recent files we made:\n" + "\n".join(lines)
