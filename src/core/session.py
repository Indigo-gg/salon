from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from src.config import SalonConfig


class SessionState(Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    WRAPPING_UP = "wrapping_up"
    FINISHED = "finished"


@dataclass
class SessionMetadata:
    session_id: str
    topic: str
    participants: list[str]  # agent IDs
    state: str
    created_at: str
    mode: str = "salon"
    round_count: int = 0
    archived: bool = False
    finished_at: str | None = None


class SessionManager:
    def __init__(self, config: SalonConfig):
        self.config = config
        self.current_session: SessionMetadata | None = None
        self.session_dir: Path | None = None

    def create_session(self, topic: str, agent_ids: list[str], mode: str = "salon") -> SessionMetadata:
        session_id = f"s_{uuid.uuid4().hex[:8]}"
        self.current_session = SessionMetadata(
            session_id=session_id,
            topic=topic,
            participants=agent_ids,
            state=SessionState.CREATED.value,
            created_at=datetime.now().isoformat(),
            mode=mode,
        )
        self.session_dir = Path(self.config.storage.sessions_dir) / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._save_metadata()
        return self.current_session

    def load_metadata(self) -> SessionMetadata | None:
        """从磁盘加载已有的 metadata.json（用于恢复会话）。"""
        if not self.session_dir:
            return None
        path = self.session_dir / "metadata.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.current_session = SessionMetadata(**data)
            return self.current_session
        except Exception:
            return None

    def update_state(self, state: SessionState) -> None:
        if self.current_session:
            self.current_session.state = state.value
            self._save_metadata()

    def increment_round(self) -> int:
        if self.current_session:
            self.current_session.round_count += 1
            return self.current_session.round_count
        return 0

    def finish(self) -> None:
        if self.current_session:
            self.current_session.state = SessionState.FINISHED.value
            self.current_session.finished_at = datetime.now().isoformat()
            self._save_metadata()

    def _save_metadata(self) -> None:
        if self.current_session and self.session_dir:
            path = self.session_dir / "metadata.json"
            path.write_text(
                json.dumps(self.current_session.__dict__, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get_transcript_path(self) -> Path | None:
        if self.session_dir:
            return self.session_dir / "transcript.jsonl"
        return None

    def get_digest_path(self) -> Path | None:
        if self.session_dir:
            return self.session_dir / "digest.md"
        return None

    def get_whiteboard_path(self) -> Path | None:
        if self.session_dir:
            return self.session_dir / "whiteboard.md"
        return None
