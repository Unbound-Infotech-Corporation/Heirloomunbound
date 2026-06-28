"""OAuth account-linking router.

Today: Spotify. The structure is provider-agnostic so adding Google / GitHub /
YouTube later means just adding a new branch under each provider param.

Storage model — one document per (user_id, provider) in `oauth_connections`:
  { user_id, provider, access_token, refresh_token, expires_at, scope,
    profile, connected_at, last_refreshed_at }

Tokens are stored server-side only; the frontend never sees them. Refresh
happens automatically when an API call detects an expired token.

On first connect we ALSO seed the user's archive with a few personality
signals (top artists, top genres, recent listening). Customer doesn't have to
do anything — by tomorrow morning their Twin already knows what music they
love.
"""
from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from deps import db, get_current_user

router = APIRouter(prefix="/oauth", tags=["oauth"])

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "")
SPOTIFY_SCOPES = (
    "user-read-email user-read-private "
    "user-read-recently-played user-top-read user-library-read "
    "playlist-read-private user-read-playback-state user-modify-playback-state"
)

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI = os.environ.get("GITHUB_REDIRECT_URI", "")
GITHUB_SCOPES = "read:user user:email"
PUBLIC_FRONTEND = os.environ.get("PUBLIC_FRONTEND_URL", "").rstrip("/") or "/"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────── List + status ───────────────────────────


@router.get("/connections")
async def list_connections(user: dict = Depends(get_current_user)):
    """Return one row per provider showing whether THIS user has connected it."""
    docs = await db.oauth_connections.find(
        {"user_id": user["user_id"]}, {"_id": 0, "access_token": 0, "refresh_token": 0}
    ).to_list(length=20)
    by_provider = {d["provider"]: d for d in docs}

    providers = [
        {
            "provider": "spotify",
            "label": "Spotify",
            "description": "Auto-import recent listening, top artists, and favourite genres into your archive. The Twin learns your taste in music.",
            "configured": bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET and SPOTIFY_REDIRECT_URI),
            "connected": "spotify" in by_provider,
            "profile": by_provider.get("spotify", {}).get("profile") or None,
            "connected_at": by_provider.get("spotify", {}).get("connected_at"),
        },
        {
            "provider": "github",
            "label": "GitHub",
            "description": "Pull your recent repositories, primary languages, and READMEs into your archive. The Twin gets a sense of what you build.",
            "configured": bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET and GITHUB_REDIRECT_URI),
            "connected": "github" in by_provider,
            "profile": by_provider.get("github", {}).get("profile") or None,
            "connected_at": by_provider.get("github", {}).get("connected_at"),
        },
    ]
    return {"connections": providers}


@router.delete("/{provider}")
async def disconnect(provider: str, user: dict = Depends(get_current_user)):
    res = await db.oauth_connections.delete_one(
        {"user_id": user["user_id"], "provider": provider}
    )
    return {"disconnected": res.deleted_count > 0}


# ─────────────────────────── Spotify connect flow ───────────────────────────


@router.get("/spotify/connect")
async def spotify_connect(user: dict = Depends(get_current_user)):
    """Return the Spotify authorize URL. Frontend redirects the browser to it."""
    if not (SPOTIFY_CLIENT_ID and SPOTIFY_REDIRECT_URI):
        raise HTTPException(status_code=500, detail="Spotify not configured on the server")

    state_token = secrets.token_urlsafe(24)
    await db.oauth_states.insert_one({
        "state": state_token,
        "user_id": user["user_id"],
        "provider": "spotify",
        "created_at": _now_iso(),
    })

    params = {
        "response_type": "code",
        "client_id": SPOTIFY_CLIENT_ID,
        "scope": SPOTIFY_SCOPES,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "state": state_token,
        "show_dialog": "false",
    }
    return {"authorize_url": "https://accounts.spotify.com/authorize?" + urlencode(params)}


@router.get("/spotify/callback")
async def spotify_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    """Spotify redirects here. We exchange the code for tokens, pull the user's
    profile + a personality-signal snapshot, and store everything. Then we
    redirect the browser back to /settings."""
    redirect_back = f"{PUBLIC_FRONTEND}/settings?spotify="

    if error:
        return RedirectResponse(redirect_back + f"error:{error}", status_code=302)
    if not code or not state:
        return RedirectResponse(redirect_back + "error:missing_code", status_code=302)

    state_row = await db.oauth_states.find_one_and_delete({"state": state})
    if not state_row:
        return RedirectResponse(redirect_back + "error:invalid_state", status_code=302)

    uid = state_row["user_id"]

    # Exchange code → tokens
    tok = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": SPOTIFY_REDIRECT_URI,
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        },
        timeout=15,
    )
    if tok.status_code != 200:
        return RedirectResponse(redirect_back + f"error:token_{tok.status_code}", status_code=302)
    tk = tok.json()
    access = tk["access_token"]
    refresh = tk.get("refresh_token", "")
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(tk.get("expires_in", 3600)) - 60)).isoformat()

    headers = {"Authorization": f"Bearer {access}"}

    # Pull profile
    me = requests.get("https://api.spotify.com/v1/me", headers=headers, timeout=10).json()
    profile = {
        "id": me.get("id"),
        "display_name": me.get("display_name") or me.get("id"),
        "email": me.get("email"),
        "country": me.get("country"),
        "product": me.get("product"),
        "image": (me.get("images") or [{}])[0].get("url"),
    }

    await db.oauth_connections.update_one(
        {"user_id": uid, "provider": "spotify"},
        {"$set": {
            "user_id": uid,
            "provider": "spotify",
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": expires_at,
            "scope": SPOTIFY_SCOPES,
            "profile": profile,
            "connected_at": _now_iso(),
            "last_refreshed_at": _now_iso(),
        }},
        upsert=True,
    )

    # Seed archive with personality signals (fire-and-forget — never block redirect)
    try:
        await _seed_spotify_signals(uid, headers)
    except Exception as exc:  # noqa: BLE001
        print(f"[spotify] signal seed failed for {uid}: {exc}")

    return RedirectResponse(redirect_back + "connected", status_code=302)


async def _seed_spotify_signals(user_id: str, headers: dict) -> None:
    """Pull top artists + top tracks + recent listening and write a single
    summary archive entry. Quick and meaningful."""
    import uuid

    # Top artists (medium-term: ~6 months)
    top_a = requests.get(
        "https://api.spotify.com/v1/me/top/artists?time_range=medium_term&limit=10",
        headers=headers, timeout=10,
    ).json().get("items", [])
    # Top tracks
    top_t = requests.get(
        "https://api.spotify.com/v1/me/top/tracks?time_range=medium_term&limit=10",
        headers=headers, timeout=10,
    ).json().get("items", [])
    # Recent plays
    recent = requests.get(
        "https://api.spotify.com/v1/me/player/recently-played?limit=20",
        headers=headers, timeout=10,
    ).json().get("items", [])

    if not (top_a or top_t or recent):
        return

    # Aggregate genres
    genres: dict[str, int] = {}
    for a in top_a:
        for g in (a.get("genres") or []):
            genres[g] = genres.get(g, 0) + 1
    top_genres = sorted(genres.items(), key=lambda x: -x[1])[:6]

    bits = []
    if top_a:
        bits.append("Top artists right now: " + ", ".join(a["name"] for a in top_a[:8]) + ".")
    if top_genres:
        bits.append("Favourite genres: " + ", ".join(g for g, _ in top_genres) + ".")
    if top_t:
        bits.append("Top tracks: " + "; ".join(
            f"{t['name']} — {t['artists'][0]['name']}" for t in top_t[:6]
        ) + ".")
    if recent:
        last = recent[0]
        last_t = last.get("track", {})
        last_a = (last_t.get("artists") or [{}])[0].get("name", "")
        bits.append(f"Last played: {last_t.get('name')} by {last_a}.")

    content = "\n\n".join(bits)
    entry_id = f"ent_{uuid.uuid4().hex[:12]}"
    await db.entries.insert_one({
        "entry_id": entry_id,
        "user_id": user_id,
        "type": "memory",
        "title": "What I'm listening to (from Spotify)",
        "content": content,
        "tags": ["music", "spotify", "personality"],
        "source": "spotify",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    })

    # Also write a long-term identity fact: "musical taste"
    await db.memory_facts.update_one(
        {"user_id": user_id, "key": "musical_taste"},
        {"$set": {
            "fact_id": f"f_{uuid.uuid4().hex[:10]}",
            "user_id": user_id,
            "key": "musical_taste",
            "value": ", ".join(g for g, _ in top_genres[:5]) or ", ".join(a["name"] for a in top_a[:5]),
            "source": "spotify",
            "updated_at": _now_iso(),
        }},
        upsert=True,
    )


# ─────────────────────────── GitHub connect flow ───────────────────────────


@router.get("/github/connect")
async def github_connect(user: dict = Depends(get_current_user)):
    if not (GITHUB_CLIENT_ID and GITHUB_REDIRECT_URI):
        raise HTTPException(status_code=500, detail="GitHub not configured on the server")

    state_token = secrets.token_urlsafe(24)
    await db.oauth_states.insert_one({
        "state": state_token,
        "user_id": user["user_id"],
        "provider": "github",
        "created_at": _now_iso(),
    })
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_REDIRECT_URI,
        "scope": GITHUB_SCOPES,
        "state": state_token,
        "allow_signup": "true",
    }
    return {"authorize_url": "https://github.com/login/oauth/authorize?" + urlencode(params)}


@router.get("/github/callback")
async def github_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    redirect_back = f"{PUBLIC_FRONTEND}/settings?github="
    if error:
        return RedirectResponse(redirect_back + f"error:{error}", status_code=302)
    if not code or not state:
        return RedirectResponse(redirect_back + "error:missing_code", status_code=302)
    state_row = await db.oauth_states.find_one_and_delete({"state": state})
    if not state_row:
        return RedirectResponse(redirect_back + "error:invalid_state", status_code=302)
    uid = state_row["user_id"]

    tok = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": GITHUB_REDIRECT_URI,
        },
        timeout=15,
    )
    if tok.status_code != 200:
        return RedirectResponse(redirect_back + f"error:token_{tok.status_code}", status_code=302)
    tk = tok.json()
    if "access_token" not in tk:
        # GitHub returns 200 with an "error" field for bad creds
        return RedirectResponse(redirect_back + f"error:{tk.get('error', 'no_token')}", status_code=302)
    access = tk["access_token"]

    headers = {"Authorization": f"Bearer {access}", "Accept": "application/vnd.github+json"}
    me = requests.get("https://api.github.com/user", headers=headers, timeout=10).json()
    profile = {
        "id": me.get("id"),
        "display_name": me.get("name") or me.get("login"),
        "login": me.get("login"),
        "image": me.get("avatar_url"),
        "bio": me.get("bio"),
        "location": me.get("location"),
        "public_repos": me.get("public_repos"),
        "followers": me.get("followers"),
    }

    # GitHub OAuth access tokens are non-expiring by default — no refresh needed
    await db.oauth_connections.update_one(
        {"user_id": uid, "provider": "github"},
        {"$set": {
            "user_id": uid,
            "provider": "github",
            "access_token": access,
            "refresh_token": "",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=365 * 5)).isoformat(),
            "scope": GITHUB_SCOPES,
            "profile": profile,
            "connected_at": _now_iso(),
            "last_refreshed_at": _now_iso(),
        }},
        upsert=True,
    )

    try:
        await _seed_github_signals(uid, headers, profile)
    except Exception as exc:  # noqa: BLE001
        print(f"[github] signal seed failed for {uid}: {exc}")

    return RedirectResponse(redirect_back + "connected", status_code=302)


async def _seed_github_signals(user_id: str, headers: dict, profile: dict) -> None:
    import uuid

    # Recent repos (most recently updated, owner = self)
    repos = requests.get(
        "https://api.github.com/user/repos?sort=updated&per_page=15&affiliation=owner",
        headers=headers, timeout=10,
    ).json()
    if not isinstance(repos, list) or not repos:
        return

    # Aggregate languages
    languages: dict[str, int] = {}
    for r in repos:
        lang = r.get("language")
        if lang:
            languages[lang] = languages.get(lang, 0) + 1
    top_langs = sorted(languages.items(), key=lambda x: -x[1])[:5]

    bits = []
    if profile.get("bio"):
        bits.append(f"GitHub bio: {profile['bio']}")
    bits.append(
        f"On GitHub as @{profile.get('login')} with "
        f"{profile.get('public_repos', 0)} public repos and {profile.get('followers', 0)} followers."
    )
    if top_langs:
        bits.append("Languages I work in most: " + ", ".join(f"{l} ({n})" for l, n in top_langs) + ".")
    # Most recently touched 6 repos with one-line descriptions
    repo_lines = []
    for r in repos[:6]:
        line = f"- {r['name']}"
        if r.get("description"):
            line += f": {r['description']}"
        repo_lines.append(line)
    if repo_lines:
        bits.append("Recent repositories:\n" + "\n".join(repo_lines))

    await db.entries.insert_one({
        "entry_id": f"ent_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "type": "memory",
        "title": "What I'm building (from GitHub)",
        "content": "\n\n".join(bits),
        "tags": ["work", "code", "github", "personality"],
        "source": "github",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    })

    if top_langs:
        await db.memory_facts.update_one(
            {"user_id": user_id, "key": "primary_languages"},
            {"$set": {
                "fact_id": f"f_{uuid.uuid4().hex[:10]}",
                "user_id": user_id,
                "key": "primary_languages",
                "value": ", ".join(l for l, _ in top_langs),
                "source": "github",
                "updated_at": _now_iso(),
            }},
            upsert=True,
        )


# ─────────────────────────── Refresh helper (used by music.py later) ──────


async def get_fresh_spotify_token(user_id: str) -> str | None:
    """Return a valid access token for this user; refresh if expired."""
    row = await db.oauth_connections.find_one(
        {"user_id": user_id, "provider": "spotify"}, {"_id": 0}
    )
    if not row:
        return None
    try:
        exp = datetime.fromisoformat(row["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < exp:
            return row["access_token"]
    except Exception:
        pass

    if not row.get("refresh_token"):
        return None

    tok = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": row["refresh_token"],
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        },
        timeout=15,
    )
    if tok.status_code != 200:
        return None
    tk = tok.json()
    new_access = tk["access_token"]
    new_exp = (datetime.now(timezone.utc) + timedelta(seconds=int(tk.get("expires_in", 3600)) - 60)).isoformat()
    await db.oauth_connections.update_one(
        {"user_id": user_id, "provider": "spotify"},
        {"$set": {
            "access_token": new_access,
            "expires_at": new_exp,
            "last_refreshed_at": _now_iso(),
        }},
    )
    return new_access
