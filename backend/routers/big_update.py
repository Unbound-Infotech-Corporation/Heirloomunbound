"""Owner routes for Setup Center, Smart Home, Writing, and Code.

Heirs and callers receive 404. Responses never include a pasted key.
Restore refuses the live Linux data root. These routes do not call the
twin brain and do not change model routing.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from assist_agent import (
    McpRefused,
    draft_message,
    plan_subagent,
    prepare_mcp_arguments,
    prepare_odysseus,
    prepare_research,
    progress,
    tools_for,
    validate_mcp,
)
from code_workspace import (
    CodeEditError,
    CodePrivacyError,
    apply_hunks,
    approve_command,
    assert_project,
    cursor_status,
    diff_hunks,
    list_tree,
    pack_context,
    pick_coder_model,
    plan_agent,
)
from deps import get_current_user
from owner_privacy import OwnerHidden, PrivacyError, json_hides_secret, require_owner
from setup_center import (
    CloudModelDeferred,
    RestoreRefused,
    SecretStore,
    accept_secret,
    apply_restore,
    box_mode_from_env,
    checklist,
    flow_by_id,
    flows,
    inventory_backup,
    plan_restore,
    repair_plan,
)
from smart_home import SmartHomeRefused, classify_discovery, ha_token_url, matter_plan, prepare_action
from writing_assistant import (
    PasteRefused,
    WritingEngineRefused,
    approve_paste,
    check_with_engine,
    lookup,
    paste_back,
    propose_paste,
    rewrite,
)

setup_router = APIRouter(prefix="/setup", tags=["setup-center"])
home_router = APIRouter(prefix="/smart-home", tags=["smart-home"])
writing_router = APIRouter(prefix="/writing", tags=["writing"])
code_router = APIRouter(prefix="/code", tags=["code-workspace"])
assist_router = APIRouter(prefix="/assist", tags=["assist-agent"])

SECRETS = SecretStore()


def _owner(user: dict) -> dict:
    try:
        require_owner(user)
    except OwnerHidden as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    return user


class ChecklistIn(BaseModel):
    signals: dict = Field(default_factory=dict)


class SecretIn(BaseModel):
    flow_id: str
    secret: str
    base_url: str | None = None


class RestoreIn(BaseModel):
    source: str
    dest: str
    confirm: bool = False
    new_machine: bool = False
    data_root: str | None = None


class DiscoverIn(BaseModel):
    records: list[dict] = Field(default_factory=list)


class ActionIn(BaseModel):
    device: dict
    action: str
    value: float | None = None
    unit: str = "F"
    always_allow: bool = False
    approved: bool = False
    critical_confirm: bool = False


class WritingIn(BaseModel):
    text: str = ""
    surface: str = "draft"
    engine: str = "rules"
    languagetool_url: str | None = None
    mode: str | None = None
    word: str | None = None


class PasteIn(BaseModel):
    text: str = ""
    mode: str = "shorter"
    proposal: dict | None = None


class CodeOpenIn(BaseModel):
    path: str


class HunkIn(BaseModel):
    before: str
    after: str = ""
    hunks: list[dict] = Field(default_factory=list)
    accept_ids: list[str] = Field(default_factory=list)


class CommandIn(BaseModel):
    command: str
    approved: bool = False


class CoderIn(BaseModel):
    tags: list[str] = Field(default_factory=list)


class ContextIn(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)
    private_texts: list[str] = Field(default_factory=list)


class DraftIn(BaseModel):
    kind: str = "email"
    to: str = ""
    body: str = ""
    private_texts: list[str] = Field(default_factory=list)


class ResearchIn(BaseModel):
    query: str = ""
    private_texts: list[str] = Field(default_factory=list)
    kind: str = "web_research"


class McpIn(BaseModel):
    spec: dict = Field(default_factory=dict)
    arguments: dict = Field(default_factory=dict)
    private_texts: list[str] = Field(default_factory=list)


@setup_router.post("/checklist")
def post_checklist(body: ChecklistIn, user: dict = Depends(get_current_user)):
    _owner(user)
    return {"steps": checklist(body.signals), "repair": repair_plan(body.signals)}


@setup_router.get("/guides")
def get_guides(user: dict = Depends(get_current_user)):
    _owner(user)
    return {"guides": flows()}


@setup_router.get("/guides/{flow_id}")
def get_guide(flow_id: str, user: dict = Depends(get_current_user)):
    _owner(user)
    row = flow_by_id(flow_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    public = next(item for item in flows() if item["id"] == flow_id)
    return public


@setup_router.post("/secrets")
def post_secret(body: SecretIn, user: dict = Depends(get_current_user)):
    owner = _owner(user)
    try:
        result = accept_secret(body.flow_id, body.secret, base_url=body.base_url)
    except CloudModelDeferred as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("ok"):
        SECRETS.put(owner["user_id"], body.flow_id, body.secret.strip())
    result["keys"] = SECRETS.public_view(owner["user_id"])
    if not json_hides_secret(result, body.secret):
        raise HTTPException(status_code=500, detail="Refusing to return a key.")
    return result


@setup_router.post("/restore/inventory")
def post_inventory(body: RestoreIn, user: dict = Depends(get_current_user)):
    _owner(user)
    try:
        return inventory_backup(Path(body.source))
    except RestoreRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@setup_router.post("/restore/plan")
def post_plan(body: RestoreIn, user: dict = Depends(get_current_user)):
    _owner(user)
    data_root = Path(body.data_root) if body.data_root else None
    return plan_restore(
        Path(body.source),
        Path(body.dest),
        box_mode=box_mode_from_env(),
        data_root=data_root,
        new_machine=body.new_machine,
        confirm=body.confirm,
    )


class EncryptedRestoreIn(BaseModel):
    source: str
    dest: str
    passphrase: str = ""
    confirm: bool = False
    new_machine: bool = False
    data_root: str | None = None


@setup_router.post("/restore/inspect")
def post_inspect(body: RestoreIn, user: dict = Depends(get_current_user)):
    _owner(user)
    from backup_gpg import inspect_backup

    try:
        return inspect_backup(Path(body.source))
    except RestoreRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@setup_router.post("/restore/encrypted")
def post_encrypted(body: EncryptedRestoreIn, user: dict = Depends(get_current_user)):
    _owner(user)
    from backup_gpg import restore_encrypted

    data_root = Path(body.data_root) if body.data_root else None
    try:
        result = restore_encrypted(
            Path(body.source),
            Path(body.dest),
            body.passphrase,
            confirm=body.confirm,
            box_mode=box_mode_from_env(),
            data_root=data_root,
            new_machine=body.new_machine,
        )
    except RestoreRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.passphrase and json_hides_secret(result, body.passphrase) is False:
        raise HTTPException(status_code=500, detail="Refusing to return a passphrase.")
    return result


@setup_router.post("/restore/apply")
def post_apply(body: RestoreIn, user: dict = Depends(get_current_user)):
    _owner(user)
    data_root = Path(body.data_root) if body.data_root else None
    plan = plan_restore(
        Path(body.source),
        Path(body.dest),
        box_mode=box_mode_from_env(),
        data_root=data_root,
        new_machine=body.new_machine,
        confirm=body.confirm,
    )
    try:
        return apply_restore(plan)
    except RestoreRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@home_router.post("/scan")
def post_scan(user: dict = Depends(get_current_user)):
    _owner(user)
    from smart_home import scan_lan_records

    return {"devices": scan_lan_records()}


@home_router.post("/discover")
def post_discover(body: DiscoverIn, user: dict = Depends(get_current_user)):
    _owner(user)
    return {"devices": [classify_discovery(row) for row in body.records], "matter": matter_plan()}


@home_router.post("/act")
def post_act(body: ActionIn, user: dict = Depends(get_current_user)):
    _owner(user)
    try:
        decision = prepare_action(
            body.device,
            body.action,
            body.value,
            unit=body.unit,
            always_allow=body.always_allow,
            approved=body.approved,
            critical_confirm=body.critical_confirm,
        )
    except SmartHomeRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return decision


@home_router.get("/home-assistant")
def get_ha(host: str, user: dict = Depends(get_current_user)):
    _owner(user)
    try:
        return {"url": ha_token_url(host)}
    except SmartHomeRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@writing_router.post("/check")
def post_check(body: WritingIn, user: dict = Depends(get_current_user)):
    _owner(user)
    try:
        return check_with_engine(
            body.text,
            engine=body.engine,
            languagetool_url=body.languagetool_url,
            surface=body.surface,
        )
    except WritingEngineRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@writing_router.post("/rewrite")
def post_rewrite(body: WritingIn, user: dict = Depends(get_current_user)):
    _owner(user)
    try:
        return rewrite(body.text, body.mode or "shorter")
    except WritingEngineRefused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@writing_router.get("/lookup")
def get_lookup(word: str, user: dict = Depends(get_current_user)):
    _owner(user)
    return lookup(word)


@writing_router.post("/paste")
def post_paste(body: PasteIn, user: dict = Depends(get_current_user)):
    _owner(user)
    if body.proposal:
        try:
            approved = approve_paste(body.proposal)
            return {"proposal": approved, "text": paste_back(approved)}
        except PasteRefused as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"proposal": propose_paste(body.text, body.mode)}


@code_router.post("/open")
def post_open(body: CodeOpenIn, user: dict = Depends(get_current_user)):
    _owner(user)
    try:
        assert_project(Path(body.path))
        return list_tree(Path(body.path))
    except CodePrivacyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@code_router.post("/hunks")
def post_hunks(body: HunkIn, user: dict = Depends(get_current_user)):
    _owner(user)
    hunks = body.hunks or diff_hunks(body.before, body.after)
    try:
        updated = apply_hunks(body.before, hunks, body.accept_ids)
    except CodeEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"hunks": hunks, "text": updated}


@code_router.post("/command")
def post_command(body: CommandIn, user: dict = Depends(get_current_user)):
    _owner(user)
    return approve_command(body.command, approved=body.approved)


@code_router.post("/coder")
def post_coder(body: CoderIn, user: dict = Depends(get_current_user)):
    _owner(user)
    return {"coder": pick_coder_model(body.tags), "cursor": cursor_status()}


@code_router.post("/context")
def post_context(body: ContextIn, user: dict = Depends(get_current_user)):
    _owner(user)
    return {"context": pack_context(body.files, body.private_texts), "plan": plan_agent("edit")}


@assist_router.get("/tools")
def get_tools(user: dict = Depends(get_current_user)):
    owner = _owner(user)
    return {"tools": tools_for(role="assistant", audience=owner.get("audience"), heir_surface=False)}


@assist_router.post("/draft")
def post_draft(body: DraftIn, user: dict = Depends(get_current_user)):
    _owner(user)
    try:
        return draft_message(kind=body.kind, to=body.to, body=body.body, private_texts=body.private_texts)
    except PrivacyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@assist_router.post("/research")
def post_research(body: ResearchIn, user: dict = Depends(get_current_user)):
    _owner(user)
    try:
        if body.kind == "odysseus":
            return prepare_odysseus(body.query, body.private_texts)
        return prepare_research(body.query, body.private_texts)
    except PrivacyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@assist_router.post("/mcp")
def post_mcp(body: McpIn, user: dict = Depends(get_current_user)):
    _owner(user)
    try:
        spec = validate_mcp(body.spec)
        arguments = prepare_mcp_arguments(body.arguments, body.private_texts) if body.arguments else {}
    except (McpRefused, PrivacyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"spec": spec, "arguments": arguments, "subagent": plan_subagent("connector"), "progress": progress("ready", "Connector is local.")}
