from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from web.api.models import SessionCreate, SessionInfo

router = APIRouter()

SESSIONS_DIR = Path("data/sessions")
AGENTS_DIR = Path("config/agents")
SOULS_DIR = Path("config/souls")


def _load_agent_mappings() -> tuple[dict[str, str], dict[str, str]]:
    """Build name↔id mappings from config/agents/*.json and config/souls/*.md."""
    name_to_id: dict[str, str] = {}
    id_to_name: dict[str, str] = {}

    # 1. Load from agent metadata JSON files (authoritative source)
    if AGENTS_DIR.exists():
        for f in AGENTS_DIR.glob("*.json"):
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
                aid = meta.get("id", f.stem)
                aname = meta.get("name", "")
                if aid and aname:
                    id_to_name[aid] = aname
                    name_to_id[aname] = aid
            except Exception:
                continue

    # 2. Fallback: discover from soul files not yet covered
    if SOULS_DIR.exists():
        for f in SOULS_DIR.glob("*.md"):
            agent_id = f.stem
            if agent_id in id_to_name:
                continue
            try:
                text = f.read_text(encoding="utf-8")
                title_match = re.search(r"^#\s+(.+?)(?:\s*[—–-]\s*(.+))?$", text, re.MULTILINE)
                name = title_match.group(2).strip() if title_match and title_match.group(2) else (
                    title_match.group(1).strip() if title_match else agent_id
                )
                id_to_name[agent_id] = name
                name_to_id[name] = agent_id
            except Exception:
                continue

    # 3. Legacy compatibility
    if "moderator" in id_to_name:
        for legacy in ("苏格拉底", "主持人"):
            if legacy not in name_to_id:
                name_to_id[legacy] = "moderator"

    return name_to_id, id_to_name


# Build mappings once at module load
_NAME_TO_ID, _ID_TO_NAME = _load_agent_mappings()


def _resolve_agent_ids(participants: list[str]) -> list[str]:
    """Resolve participant names (Chinese or English) to agent IDs."""
    result = []
    for p in participants:
        if p in _NAME_TO_ID:
            result.append(_NAME_TO_ID[p])
        elif p in _ID_TO_NAME:
            result.append(p)  # already an ID
        else:
            result.append(p)  # keep as-is
    return result


def _resolve_agent_names(agent_ids: list[str]) -> list[str]:
    """Resolve agent IDs to display names."""
    result = []
    for a in agent_ids:
        if a in _ID_TO_NAME:
            result.append(_ID_TO_NAME[a])
        elif a in _NAME_TO_ID:
            result.append(a)  # already a name
        else:
            result.append(a)
    return result


def _list_sessions(archived: bool = False) -> list[SessionInfo]:
    if not SESSIONS_DIR.exists():
        return []

    sessions = []
    for d in SESSIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            is_archived = meta.get("archived", False)
            if is_archived != archived:
                continue
            participants = meta.get("participants", [])
            agent_ids = _resolve_agent_ids(participants)
            sessions.append(SessionInfo(
                session_id=meta.get("session_id", d.name),
                topic=meta.get("topic", ""),
                agent_ids=agent_ids,
                agent_names=_resolve_agent_names(agent_ids),
                mode=meta.get("mode", "salon"),
                state=meta.get("state", "unknown"),
                round_count=meta.get("round_count", 0),
                created_at=meta.get("created_at", ""),
                archived=is_archived,
                mode_config=meta.get("mode_config"),
            ))
        except Exception:
            continue

    sessions.sort(key=lambda s: s.created_at, reverse=True)
    return sessions


def detect_stale_sessions() -> int:
    """Find sessions marked 'running' with no active orchestrator and mark them as 'paused'.

    This runs on server startup to recover from crashes.
    Returns the number of sessions fixed.
    """
    from web.api.routes.chat import _active_sessions

    if not SESSIONS_DIR.exists():
        return 0

    fixed = 0
    for d in SESSIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("state") != "running":
                continue
            session_id = meta.get("session_id", d.name)
            if session_id in _active_sessions:
                continue  # actually running
            # Mark as paused so it can be resumed
            round_count = meta.get("round_count", 0)
            meta["state"] = "paused" if round_count > 0 else "created"
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            fixed += 1
        except Exception:
            continue

    return fixed


@router.post("", response_model=SessionInfo)
def create_session(req: SessionCreate):
    import uuid
    from datetime import datetime

    agent_ids = list(req.agent_ids)
    resolved = _resolve_agent_ids(agent_ids)

    session_id = f"s_{uuid.uuid4().hex[:8]}"
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "session_id": session_id,
        "topic": req.topic,
        "participants": agent_ids,
        "mode": req.mode,
        "state": "created",
        "round_count": 0,
        "created_at": datetime.now().isoformat(),
        "archived": False,
    }
    if req.mode_config:
        meta["mode_config"] = req.mode_config
    (session_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return SessionInfo(
        session_id=session_id,
        topic=req.topic,
        agent_ids=agent_ids,
        agent_names=_resolve_agent_names(agent_ids),
        mode=req.mode,
        state="created",
        round_count=0,
        created_at=meta["created_at"],
        archived=False,
        mode_config=req.mode_config,
    )


@router.get("", response_model=list[SessionInfo])
def list_sessions():
    return _list_sessions(archived=False)


@router.get("/{session_id}", response_model=SessionInfo)
def get_session(session_id: str):
    meta_path = SESSIONS_DIR / session_id / "metadata.json"
    if not meta_path.exists():
        raise HTTPException(404, "Session not found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    participants = meta.get("participants", [])
    agent_ids = _resolve_agent_ids(participants)
    return SessionInfo(
        session_id=meta.get("session_id", session_id),
        topic=meta.get("topic", ""),
        agent_ids=agent_ids,
        agent_names=_resolve_agent_names(agent_ids),
        mode=meta.get("mode", "salon"),
        state=meta.get("state", "unknown"),
        round_count=meta.get("round_count", 0),
        created_at=meta.get("created_at", ""),
        archived=meta.get("archived", False),
        mode_config=meta.get("mode_config"),
    )


@router.get("/{session_id}/messages")
def get_session_messages(session_id: str):
    transcript_path = SESSIONS_DIR / session_id / "transcript.jsonl"
    if not transcript_path.exists():
        return []
    messages = []
    for line in transcript_path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            messages.append(json.loads(line))
    return messages


@router.get("/{session_id}/whiteboard")
def get_session_whiteboard(session_id: str):
    wb_path = SESSIONS_DIR / session_id / "whiteboard.md"
    if not wb_path.exists():
        return {"content": ""}
    return {"content": wb_path.read_text(encoding="utf-8")}


@router.get("/{session_id}/digest")
def get_session_digest(session_id: str):
    digest_path = SESSIONS_DIR / session_id / "digest.md"
    if not digest_path.exists():
        return {"content": ""}
    return {"content": digest_path.read_text(encoding="utf-8")}


@router.get("/{session_id}/notebooks")
def get_session_notebooks(session_id: str):
    nb_dir = SESSIONS_DIR / session_id / "notebooks"
    if not nb_dir.exists():
        return {}
    notebooks = {}
    for f in nb_dir.glob("*.md"):
        notebooks[f.stem] = f.read_text(encoding="utf-8")
    return notebooks


@router.put("/{session_id}/archive")
def archive_session(session_id: str):
    meta_path = SESSIONS_DIR / session_id / "metadata.json"
    if not meta_path.exists():
        raise HTTPException(404, "Session not found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["archived"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"archived": session_id}


@router.delete("/{session_id}")
def delete_session(session_id: str):
    import shutil
    import time
    from web.api.routes.chat import _active_sessions

    if session_id in _active_sessions:
        try:
            _active_sessions[session_id].stop()
            del _active_sessions[session_id]
            time.sleep(0.1)
        except Exception:
            pass

    session_dir = SESSIONS_DIR / session_id
    if not session_dir.exists():
        raise HTTPException(404, "Session not found")
    
    shutil.rmtree(session_dir, ignore_errors=True)
    return {"deleted": session_id}
