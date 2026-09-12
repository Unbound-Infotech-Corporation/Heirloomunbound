"""Owner rail — Slice 1 of OWNER_RAIL.md.

One owner teammate chat classifies each turn to Assist (Do / PC) and/or
Twin (Ask / vault). Heir and caller surfaces must never enter this mode.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from owner_pairing import is_owner_audience

ROUTE_ASSIST = "assist"
ROUTE_TWIN = "twin"
ROUTE_BOTH = "both"

CHIP_DO = "Do"
CHIP_AS_YOU = "As you"
CHIP_BOTH = "Do + As you"

CHIP_BY_ROUTE = {
    ROUTE_ASSIST: CHIP_DO,
    ROUTE_TWIN: CHIP_AS_YOU,
    ROUTE_BOTH: CHIP_BOTH,
}

VALID_CHAT_MODES = frozenset({"twin", "assistant", "owner"})

# Tools that may only appear on the Assist leg.
PC_TOOL_NAMES = frozenset({
    "open_on_pc",
    "control_media",
    "set_volume",
    "power_action",
    "notify_on_pc",
    "type_text",
    "clipboard",
    "system_status",
    "find_file",
    "see_screen",
    "run_command",
})

# Assist = Do on this PC. Twin = Ask the archive / sit in their voice.
_ASSIST_RE = re.compile(
    r"(?:"
    r"\b(?:open|launch)\s+(?!up\b)(?:the\s+|my\s+|a\s+)?(?:app|application|browser|site|website|file|folder|document|tab|window|url|settings|calendar|inbox|mail|email)\b"
    r"|\b(?:open|launch|start)\s+(?:up\s+)?(?:chrome|firefox|edge|safari|brave|notepad|terminal|powershell|cmd|explorer|spotify|youtube|gmail|slack|discord|zoom|word|excel|outlook|calculator|vscode|code)\b"
    r"|\bgo to\s+\S+\.\w{2,}\b"
    r"|\b(?:type|paste|click|press)\s+(?:this|that|the|into|in)\b"
    r"|\b(?:see|look at|what's on|whats on)\s+(?:the\s+|my\s+)?screen\b"
    r"|\bscreenshot\b"
    r"|\b(?:set|turn(?:\s+up|\s+down)?)\s+(?:the\s+|my\s+)?volume\b"
    r"|\b(?:mute|unmute)\b"
    r"|\b(?:sleep|shut\s*down|shutdown|restart|reboot|hibernate)\b"
    r"|\block\s+(?:the\s+|my\s+)?(?:pc|computer|machine|workstation)\b"
    r"|\b(?:find|locate)\s+(?:the\s+|my\s+|a\s+)?file\b"
    r"|\b(?:clipboard|copy to clipboard)\b"
    r"|\b(?:terminal|powershell|command prompt|cmd\.exe|run a command|shell command)\b"
    r"|\brun\s+(?:a\s+)?(?:command|script|powershell)\b"
    r"|\b(?:on (?:this|the|my) (?:pc|computer|machine)|this pc)\b"
    r"|\bnotify (?:me )?on (?:the |my )?(?:pc|computer)\b"
    r"|\b(?:close|minimize|maximize)\s+(?:the\s+|that\s+)?window\b"
    r"|\bcontrol (?:media|playback)\b"
    r"|\b(?:play|pause|skip)\s+(?:the\s+)?(?:music|track|song)(?:\s+on)?\b"
    r")",
    re.IGNORECASE,
)

_TWIN_RE = re.compile(
    r"(?:"
    r"\bremember(?:\s+that|\s+when|\s+how|\s+the|\s+my|\s+our)?\b"
    r"|\brecall\b"
    r"|\b(?:file this|capture this|write this down|save this (?:memory|story|to the archive))\b"
    r"|\bwhat did i\b"
    r"|\bwhat do i (?:believe|think|remember|feel)\b"
    r"|\b(?:who (?:was|is|were)|how did i feel|tell me about)\b"
    r"|\b(?:remind me|set (?:a )?reminder)\b"
    r"|\b(?:growing up|childhood|from the (?:archive|vault)|what i filed|in the archive)\b"
    r"|\bmy (?:father|mother|dad|mom|son|daughter|wife|husband|family|childhood|twenties|thirties)\b"
    r"|\b(?:sit with|as (?:you|me)|in my voice)\b"
    r"|\b(?:what(?:'s| is) a story|a story from)\b"
    r")",
    re.IGNORECASE,
)

# "remember to open Chrome" — vault ask plus a PC do.
_REMEMBER_TO_DO_RE = re.compile(
    r"\bremember to\s+(?:open|launch|run|type|click|see|look|set|mute|sleep|shut|restart|find|paste)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OwnerRailDecision:
    route: str
    chip: str
    assist: bool
    twin: bool
    reasons: tuple[str, ...] = ()

    @property
    def legs(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.twin:
            out.append(ROUTE_TWIN)
        if self.assist:
            out.append(ROUTE_ASSIST)
        return tuple(out)


@dataclass
class OwnerTurnResult:
    reply: str
    tool_trace: list[dict] = field(default_factory=list)
    action: Optional[dict] = None
    conversation_id: str = ""
    ts: str = ""
    backend: str = "cloud_claude"
    rail: str = ROUTE_TWIN
    rail_chip: str = CHIP_AS_YOU
    rail_legs: list[str] = field(default_factory=lambda: [ROUTE_TWIN])


def _norm(text: str) -> str:
    raw = (text or "").strip()
    raw = raw.replace("\u2018", "'").replace("\u2019", "'")
    raw = raw.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", raw)


def classify_owner_turn(text: str) -> OwnerRailDecision:
    """Heuristic v1. Cheap keyword/intent only — no LLM."""
    blob = _norm(text)
    if not blob:
        return OwnerRailDecision(
            route=ROUTE_TWIN,
            chip=CHIP_AS_YOU,
            assist=False,
            twin=True,
            reasons=("empty",),
        )

    assist = bool(_ASSIST_RE.search(blob))
    twin = bool(_TWIN_RE.search(blob))
    remember_to_do = bool(_REMEMBER_TO_DO_RE.search(blob))
    reasons: list[str] = []

    if remember_to_do:
        assist = True
        twin = True
        reasons.append("remember_to_do")
    if assist:
        reasons.append("do_pc")
    if twin:
        reasons.append("ask_vault")

    if assist and twin:
        route = ROUTE_BOTH
    elif assist:
        route = ROUTE_ASSIST
    else:
        route = ROUTE_TWIN
        if not twin:
            reasons.append("default_ask")
        twin = True

    return OwnerRailDecision(
        route=route,
        chip=CHIP_BY_ROUTE[route],
        assist=route in {ROUTE_ASSIST, ROUTE_BOTH},
        twin=route in {ROUTE_TWIN, ROUTE_BOTH},
        reasons=tuple(reasons),
    )


def owner_mode_allowed(*, audience: str | None, heir_surface: bool = False) -> bool:
    if heir_surface:
        return False
    return is_owner_audience(audience)


def resolve_chat_mode(
    mode: str | None,
    *,
    audience: str | None = "owner",
    heir_surface: bool = False,
) -> str:
    """Map a requested chat mode onto twin | assistant | owner.

    Unknown modes fall back to twin. Owner rail is refused on heir/caller
    surfaces so they stay Twin-only with no PC tools.
    """
    key = (mode or "twin").strip().lower()
    if key not in VALID_CHAT_MODES:
        key = "twin"
    if key == "owner" and not owner_mode_allowed(audience=audience, heir_surface=heir_surface):
        return "twin"
    return key


def tools_for_owner_leg(
    route: str,
    enabled_ids: set[str],
    **kwargs: Any,
) -> set[str]:
    """PC tools only on the Assist leg. Twin / both-twin never get them."""
    from twin_runtime import tools_for_turn

    leg = (route or "").strip().lower()
    if leg not in {ROUTE_ASSIST, ROUTE_TWIN}:
        raise ValueError("owner rail leg must be assist or twin")
    role = "assistant" if leg == ROUTE_ASSIST else "twin"
    return tools_for_turn(role, enabled_ids, **kwargs)


def merge_owner_replies(twin_reply: str, assist_reply: str) -> str:
    twin_text = (twin_reply or "").strip()
    assist_text = (assist_reply or "").strip()
    if twin_text and assist_text:
        return f"{twin_text}\n\n{assist_text}"
    return twin_text or assist_text or "I heard you."


def owner_response_fields(result: OwnerTurnResult) -> dict[str, Any]:
    return {
        "rail": result.rail,
        "rail_chip": result.rail_chip,
        "rail_legs": list(result.rail_legs),
    }


async def run_owner_turn(
    user: dict,
    message: str,
    *,
    conversation: dict,
    source: str = "web_owner",
    persist: bool = True,
    summarise: bool = True,
    twin_pack: Any = None,
    grounded: bool | None = None,
    persona_hint: str | None = None,
    audience: str = "owner",
) -> OwnerTurnResult:
    """Classify one owner turn, run Twin and/or Assist, persist one receipt."""
    import asyncio

    from twin_runtime import _now_iso, _persist_pair, _safe_summarise, run_twin_turn

    text = (message or "").strip()
    if not text:
        raise ValueError("Empty message")

    if not owner_mode_allowed(audience=audience):
        decision = OwnerRailDecision(
            route=ROUTE_TWIN,
            chip=CHIP_AS_YOU,
            assist=False,
            twin=True,
            reasons=("heir_fence",),
        )
    else:
        decision = classify_owner_turn(text)

    twin_res = None
    assist_res = None

    # Twin / memory first, then Assist if the turn also needs a Do.
    if decision.twin:
        twin_res = await run_twin_turn(
            user,
            text,
            conversation=conversation,
            source=source,
            persist=False,
            summarise=False,
            role="twin",
            twin_pack=twin_pack,
            grounded=grounded,
            persona_hint=persona_hint,
            audience=audience or "owner",
        )
    if decision.assist:
        assist_res = await run_twin_turn(
            user,
            text,
            conversation=conversation,
            source=source,
            persist=False,
            summarise=False,
            role="assistant",
            twin_pack=None,
            grounded=False,
            persona_hint=persona_hint,
            audience="owner",
        )

    reply = merge_owner_replies(
        twin_res.reply if twin_res else "",
        assist_res.reply if assist_res else "",
    )
    tool_trace: list[dict] = []
    if twin_res:
        for row in twin_res.tool_trace:
            tool_trace.append({**row, "leg": ROUTE_TWIN})
    if assist_res:
        for row in assist_res.tool_trace:
            tool_trace.append({**row, "leg": ROUTE_ASSIST})

    action = None
    if assist_res and assist_res.action:
        action = assist_res.action
        if twin_res and twin_res.action:
            action = {**action, "also": twin_res.action}
    elif twin_res and twin_res.action:
        action = twin_res.action

    ts = (
        (assist_res.ts if assist_res and assist_res.ts else "")
        or (twin_res.ts if twin_res and twin_res.ts else "")
        or _now_iso()
    )
    backend = (
        (assist_res.backend if assist_res and assist_res.backend else "")
        or (twin_res.backend if twin_res and twin_res.backend else "")
        or "cloud_claude"
    )
    conversation_id = conversation["conversation_id"]

    if persist:
        await _persist_pair(
            user["user_id"],
            conversation_id,
            text,
            reply,
            ts,
            source=source,
            action=action,
            tool_trace=tool_trace or None,
            rail=decision.route,
            rail_chip=decision.chip,
            rail_legs=list(decision.legs),
        )
        if summarise:
            try:
                asyncio.create_task(_safe_summarise(user["user_id"], conversation_id))
            except Exception:  # noqa: BLE001
                pass

    return OwnerTurnResult(
        reply=reply,
        tool_trace=tool_trace,
        action=action,
        conversation_id=conversation_id,
        ts=ts,
        backend=backend,
        rail=decision.route,
        rail_chip=decision.chip,
        rail_legs=list(decision.legs),
    )
