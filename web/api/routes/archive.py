from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

router = APIRouter()

SESSIONS_DIR = Path("data/sessions")

# System agents that should not appear as participant sprites in the UI
_SYSTEM_AGENT_IDS = {"moderator", "scribe"}


@router.get("")
def list_archives():
    if not SESSIONS_DIR.exists():
        return []
    archives = []
    for d in SESSIONS_DIR.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("archived", False) or meta.get("state") == "finished":
                archives.append({
                    "session_id": meta.get("session_id", d.name),
                    "topic": meta.get("topic", ""),
                    "participants": [p for p in meta.get("participants", []) if p not in _SYSTEM_AGENT_IDS],
                    "round_count": meta.get("round_count", 0),
                    "created_at": meta.get("created_at", ""),
                    "finished_at": meta.get("finished_at", ""),
                })
        except Exception:
            continue
    archives.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    return archives


@router.get("/{session_id}")
def get_archive(session_id: str):
    session_dir = SESSIONS_DIR / session_id
    meta_path = session_dir / "metadata.json"
    if not meta_path.exists():
        raise HTTPException(404, "Archive not found")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # Filter out system agents (moderator, scribe) from participants
    meta["participants"] = [p for p in meta.get("participants", []) if p not in _SYSTEM_AGENT_IDS]

    # Load transcript
    transcript_path = session_dir / "transcript.jsonl"
    messages = []
    if transcript_path.exists():
        for line in transcript_path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                messages.append(json.loads(line))

    # Load whiteboard
    wb_path = session_dir / "whiteboard.md"
    whiteboard = wb_path.read_text(encoding="utf-8") if wb_path.exists() else ""

    # Load digest
    digest_path = session_dir / "digest.md"
    digest = digest_path.read_text(encoding="utf-8") if digest_path.exists() else ""

    # Load notebooks
    nb_dir = session_dir / "notebooks"
    notebooks = {}
    if nb_dir.exists():
        for f in nb_dir.glob("*.md"):
            notebooks[f.stem] = f.read_text(encoding="utf-8")

    return {
        "metadata": meta,
        "messages": messages,
        "whiteboard": whiteboard,
        "digest": digest,
        "notebooks": notebooks,
    }


@router.delete("/{session_id}")
def delete_archive(session_id: str):
    import shutil

    session_dir = SESSIONS_DIR / session_id
    if not session_dir.exists():
        raise HTTPException(404, "Archive not found")
    shutil.rmtree(session_dir)
    return {"ok": True}


@router.get("/{session_id}/export")
def export_archive(
    session_id: str,
    format: str = Query("html", pattern="^(md|html|pdf)$"),
    include_reasoning: bool = Query(False),
):
    """导出对话记录为 Markdown / HTML / PDF 文件。"""
    session_dir = SESSIONS_DIR / session_id
    if not session_dir.exists():
        raise HTTPException(404, "Archive not found")

    # 延迟导入，避免循环依赖
    import sys
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from src.output.export import export_session

    try:
        content, filename, media_type = export_session(
            session_dir, fmt=format, include_reasoning=include_reasoning,
        )
        if isinstance(content, str):
            content = content.encode("utf-8")
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{session_id}/memory")
def get_archive_memory(session_id: str):
    """从转录中提取每个 agent 的会话记忆（立场、贡献、分歧）。"""
    session_dir = SESSIONS_DIR / session_id
    transcript_path = session_dir / "transcript.jsonl"
    if not transcript_path.exists():
        return {}  # 活跃会话可能还没有 transcript

    # 解析转录
    messages = []
    for line in transcript_path.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            messages.append(json.loads(line))

    # 按 agent 构建记忆
    _SYSTEM = {"moderator", "scribe", "system", "human"}
    agent_memories: dict[str, dict] = {}

    for msg in messages:
        aid = msg.get("agent_id", "")
        if aid in _SYSTEM:
            continue
        if msg.get("speech_type") == "intent":
            continue

        if aid not in agent_memories:
            agent_memories[aid] = {
                "agent_id": aid,
                "name": msg.get("agent_name", aid),
                "expressed_stances": [],
                "unique_contributions": [],
                "active_disagreements": [],
            }

        mem = agent_memories[aid]
        thought = msg.get("thought") or ""
        speech = msg.get("content") or ""
        speech_type = msg.get("speech_type", "")
        mentions = msg.get("mentions") or []

        # 提取立场（thought 的第一个句子，fallback 到 speech 前 80 字）
        import re
        stance = None
        if thought:
            m = re.search(r'^(.{5,}?)[。？！.?!\n]', thought.strip())
            stance = m.group(1).strip()[:80] if m else thought.strip()[:80]
        if not stance and speech:
            stance = speech.strip()[:80]
        if stance:
            mem["expressed_stances"].append(stance)
            if len(mem["expressed_stances"]) > 5:
                mem["expressed_stances"] = mem["expressed_stances"][-5:]

        # 独特贡献
        if speech_type in ("New_Angle", "Dissent") and speech:
            contrib = speech.strip()[:60]
            mem["unique_contributions"].append(contrib)
            if len(mem["unique_contributions"]) > 5:
                mem["unique_contributions"] = mem["unique_contributions"][-5:]

        # 活跃分歧
        if speech_type == "Dissent" and mentions:
            desc = speech.strip()[:40]
            mem["active_disagreements"].append(f"与{mentions[0]}：{desc}")
            if len(mem["active_disagreements"]) > 3:
                mem["active_disagreements"] = mem["active_disagreements"][-3:]

    return agent_memories
