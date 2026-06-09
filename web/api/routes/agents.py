from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from web.api.models import AgentCreate, AgentMeta, AgentUpdate

router = APIRouter()

SOULS_DIR = Path("config/souls")
AGENTS_DIR = Path("config/agents")


def _ensure_dirs():
    SOULS_DIR.mkdir(parents=True, exist_ok=True)
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def _name_to_id(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip())


# 中英文 role 标准化映射（soul 标题可能是中文，前端统一用英文）
_ROLE_NORMALIZE = {
    "主持人": "moderator",
    "记录员": "scribe",
    "参与者": "participant",
    "观察者": "participant",
    "moderator": "moderator",
    "scribe": "scribe",
    "participant": "participant",
    "host": "moderator",
}


def _normalize_role(raw: str) -> str:
    """将 soul 标题中的 role 统一映射为英文小写。"""
    return _ROLE_NORMALIZE.get(raw, _ROLE_NORMALIZE.get(raw.lower(), "participant"))


def _load_agent_meta(agent_id: str) -> AgentMeta | None:
    meta_path = AGENTS_DIR / f"{agent_id}.json"
    if meta_path.exists():
        return AgentMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
    return None


def _save_agent_meta(meta: AgentMeta):
    _ensure_dirs()
    meta_path = AGENTS_DIR / f"{meta.id}.json"
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")


def _list_all_agents() -> list[AgentMeta]:
    _ensure_dirs()
    agents = []
    seen_ids = set()

    # Load from metadata files
    for f in AGENTS_DIR.glob("*.json"):
        try:
            meta = AgentMeta.model_validate_json(f.read_text(encoding="utf-8"))
            # 标准化 role（兼容旧版 JSON 中可能的中文 role）
            meta.role = _normalize_role(meta.role)
            agents.append(meta)
            seen_ids.add(meta.id)
        except Exception:
            pass

    # Auto-discover from soul files without metadata
    for f in SOULS_DIR.glob("*.md"):
        agent_id = f.stem
        if agent_id not in seen_ids:
            text = f.read_text(encoding="utf-8")
            title_match = re.search(r"^#\s+(.+?)(?:\s*[—–-]\s*(.+))?$", text, re.MULTILINE)
            raw_role = title_match.group(1).strip() if title_match else "participant"
            name = title_match.group(2).strip() if title_match and title_match.group(2) else raw_role
            # 标准化 role 为英文，确保前端一致性
            role = _normalize_role(raw_role)
            if role not in ("moderator", "scribe"):
                meta = AgentMeta(
                    id=agent_id, name=name, role=role,
                    soul_path=str(f),
                )
                _save_agent_meta(meta)
                agents.append(meta)

    # Filter out any moderator or scribe that might have been loaded from JSON
    return [a for a in agents if a.role not in ("moderator", "scribe")]


@router.get("", response_model=list[AgentMeta])
def list_agents():
    return _list_all_agents()


@router.get("/{agent_id}", response_model=AgentMeta)
def get_agent(agent_id: str):
    agents = _list_all_agents()
    for a in agents:
        if a.id == agent_id:
            return a
    raise HTTPException(404, "Agent not found")


@router.get("/{agent_id}/soul")
def get_agent_soul(agent_id: str):
    soul_path = SOULS_DIR / f"{agent_id}.md"
    if not soul_path.exists():
        raise HTTPException(404, "Soul file not found")
    return {"content": soul_path.read_text(encoding="utf-8")}


@router.post("", response_model=AgentMeta)
def create_agent(req: AgentCreate):
    _ensure_dirs()
    agent_id = _name_to_id(req.name)
    if (SOULS_DIR / f"{agent_id}.md").exists():
        raise HTTPException(409, "Agent already exists")

    # Write soul file
    soul_content = req.soul_content or f"# {req.name}\n\n## Basic Profile\n{req.name} is a discussion participant."
    (SOULS_DIR / f"{agent_id}.md").write_text(soul_content, encoding="utf-8")

    meta = AgentMeta(
        id=agent_id, name=req.name, role=req.role,
        group=req.group, tags=req.tags, avatar=req.avatar,
        gender=req.gender, voice=req.voice, voice_description=req.voice_description,
        soul_path=str(SOULS_DIR / f"{agent_id}.md"),
    )
    _save_agent_meta(meta)
    return meta


@router.put("/{agent_id}", response_model=AgentMeta)
def update_agent(agent_id: str, req: AgentUpdate):
    meta = _load_agent_meta(agent_id)
    if not meta:
        raise HTTPException(404, "Agent not found")

    if req.name is not None:
        meta.name = req.name
    if req.role is not None:
        meta.role = req.role
    if req.group is not None:
        meta.group = req.group
    if req.tags is not None:
        meta.tags = req.tags
    if req.avatar is not None:
        meta.avatar = req.avatar
    if req.gender is not None:
        meta.gender = req.gender
    if req.voice is not None:
        meta.voice = req.voice
    if req.voice_description is not None:
        meta.voice_description = req.voice_description
    if req.soul_content is not None:
        soul_path = SOULS_DIR / f"{agent_id}.md"
        soul_path.write_text(req.soul_content, encoding="utf-8")

    _save_agent_meta(meta)
    return meta


@router.delete("/{agent_id}")
def delete_agent(agent_id: str):
    meta_path = AGENTS_DIR / f"{agent_id}.json"
    soul_path = SOULS_DIR / f"{agent_id}.md"

    if not meta_path.exists() and not soul_path.exists():
        raise HTTPException(404, "Agent not found")

    if meta_path.exists():
        meta_path.unlink()
    # Keep soul file as backup, just remove metadata
    return {"deleted": agent_id}
