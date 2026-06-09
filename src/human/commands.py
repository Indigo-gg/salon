from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedCommand:
    command: str
    target: str | None = None
    content: str | None = None


COMMANDS = {
    "/pause": "Pause discussion",
    "/resume": "Resume discussion",
    "/ask": "Ask a specific role a question. Format: /ask @role question",
    "/topic": "Introduce new topic. Format: /topic new topic",
    "/summarize": "Trigger mid-discussion summary",
    "/whiteboard": "View current whiteboard",
    "/notebook": "View agent memory. /notebook or /notebook @role",
    "/memory": "Open memory web page. Shows card UI with tabs.",
    "/monitor": "View decision history. /monitor [all|signals]",
    "/end": "End discussion",
    "/inject": "Inject private instruction. Format: /inject @role instruction",
    "/skip": "Skip current topic",
    "/status": "View discussion status",
    "/help": "Show available commands",
}


def parse_command(text: str) -> ParsedCommand | None:
    text = text.strip()
    if not text.startswith("/"):
        return None

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if cmd not in COMMANDS:
        return None

    target = None
    content = rest

    # Extract @target
    target_match = re.search(r"@(\w+)", rest)
    if target_match:
        target = target_match.group(1)
        content = rest[target_match.end():].strip()

    return ParsedCommand(command=cmd, target=target, content=content or None)


def format_help() -> str:
    lines = ["Available commands:"]
    for cmd, desc in COMMANDS.items():
        lines.append(f"  {cmd:15s} {desc}")
    return "\n".join(lines)
