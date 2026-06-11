"""讨论阶段状态机——代码控制阶段转移。

PhaseState 是 phase 的唯一权威数据源（SSOT）。
- SchedulingState 不再直接修改 decision.phase，改为发送 exhaustion_signal
- AgendaDecision.phase 字段将被移除，LLM 不再决定阶段
- salon.py 和 moderator.py 统一从 PhaseState 读取当前阶段

用法：
    from src.core.phase_state import PhaseState

    phase_state = PhaseState(config)
    new_phase = phase_state.update(
        round_num=round_num,
        dimension_fully_covered=True,
        uncovered_dims=0,
        exhaustion_signal=False,
    )
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import SalonConfig

logger = logging.getLogger(__name__)


class PhaseState:
    """讨论阶段状态机——代码控制阶段转移（phase 唯一权威数据源）。"""

    # 合法的状态转移图
    VALID_TRANSITIONS: dict[str, set[str]] = {
        "OPENING":     {"EXPLORATION"},
        "EXPLORATION": {"DEEPENING", "CONVERGENCE"},
        "DEEPENING":   {"EXPLORATION", "CONVERGENCE"},
        "CONVERGENCE": {"DEEPENING", "CLOSING"},
        "CLOSING":     set(),  # 终态，不可逆
    }

    def __init__(self, config: SalonConfig):
        self.phase: str = "OPENING"
        self.max_rounds: int = config.discussion.max_rounds
        self.participants_count: int = len(getattr(config, 'agents', [])) or config.discussion.default_participant_count
        self.phase_start_round: int = 0
        # 从配置读取收尾窗口参数（复用 SchedulingState 的配置，避免两套不一致）
        monitor_cfg = config.monitor
        self.closing_window_min: int = monitor_cfg.closing_window_min
        self.closing_window_max: int = monitor_cfg.closing_window_max

    def get_closing_window(self) -> int:
        """收尾窗口：最后 N 轮自动进入 CONVERGENCE。

        使用配置中的 closing_window_min / closing_window_max，
        与 SchedulingState 共用同一套配置值。
        """
        raw = math.ceil(math.sqrt(self.max_rounds))
        return max(self.closing_window_min, min(self.closing_window_max, raw))

    def update(
        self,
        round_num: int,
        dimension_fully_covered: bool = False,
        uncovered_dims: int = 0,
        exhaustion_signal: bool = False,
    ) -> str:
        """
        代码级阶段转移。LLM 的建议不参与决策。

        信号来源：
        - round_num：轮次推进
        - dimension_fully_covered：DimensionState 提供
        - uncovered_dims：DimensionState 提供
        - exhaustion_signal：SchedulingState 提供（替代直接修改 decision.phase）

        Returns:
            新的阶段名称
        """
        rounds_left = self.max_rounds - round_num
        closing_window = self.get_closing_window()

        # 规则1：CLOSING 是终态，不可逆
        if self.phase == "CLOSING":
            return "CLOSING"

        # 规则2：最后 1 轮强制 CLOSING
        if rounds_left <= 1:
            return self._try_transition("CLOSING")

        # 规则3：收尾窗口内，无未覆盖维度 → CONVERGENCE
        if rounds_left <= closing_window and uncovered_dims == 0:
            return self._try_transition("CONVERGENCE")

        # 规则4：收尾窗口内，有未覆盖维度 → 保持当前阶段（优先切维度）
        if rounds_left <= closing_window:
            pass  # 不切阶段，让维度状态机处理

        # 规则5：OPENING → EXPLORATION（至少 2 轮后）
        if self.phase == "OPENING" and round_num >= 2:
            return self._try_transition("EXPLORATION")

        # 规则6：EXPLORATION ↔ DEEPENING（基于维度覆盖深度）
        if self.phase == "EXPLORATION" and dimension_fully_covered:
            return self._try_transition("DEEPENING")
        if self.phase == "DEEPENING" and not dimension_fully_covered:
            return self._try_transition("EXPLORATION")

        # 规则7：SchedulingState 的枯竭信号 → DEEPENING
        # （替代原 SchedulingState.post_process() 直接修改 decision.phase 的做法）
        if exhaustion_signal and self.phase in ("EXPLORATION", "DEEPENING"):
            return self._try_transition("DEEPENING")

        # 规则8：CONVERGENCE → DEEPENING（如果发现新维度需要探索）
        if self.phase == "CONVERGENCE" and uncovered_dims > 0 and rounds_left > closing_window:
            return self._try_transition("DEEPENING")

        # 默认：保持当前阶段
        return self.phase

    def _try_transition(self, new_phase: str) -> str:
        """尝试状态转移，验证合法性。非法转移保持当前阶段。"""
        valid = self.VALID_TRANSITIONS.get(self.phase, set())
        if new_phase in valid:
            old = self.phase
            self.phase = new_phase
            self.phase_start_round = 0
            if old != new_phase:
                logger.info(f"[PhaseState] 阶段转移: {old} → {new_phase}")
        else:
            logger.debug(f"[PhaseState] 非法转移: {self.phase} → {new_phase}，保持当前阶段")
        return self.phase
