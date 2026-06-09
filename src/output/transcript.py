from __future__ import annotations

import json
from pathlib import Path

from src.memory.stream import Message


class TranscriptWriter:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_message(self, message: Message) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        messages = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    messages.append(json.loads(line))
        return messages

    def get_transcript_text(self) -> str:
        messages = self.read_all()
        lines = []
        for msg in messages:
            lines.append(f"[Round {msg['round']}] {msg['agent_name']}: {msg['content']}")
        return "\n".join(lines)
