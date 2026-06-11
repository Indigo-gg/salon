"""维度状态机——代码控制维度生命周期。

DimensionState 是维度切换的唯一权威数据源。
不依赖 LLM 判断 should_switch，而是基于代码信号（轮次、覆盖率、新颖度）驱动。

支持非线性导航：跳过已自然覆盖的维度，回溯覆盖不足的维度。

用法：
    from src.core.dimension_state import DimensionState

    dim_state = DimensionState(roadmap, config)
    dim_state.advance_round(round_num)
    switch, reason = dim_state.check_switch_needed(round_num, anchor_quality, novelty, speeches_since_novel)
    if switch:
        dim_state.switch_to_next(round_num)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agents.strategist import DiscussionRoadmap, MandatoryDim
    from src.config import SalonConfig

logger = logging.getLogger(__name__)


class DimensionState:
    """维度状态机——代码控制维度生命周期，支持非线性导航。"""

    def __init__(self, roadmap: DiscussionRoadmap, config: SalonConfig):
        self.roadmap = roadmap
        self.dimension_sequence: list[str] = list(roadmap.dimension_sequence)
        self.current_index: int = 0
        self.dim_start_round: int = 0
        self.dim_round_count: int = 0
        self.consecutive_low_coverage: int = 0
        self.max_rounds_per_dim: int = config.discussion.max_rounds_per_dimension
        self.coverage_history: dict[str, list[str]] = {}  # dim_id -> [quality]

    @property
    def current_dimension_id(self) -> str:
        """当前维度 ID。"""
        return self.dimension_sequence[self.current_index]

    @property
    def current_dimension(self) -> MandatoryDim:
        """当前维度的完整信息。"""
        dim_id = self.current_dimension_id
        return next(d for d in self.roadmap.mandatory_dimensions if d.id == dim_id)

    def advance_round(self, round_num: int) -> None:
        """每轮开始时调用，更新维度轮次计数。"""
        self.dim_round_count = round_num - self.dim_start_round

    def check_switch_needed(
        self,
        round_num: int,
        anchor_quality: str = "unknown",
        novelty_score: float = 0.5,
        speeches_since_novel: int = 0,
    ) -> tuple[bool, str]:
        """
        代码级维度切换判断。不依赖 LLM。

        信号来源：
        1. 轮次超时（硬截断）
        2. 连续低质量回应（锚点被敷衍）
        3. 连续低新颖度发言（话题枯竭，复用 SchedulingState 信号）

        Returns:
            (should_switch, reason)
        """
        # 规则1：轮次超时（硬截断）
        if self.dim_round_count >= self.max_rounds_per_dim:
            return True, f"维度已讨论 {self.dim_round_count} 轮，达到上限 {self.max_rounds_per_dim}"

        # 规则2：连续低质量回应（锚点被敷衍）
        if anchor_quality in ("ignored", "token"):
            self.consecutive_low_coverage += 1
            if self.consecutive_low_coverage >= 2:
                return True, f"参与者连续 {self.consecutive_low_coverage} 轮无法实质性回应"
        else:
            self.consecutive_low_coverage = 0

        # 规则3：连续低新颖度——话题在当前维度上已枯竭
        if speeches_since_novel >= 3 and self.dim_round_count >= 2:
            return True, f"连续 {speeches_since_novel} 轮无新观点，当前维度话题枯竭"

        return False, ""

    def switch_to_next(self, round_num: int) -> str | None:
        """
        执行维度切换。支持非线性导航：

        优先级：
        1. 选择 coverage 最低的未充分覆盖维度（而非简单 +1）
        2. 如果所有维度都已充分覆盖，按原始序列推进
        3. 如果所有维度都已覆盖，返回 None
        """
        uncovered = self.get_uncovered_dimensions()
        if uncovered:
            # 选择第一个未充分覆盖的维度（可扩展为优先级排序）
            next_dim = uncovered[0]
            if next_dim in self.dimension_sequence:
                self.current_index = self.dimension_sequence.index(next_dim)
            logger.info(f"[DimensionState] 非线性切换到未覆盖维度: {next_dim}")
        elif self.current_index + 1 < len(self.dimension_sequence):
            # 所有维度都有覆盖，按序列推进
            self.current_index += 1
            logger.info(f"[DimensionState] 线性推进到维度: {self.current_dimension_id}")
        else:
            logger.info("[DimensionState] 所有维度已覆盖，无更多维度")
            return None

        self.dim_start_round = round_num
        self.dim_round_count = 0
        self.consecutive_low_coverage = 0
        return self.current_dimension_id

    def record_coverage(self, dim_id: str, quality: str) -> None:
        """记录维度覆盖质量（由记录员分析结果驱动）。"""
        if dim_id not in self.coverage_history:
            self.coverage_history[dim_id] = []
        self.coverage_history[dim_id].append(quality)

    def get_uncovered_dimensions(self) -> list[str]:
        """获取未充分覆盖的维度列表。"""
        uncovered = []
        for dim_id in self.dimension_sequence:
            qualities = self.coverage_history.get(dim_id, [])
            if not qualities or all(q in ("ignored", "token") for q in qualities[-2:]):
                uncovered.append(dim_id)
        return uncovered

    def is_current_covered(self) -> bool:
        """当前维度是否已充分覆盖。"""
        dim_id = self.current_dimension_id
        qualities = self.coverage_history.get(dim_id, [])
        return bool(qualities) and any(q in ("deep", "surface") for q in qualities[-2:])

    def get_pacing_info(self) -> dict:
        """获取维度进度信息（用于日志和 prompt 注入）。"""
        return {
            "current_dimension_id": self.current_dimension_id,
            "current_dimension_label": self.current_dimension.label,
            "dim_round_count": self.dim_round_count,
            "max_rounds_per_dim": self.max_rounds_per_dim,
            "uncovered_count": len(self.get_uncovered_dimensions()),
            "coverage_history": dict(self.coverage_history),
        }
