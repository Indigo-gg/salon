"""对话模式策略接口与上下文。

策略模式核心：将模式特定的调度逻辑从编排器中解耦。
每个模式实现 DialogueModeStrategy，通过 ModeContext 访问共享基础设施。
"""

from __future__ import annotations

import queue
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from src.agents.base import BaseAgent
    from src.agents.moderator import ModeratorAgent
    from src.agents.scribe import ScribeAgent
    from src.config import SalonConfig
    from src.core.context_manager import ContextManager
    from src.core.moderator_signal import ModeratorSignalSystem
    from src.core.round_monitor import RoundMonitor
    from src.core.scheduling_state import SchedulingState
    from src.core.session import SessionManager
    from src.llm.client import LLMClient
    from src.memory import MemorySystem
    from src.output.transcript import TranscriptWriter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 命令输入源：统一 CLI 和 Web 的输入接口
# ---------------------------------------------------------------------------

class CommandSource(ABC):
    """统一的命令输入源。CLI 用 stdin，Web 用队列。"""

    @abstractmethod
    def try_get(self) -> str | None:
        """非阻塞获取命令。无命令返回 None。"""

    @abstractmethod
    def wait(self, timeout: float = 30) -> str | None:
        """阻塞等待命令。超时返回 None。"""


class WebCommandSource(CommandSource):
    """基于 queue.Queue 的命令源（Web 模式用）。"""

    def __init__(self, cmd_queue: queue.Queue):
        self._q = cmd_queue

    def try_get(self) -> str | None:
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None

    def wait(self, timeout: float = 30) -> str | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None


# ---------------------------------------------------------------------------
# 模式上下文：策略能访问的共享状态
# ---------------------------------------------------------------------------

@dataclass
class ModeContext:
    """模式策略能访问的上下文 — 只暴露必要接口，不暴露编排器自身。"""

    config: SalonConfig
    participants: list  # list[ParticipantAgent]
    all_agents: list    # list[BaseAgent]
    memory: MemorySystem
    context_manager: ContextManager
    llm: LLMClient
    transcript: TranscriptWriter
    session_manager: SessionManager

    # 输入源（由编排器层注入）
    command_source: CommandSource | None = None

    # 可选组件（由策略在 setup 中决定是否初始化）
    moderator: ModeratorAgent | None = None
    scribe: ScribeAgent | None = None
    search_tool: object | None = None  # WebSearchTool（避免循环导入，用 object 类型）
    tool_registry: object | None = None  # ToolRegistry（避免循环导入，用 object 类型）
    round_monitor: RoundMonitor | None = None
    signal_system: ModeratorSignalSystem | None = None
    scheduling_state: SchedulingState | None = None

    # 运行时状态（由框架层管理）
    round_num: int = 0
    _ended: bool = False
    _paused: bool = False
    decision_history: list = field(default_factory=list)

    # 事件回调（Web 模式用，CLI 模式为 None）
    emit_event: Callable[[str, dict], None] | None = None

    @property
    def max_rounds(self) -> int:
        return self.config.discussion.max_rounds


# ---------------------------------------------------------------------------
# 策略接口
# ---------------------------------------------------------------------------

class DialogueModeStrategy(ABC):
    """对话模式的策略接口。每种模式实现一个子类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """模式名称，如 'salon', 'interview'。"""

    @abstractmethod
    def setup(self, ctx: ModeContext) -> None:
        """初始化模式特定组件（如加载主持人、设置信号系统）。
        在编排器的 run() 早期调用，此时 ctx 的基础组件已就绪。"""

    @abstractmethod
    def execute_round(self, ctx: ModeContext) -> int:
        """执行一个完整的对话轮次。返回新的 round_num。
        策略负责：意图收集、发言权分配、发言执行。
        框架负责：生命周期、记忆管理、收尾。"""

    def should_continue(self, ctx: ModeContext) -> bool:
        """是否继续下一轮。默认：round < max_rounds。"""
        return ctx.round_num < ctx.max_rounds

    def get_mode_commands(self) -> dict[str, str]:
        """返回该模式特有的命令帮助。格式：{命令: 说明}。"""
        return {}

    def on_round_end(self, ctx: ModeContext) -> None:
        """轮次结束后的钩子（可选覆盖）。"""
        pass
