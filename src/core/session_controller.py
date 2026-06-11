"""SessionController——聚合所有状态机，统一调度轮次推进。

SessionController 持有 DimensionState、PhaseState、SchedulingState、QualityGate，
统一调度它们的 update() 顺序和信号传递。salon.py 通过 SessionController
获取 RoundDirective，不再直接操作各状态机。

用法：
    from src.core.session_controller import SessionController

    ctrl = SessionController(roadmap, config, scheduling_state)
    directive = ctrl.advance_round(round_num, anchor_quality)
    # directive.phase, directive.dimension_id, directive.should_switch_dim ...
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.dimension_state import DimensionState
from src.core.phase_state import PhaseState
from src.core.quality_gate import QualityGate

if TYPE_CHECKING:
    from src.agents.strategist import DiscussionRoadmap, StrategyOutput
    from src.config import SalonConfig
    from src.core.scheduling_state import SchedulingState

logger = logging.getLogger(__name__)


class RoundDirective:
    """SessionController 输出的本轮指令集——execute_round() 的唯一输入。

    替代原来散落在各处的状态查询，集中提供本轮所有状态决策结果。
    """

    def __init__(
        self,
        dimension_id: str,
        dimension_label: str,
        phase: str,
        should_switch_dim: bool,
        switch_reason: str,
        uncovered_dims: list[str],
    ):
        self.dimension_id = dimension_id
        self.dimension_label = dimension_label
        self.phase = phase
        self.should_switch_dim = should_switch_dim
        self.switch_reason = switch_reason
        self.uncovered_dims = uncovered_dims

    def __repr__(self) -> str:
        return (
            f"RoundDirective(dim={self.dimension_id}, phase={self.phase}, "
            f"switch={self.should_switch_dim}, uncovered={len(self.uncovered_dims)})"
        )


class SessionController:
    """聚合所有状态机，统一调度轮次推进。"""

    def __init__(
        self,
        roadmap: DiscussionRoadmap,
        config: SalonConfig,
        scheduling_state: SchedulingState,
    ):
        self.dimension = DimensionState(roadmap, config)
        self.phase = PhaseState(config)
        self.scheduling = scheduling_state
        self.quality_gate = QualityGate(config)
        self._last_directive: RoundDirective | None = None

    def advance_round(
        self,
        round_num: int,
        anchor_quality: str = "unknown",
    ) -> RoundDirective:
        """
        每轮开始时调用，返回本轮的完整指令集。

        调度顺序（顺序敏感）：
        1. DimensionState.advance_round() — 更新维度轮次计数
        2. DimensionState.check_switch_needed() — 检查维度切换
        3. PhaseState.update() — 更新阶段（感知维度状态变化）
        4. 组装 RoundDirective — 供 execute_round() 使用
        """
        # 1. 维度推进
        self.dimension.advance_round(round_num)

        # 2. 维度切换检查
        novelty = self.scheduling.get_latest_novelty()
        speeches_since_novel = self.scheduling.speeches_since_novel
        switch, reason = self.dimension.check_switch_needed(
            round_num, anchor_quality, novelty, speeches_since_novel
        )
        if switch:
            self.dimension.switch_to_next(round_num)

        # 3. 阶段推进
        uncovered = self.dimension.get_uncovered_dimensions()
        dim_covered = self.dimension.is_current_covered()

        # 检查 SchedulingState 的枯竭信号
        exhaustion_signal = self._check_exhaustion()

        new_phase = self.phase.update(
            round_num=round_num,
            dimension_fully_covered=dim_covered,
            uncovered_dims=len(uncovered),
            exhaustion_signal=exhaustion_signal,
        )

        # 4. 组装指令
        directive = RoundDirective(
            dimension_id=self.dimension.current_dimension_id,
            dimension_label=self.dimension.current_dimension.label,
            phase=new_phase,
            should_switch_dim=switch,
            switch_reason=reason,
            uncovered_dims=uncovered,
        )
        self._last_directive = directive

        logger.info(f"[SessionController] Round {round_num}: {directive}")
        return directive

    def _check_exhaustion(self) -> bool:
        """检查 SchedulingState 是否检测到话题枯竭。

        当连续低新颖度发言超过动态阈值时，返回 True。
        PhaseState 会据此判断是否需要从 EXPLORATION → DEEPENING。
        """
        dyn = self.scheduling.dynamic_thresholds(
            len(self.scheduling.consecutive_silence) + 1  # 估算参与者数
        )
        return self.scheduling.speeches_since_novel >= dyn.get("topic_shift", 12)

    def validate_strategy(self, output: StrategyOutput) -> StrategyOutput:
        """战略家输出后，运行质量门验证。"""
        return self.quality_gate.validate_strategy_output(
            output, self.dimension, self.scheduling
        )

    def record_anchor_coverage(self, quality: str) -> None:
        """记录当前维度的锚点覆盖质量（由记录员分析结果驱动）。"""
        self.dimension.record_coverage(self.dimension.current_dimension_id, quality)

    @property
    def last_directive(self) -> RoundDirective | None:
        """上一轮的指令（供其他组件查询当前状态）。"""
        return self._last_directive
