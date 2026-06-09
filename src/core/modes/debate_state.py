"""辩论状态机：管理辩论的阶段转换和发言权分配。

纯逻辑，无 I/O 依赖。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class DebatePhase(str, Enum):
    CONSTRUCTIVE = "constructive"    # 立论
    FREE_DEBATE = "free_debate"      # 自由辩论
    CLOSING = "closing"              # 总结陈词
    FINISHED = "finished"            # 结束


class Faction(str, Enum):
    AFFIRMATIVE = "affirmative"      # 正方
    NEGATIVE = "negative"            # 反方


@dataclass
class DebateConfig:
    """辩论赛配置。总轮数由 max_rounds 统一控制。"""
    resolution: str                           # 辩题
    affirmative_ids: list[str]                # 正方 agent IDs
    negative_ids: list[str]                   # 反方 agent IDs
    constructive_per_side: int = 1            # 每方立论人数
    closing_per_side: int = 1                 # 每方总结人数
    free_debate_rounds: int = 0               # 自由辩论轮数（0=自动计算）

    def resolve_free_rounds(self, max_rounds: int) -> int:
        """根据 max_rounds 自动计算自由辩论轮数。"""
        if self.free_debate_rounds > 0:
            return self.free_debate_rounds
        fixed = self.constructive_per_side * 2 + self.closing_per_side * 2
        remaining = max_rounds - fixed
        return max(2, remaining)  # 至少 2 轮自由辩论


@dataclass
class DebateState:
    """辩论状态机。"""
    config: DebateConfig
    effective_free_rounds: int = 6            # 实际自由辩论轮数（由策略根据 max_rounds 计算）
    phase: DebatePhase = DebatePhase.CONSTRUCTIVE

    # 立论阶段追踪
    _constructive_idx: int = 0                # 当前立论发言者索引

    # 自由辩论追踪
    _free_round_count: int = 0                # 已完成的自由辩论轮数
    _free_active_faction: Faction = Faction.AFFIRMATIVE  # 当前轮哪方发言

    # 总结阶段追踪
    _closing_idx: int = 0                     # 当前总结发言者索引

    def get_constructive_speaker(self) -> tuple[Faction, str] | None:
        """获取当前立论阶段的发言者。返回 (阵营, agent_id) 或 None。"""
        total = self.config.constructive_per_side * 2
        if self._constructive_idx >= total:
            return None

        # 交替：正方0, 反方0, 正方1, 反方1, ...
        idx = self._constructive_idx
        if idx % 2 == 0:
            side_idx = idx // 2
            if side_idx < len(self.config.affirmative_ids):
                return (Faction.AFFIRMATIVE, self.config.affirmative_ids[side_idx])
        else:
            side_idx = idx // 2
            if side_idx < len(self.config.negative_ids):
                return (Faction.NEGATIVE, self.config.negative_ids[side_idx])
        return None

    def advance_constructive(self) -> None:
        """立论阶段推进到下一位发言者。"""
        self._constructive_idx += 1
        if self._constructive_idx >= self.config.constructive_per_side * 2:
            self.phase = DebatePhase.FREE_DEBATE
            self._free_active_faction = Faction.AFFIRMATIVE
            logger.info("Debate: constructive → free_debate")

    def get_free_debate_faction(self) -> Faction:
        """获取当前自由辩论轮的发言阵营。"""
        return self._free_active_faction

    def get_free_debate_candidates(self) -> list[str]:
        """获取当前轮可发言的 agent IDs（当前阵营的所有成员）。"""
        if self._free_active_faction == Faction.AFFIRMATIVE:
            return list(self.config.affirmative_ids)
        return list(self.config.negative_ids)

    def advance_free_debate(self) -> None:
        """自由辩论推进到下一轮。"""
        # 切换阵营
        if self._free_active_faction == Faction.AFFIRMATIVE:
            self._free_active_faction = Faction.NEGATIVE
        else:
            self._free_active_faction = Faction.AFFIRMATIVE
            self._free_round_count += 1  # 一轮完整的双方发言

        if self._free_round_count >= self.effective_free_rounds // 2:
            self.phase = DebatePhase.CLOSING
            logger.info("Debate: free_debate → closing")

    def get_closing_speaker(self) -> tuple[Faction, str] | None:
        """获取当前总结阶段的发言者。反方先总结，正方后。"""
        total = self.config.closing_per_side * 2
        if self._closing_idx >= total:
            return None

        # 逆序：反方最后 → 正方最后
        idx = self._closing_idx
        if idx % 2 == 0:
            # 反方总结
            side_idx = len(self.config.negative_ids) - 1 - (idx // 2)
            if 0 <= side_idx < len(self.config.negative_ids):
                return (Faction.NEGATIVE, self.config.negative_ids[side_idx])
        else:
            # 正方总结
            side_idx = len(self.config.affirmative_ids) - 1 - (idx // 2)
            if 0 <= side_idx < len(self.config.affirmative_ids):
                return (Faction.AFFIRMATIVE, self.config.affirmative_ids[side_idx])
        return None

    def advance_closing(self) -> None:
        """总结阶段推进到下一位。"""
        self._closing_idx += 1
        total = self.config.closing_per_side * 2
        if self._closing_idx >= total:
            self.phase = DebatePhase.FINISHED
            logger.info("Debate: closing → finished")

    def get_phase_display(self) -> str:
        """获取当前阶段的显示文本。"""
        if self.phase == DebatePhase.CONSTRUCTIVE:
            total = self.config.constructive_per_side * 2
            return f"立论阶段 {self._constructive_idx + 1}/{total}"
        elif self.phase == DebatePhase.FREE_DEBATE:
            max_rounds = self.effective_free_rounds // 2
            faction_name = "正方" if self._free_active_faction == Faction.AFFIRMATIVE else "反方"
            return f"自由辩论 第{self._free_round_count + 1}/{max_rounds}轮 · {faction_name}发言"
        elif self.phase == DebatePhase.CLOSING:
            total = self.config.closing_per_side * 2
            return f"总结陈词 {self._closing_idx + 1}/{total}"
        return "已结束"

    def get_faction(self, agent_id: str) -> Faction | None:
        """判断某 agent 属于哪个阵营。"""
        if agent_id in self.config.affirmative_ids:
            return Faction.AFFIRMATIVE
        if agent_id in self.config.negative_ids:
            return Faction.NEGATIVE
        return None

    def get_faction_label(self, agent_id: str) -> str:
        """获取阵营标签。"""
        f = self.get_faction(agent_id)
        if f == Faction.AFFIRMATIVE:
            return "正方"
        if f == Faction.NEGATIVE:
            return "反方"
        return ""
