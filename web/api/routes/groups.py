from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from web.api.models import GroupCreate, GroupMeta, GroupUpdate

router = APIRouter()

GROUPS_DIR = Path("config/groups")
AGENTS_DIR = Path("config/agents")


def _ensure_dirs():
    GROUPS_DIR.mkdir(parents=True, exist_ok=True)
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_group_meta(group_id: str) -> GroupMeta | None:
    meta_path = GROUPS_DIR / f"{group_id}.json"
    if meta_path.exists():
        return GroupMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
    return None


def _save_group_meta(meta: GroupMeta):
    _ensure_dirs()
    meta_path = GROUPS_DIR / f"{meta.id}.json"
    meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")


def _list_all_groups() -> list[GroupMeta]:
    _ensure_dirs()
    groups = []
    for f in GROUPS_DIR.glob("*.json"):
        try:
            meta = GroupMeta.model_validate_json(f.read_text(encoding="utf-8"))
            groups.append(meta)
        except Exception:
            pass
    return groups


def _bootstrap_groups_from_agents():
    """Auto-create groups from existing agent group strings."""
    if not AGENTS_DIR.exists():
        return
    existing = {g.id for g in _list_all_groups()}
    for f in AGENTS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            group_name = data.get("group", "")
            if group_name and group_name not in existing:
                meta = GroupMeta(id=group_name, name=group_name)
                _save_group_meta(meta)
                existing.add(group_name)
        except Exception:
            pass


@router.get("", response_model=list[GroupMeta])
def list_groups():
    _bootstrap_groups_from_agents()
    return _list_all_groups()


@router.get("/{group_id}", response_model=GroupMeta)
def get_group(group_id: str):
    _bootstrap_groups_from_agents()
    meta = _load_group_meta(group_id)
    if not meta:
        raise HTTPException(404, "Group not found")
    return meta


@router.post("", response_model=GroupMeta)
def create_group(req: GroupCreate):
    _ensure_dirs()
    group_id = "grp_" + uuid.uuid4().hex[:8]
    if (GROUPS_DIR / f"{group_id}.json").exists():
        raise HTTPException(409, "Group already exists")
    meta = GroupMeta(id=group_id, name=req.name, description=req.description, emoji=req.emoji)
    _save_group_meta(meta)
    return meta


@router.put("/{group_id}", response_model=GroupMeta)
def update_group(group_id: str, req: GroupUpdate):
    meta = _load_group_meta(group_id)
    if not meta:
        raise HTTPException(404, "Group not found")

    old_name = meta.name
    if req.name is not None:
        meta.name = req.name
    if req.description is not None:
        meta.description = req.description
    if req.emoji is not None:
        meta.emoji = req.emoji

    _save_group_meta(meta)

    return meta


def _update_agents_group_name(old_name: str, new_name: str):
    """Update all agents whose group matches old_name to new_name."""
    if not AGENTS_DIR.exists():
        return
    for f in AGENTS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("group") == old_name:
                data["group"] = new_name
                f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


@router.delete("/{group_id}")
def delete_group(group_id: str):
    meta = _load_group_meta(group_id)
    if not meta:
        raise HTTPException(404, "Group not found")

    # Clear group field on member agents
    agents_updated = 0
    if AGENTS_DIR.exists():
        for f in AGENTS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("group") == group_id:
                    data["group"] = ""
                    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    agents_updated += 1
            except Exception:
                pass

    # Delete group file
    (GROUPS_DIR / f"{group_id}.json").unlink(missing_ok=True)
    return {"deleted": group_id, "agents_updated": agents_updated}
