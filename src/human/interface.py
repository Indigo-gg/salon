from __future__ import annotations

import logging
import queue
from enum import Enum

from src.config import HumanConfig
from src.human.commands import ParsedCommand, format_help, parse_command

logger = logging.getLogger(__name__)


class HumanRole(Enum):
    CHAIR = "chair"
    PARTICIPANT = "participant"
    OBSERVER = "observer"


class HumanInterface:
    def __init__(self, config: HumanConfig):
        self.config = config
        self.role = HumanRole(config.default_role)
        self._input_queue: queue.Queue[str] = queue.Queue()
        self._paused = False
        self._ended = False

    def set_role(self, role: str) -> None:
        self.role = HumanRole(role)

    def signal_input(self, text: str) -> None:
        """Called when human provides input externally."""
        self._input_queue.put(text)

    def check_input_now(self) -> ParsedCommand | None:
        """Non-blocking check for human input."""
        try:
            text = self._input_queue.get_nowait()
        except queue.Empty:
            return None

        parsed = parse_command(text)
        if parsed:
            return parsed
        return ParsedCommand(command="/message", content=text)

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_ended(self) -> bool:
        return self._ended

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def end(self) -> None:
        self._ended = True

    def get_help(self) -> str:
        return format_help()
