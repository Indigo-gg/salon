from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.api.routes import agents, sessions, chat, config, archive, tts, groups

app = FastAPI(title="Salon API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(archive.router, prefix="/api/archives", tags=["archives"])
app.include_router(tts.router, prefix="/api/tts", tags=["tts"])
app.include_router(groups.router, prefix="/api/groups", tags=["groups"])

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def startup():
    from web.api.routes.sessions import detect_stale_sessions
    fixed = detect_stale_sessions()
    if fixed:
        print(f"[startup] Recovered {fixed} stale session(s)")


# Serve frontend static files (must be last — catches all non-/api routes)
frontend_dist = project_root / "web" / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
