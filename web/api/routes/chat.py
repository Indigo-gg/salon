from __future__ import annotations

import asyncio
import json
import queue
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from web.api.models import CommandRequest

router = APIRouter()

# Active sessions: session_id -> WebOrchestrator-like manager
_active_sessions: dict[str, dict] = {}


def _get_manager(session_id: str) -> dict | None:
    return _active_sessions.get(session_id)


@router.post("/{session_id}/start")
def start_session(session_id: str):
    """Start or resume a dialogue session. Returns immediately; use /stream for SSE."""
    from web.api.manager import create_web_session

    # Check if already running
    if session_id in _active_sessions:
        return {"status": "already_running", "session_id": session_id}

    # Check if session is finished (can't restart finished sessions)
    meta_path = Path("data/sessions") / session_id / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("state") == "finished":
            raise HTTPException(400, "Session is finished. Create a new session instead.")

    manager = create_web_session(session_id)
    if not manager:
        raise HTTPException(404, "Session not found")

    _active_sessions[session_id] = manager
    # Start dialogue in background thread
    thread = threading.Thread(target=manager["run"], daemon=True)
    thread.start()
    return {"status": "started", "session_id": session_id}


@router.get("/{session_id}/stream")
async def stream(session_id: str):
    """SSE endpoint for real-time dialogue messages."""
    manager = _get_manager(session_id)
    if not manager:
        # Create a simple queue for this listener
        manager = {"event_queue": queue.Queue(), "status": "waiting"}
        _active_sessions[session_id] = manager

    event_queue: queue.Queue = manager["event_queue"]

    async def event_generator():
        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: event_queue.get(timeout=30)
                )
                if event is None:
                    break
                yield {
                    "event": event.get("type", "message"),
                    "data": json.dumps(event.get("data", {}), ensure_ascii=False),
                }
                if event.get("type") == "done":
                    break
            except queue.Empty:
                # Send keepalive
                yield {"event": "ping", "data": "{}"}

    return EventSourceResponse(event_generator())


@router.post("/{session_id}/command")
def send_command(session_id: str, req: CommandRequest):
    """Send a human command to the dialogue."""
    manager = _get_manager(session_id)
    if not manager:
        # 尝试重新连接：检查 session 是否存在但不在活跃列表中
        meta_path = Path("data/sessions") / session_id / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("state") == "running":
                # Session 存在但不在活跃列表中（可能服务器重启过）
                # 尝试重新创建 manager
                from web.api.manager import create_web_session
                manager = create_web_session(session_id)
                if manager:
                    _active_sessions[session_id] = manager
                    thread = threading.Thread(target=manager["run"], daemon=True)
                    thread.start()
        if not manager:
            raise HTTPException(404, "No active session")

    cmd_queue = manager.get("cmd_queue")
    if cmd_queue:
        cmd_queue.put(req.command)

    return {"command": req.command, "sent": True}


@router.post("/{session_id}/pause")
def pause_session(session_id: str):
    """Pause a running session (saves state to disk)."""
    manager = _get_manager(session_id)
    if not manager:
        # 尝试重新连接
        meta_path = Path("data/sessions") / session_id / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("state") == "running":
                from web.api.manager import create_web_session
                manager = create_web_session(session_id)
                if manager:
                    _active_sessions[session_id] = manager
                    thread = threading.Thread(target=manager["run"], daemon=True)
                    thread.start()
    if manager:
        pause_fn = manager.get("pause")
        if pause_fn:
            pause_fn()
        # Emit status event immediately so the frontend updates without waiting for the main loop
        event_queue = manager.get("event_queue")
        if event_queue:
            event_queue.put({"type": "status", "data": {"state": "paused", "paused": True}})
        cmd_queue = manager.get("cmd_queue")
        if cmd_queue:
            cmd_queue.put("/pause")
    return {"paused": session_id}


@router.post("/{session_id}/resume")
def resume_session(session_id: str):
    """Resume a paused session."""
    manager = _get_manager(session_id)
    if not manager:
        # 尝试重新连接
        meta_path = Path("data/sessions") / session_id / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("state") in ("running", "paused"):
                from web.api.manager import create_web_session
                manager = create_web_session(session_id)
                if manager:
                    _active_sessions[session_id] = manager
                    thread = threading.Thread(target=manager["run"], daemon=True)
                    thread.start()
        if not manager:
            raise HTTPException(404, "No active session to resume")
    resume_fn = manager.get("resume")
    if resume_fn:
        resume_fn()
    # Emit status event immediately so the frontend updates without waiting for the main loop
    event_queue = manager.get("event_queue")
    if event_queue:
        event_queue.put({"type": "status", "data": {"state": "running", "paused": False}})
    cmd_queue = manager.get("cmd_queue")
    if cmd_queue:
        cmd_queue.put("/resume")
    return {"resumed": session_id}


@router.post("/{session_id}/stop")
def stop_session(session_id: str):
    """Stop a running session."""
    manager = _get_manager(session_id)
    if manager:
        stop_fn = manager.get("stop")
        if stop_fn:
            stop_fn()
        cmd_queue = manager.get("cmd_queue")
        if cmd_queue:
            cmd_queue.put("/end")
        event_queue = manager.get("event_queue")
        if event_queue:
            event_queue.put(None)  # Signal SSE stream to close
    return {"stopped": session_id}
