"""对话模式策略注册与工厂。

用法：
    from src.core.modes import ModeFactory

    strategy = ModeFactory.create("salon")
    strategy.setup(ctx)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.modes.base import CommandSource, DialogueModeStrategy, ModeContext, WebCommandSource
from src.core.modes.debate import DebateModeStrategy
from src.core.modes.debate_state import DebateConfig, DebatePhase, DebateState, Faction
from src.core.modes.interview import InterviewModeStrategy
from src.core.modes.salon import SalonModeStrategy

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 模式注册表
# ---------------------------------------------------------------------------

_MODE_REGISTRY: dict[str, type[DialogueModeStrategy]] = {
    "salon": SalonModeStrategy,
    "interview": InterviewModeStrategy,
    "debate": DebateModeStrategy,
}


class ModeFactory:
    """模式策略工厂。"""

    @staticmethod
    def create(mode_name: str) -> DialogueModeStrategy:
        """根据模式名创建策略实例。"""
        cls = _MODE_REGISTRY.get(mode_name)
        if cls is None:
            available = list(_MODE_REGISTRY.keys())
            raise ValueError(f"Unknown mode: '{mode_name}'. Available: {available}")
        return cls()

    @staticmethod
    def register(name: str, cls: type[DialogueModeStrategy]) -> None:
        """注册新模式。"""
        _MODE_REGISTRY[name] = cls
        logger.info(f"Mode registered: {name}")

    @staticmethod
    def available_modes() -> list[str]:
        """返回所有可用模式名。"""
        return list(_MODE_REGISTRY.keys())


__all__ = [
    "CommandSource",
    "DialogueModeStrategy",
    "ModeContext",
    "ModeFactory",
    "WebCommandSource",
    "SalonModeStrategy",
    "InterviewModeStrategy",
    "DebateModeStrategy",
    "DebateConfig",
    "DebatePhase",
    "DebateState",
    "Faction",
]
