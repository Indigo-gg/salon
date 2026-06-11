"""质量门——代码级验证 LLM 输出是否合规。

QualityGate 在 LLM 输出之后、状态转移之前运行，
交叉验证 LLM 的判断（如锚点回应质量），拦截明显错误。

用法：
    from src.core.quality_gate import QualityGate

    gate = QualityGate(config)
    validated = gate.validate_anchor_coverage(coverage, novelty_score, dim_round_count)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.models import AnchorCoverageCheck

if TYPE_CHECKING:
    from src.agents.strategist import DiscussionRoadmap, StrategyOutput
    from src.config import SalonConfig
    from src.core.dimension_state import DimensionState
    from src.core.scheduling_state import SchedulingState

logger = logging.getLogger(__name__)


class QualityGate:
    """代码级质量验证——验证 LLM 输出是否合规。"""

    def __init__(self, config: SalonConfig):
        self.novelty_low_threshold: float = config.monitor.novelty_low_threshold

    def validate_anchor_coverage(
        self,
        coverage: AnchorCoverageCheck,
        novelty_score: float,
        dim_round_count: int,
    ) -> AnchorCoverageCheck:
        """代码级锚点回应质量验证——交叉检查 LLM 判断。

        使用配置中的 novelty_low_threshold，而非硬编码阈值。
        """
        # 如果 LLM 说"深入回应"但新颖度很低，可能判断有误
        if coverage.quality == "deep" and novelty_score < self.novelty_low_threshold:
            logger.warning(
                f"[QualityGate] LLM 判断 deep 但 novelty={novelty_score:.2f} "
                f"< {self.novelty_low_threshold}，降级为 surface"
            )
            coverage.quality = "surface"

        # 如果 LLM 说"忽略"但维度才刚开始（第1轮），可能是误判
        if coverage.quality == "ignored" and dim_round_count <= 1:
            logger.warning("[QualityGate] 维度第1轮就被判 ignored，标记为 unknown")
            coverage.quality = "unknown"

        # 重新计算 needs_escalation
        coverage.needs_escalation = (
            coverage.quality in ("ignored", "token")
            or (coverage.quality == "surface" and dim_round_count >= 3)
        )

        return coverage

    @staticmethod
    def validate_roadmap(roadmap: DiscussionRoadmap, total_rounds: int) -> DiscussionRoadmap:
        """代码级路线图验证——检查维度数量和序列完整性。"""
        dims = roadmap.mandatory_dimensions

        # 维度数量检查
        if len(dims) < 2:
            logger.warning(f"[QualityGate] 维度数量过少({len(dims)})，可能讨论不完整")
        if len(dims) > 5:
            logger.warning(f"[QualityGate] 维度数量过多({len(dims)})，截断为5个")
            roadmap.mandatory_dimensions = dims[:5]
            roadmap.dimension_sequence = roadmap.dimension_sequence[:5]

        # 维度序列完整性检查
        dim_ids = {d.id for d in roadmap.mandatory_dimensions}
        seq_ids = set(roadmap.dimension_sequence)
        if dim_ids != seq_ids:
            logger.warning("[QualityGate] dimension_sequence 与 mandatory_dimensions 不一致，自动修正")
            roadmap.dimension_sequence = [d.id for d in roadmap.mandatory_dimensions]

        # 每维度轮次合理性检查
        dim_count = len(roadmap.mandatory_dimensions)
        rounds_per_dim = max(2, total_rounds // (dim_count + 1))
        if rounds_per_dim < 2:
            logger.warning(f"[QualityGate] 每维度仅 {rounds_per_dim} 轮，建议减少维度数量")

        return roadmap

    @staticmethod
    def validate_whiteboard_operations(ops: list) -> list:
        """代码级白板操作验证——allowlist 机制。"""
        SCRIBE_ALLOWED_SECTIONS = {
            "current_focus", "consensus", "disagreements", "backlog",
            "surprises", "active_concepts", "dimension_map", "search_materials",
        }
        SCRIBE_FORBIDDEN_SECTIONS = {
            "agenda_trace",  # 仅 moderator 可写
        }

        validated = []
        for op in ops:
            section = getattr(op, 'section', None)
            if section in SCRIBE_FORBIDDEN_SECTIONS:
                logger.warning(f"[QualityGate] 拒绝写入禁止区域: {section}")
                continue
            if section not in SCRIBE_ALLOWED_SECTIONS:
                logger.warning(f"[QualityGate] 拒绝写入未知区域: {section}")
                continue
            validated.append(op)
        return validated

    def validate_strategy_output(
        self,
        output: StrategyOutput,
        dimension_state: DimensionState | None = None,
        scheduling_state: SchedulingState | None = None,
    ) -> StrategyOutput:
        """验证战略家输出的完整性。

        当前主要做 anchor_coverage 的交叉验证。
        后续可扩展为更全面的验证。
        """
        if output.anchor_coverage and dimension_state:
            novelty = scheduling_state.get_latest_novelty() if scheduling_state else 0.5
            output.anchor_coverage = self.validate_anchor_coverage(
                output.anchor_coverage,
                novelty_score=novelty,
                dim_round_count=dimension_state.dim_round_count,
            )
        return output
