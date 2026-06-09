"""主持人信号感知与注入系统（Moderator Signal Perception & Injection）。

控制论架构：传感器 → 观测器 → 注入器 → LLM

- sensors.py：第一层，原始信号测量（规则 + 统计）
- observer.py：第二层，状态观测器（EMA + 映射 + LLM 辅助）
- injector.py：注入器，控制信号 → 注入文本

用法：
    from src.core.moderator_signal import ModeratorSignalSystem

    system = ModeratorSignalSystem()
    raw = system.compute_raw(round_num, messages, topic, concept_registry, participant_ids)
    control = system.update(raw)
    mod_text = system.get_moderator_injection()
    part_text = system.get_participant_injection()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.moderator_signal.injector import SignalInjector
from src.core.moderator_signal.observer import ControlSignals, SignalObserver, StateVector
from src.core.moderator_signal.sensors import RawSignals, compute_raw_signals
from src.core.scheduling_state import SchedulingState

logger = logging.getLogger(__name__)


class ModeratorSignalSystem:
    """主持人信号感知与注入系统的统一入口。

    封装三层架构，提供简洁的调用接口。
    """

    def __init__(
        self,
        short_half_life: float = 3.0,
        long_half_life: float = 10.0,
        dive_threshold: int = 3,
        surface_threshold: int = 3,
        readability_threshold: float = 0.7,
        focus_threshold: float = 0.6,
        scheduling_state: SchedulingState | None = None,
    ):
        self.observer = SignalObserver(
            short_half_life=short_half_life,
            long_half_life=long_half_life,
        )
        self.injector = SignalInjector(
            dive_threshold=dive_threshold,
            surface_threshold=surface_threshold,
            readability_threshold=readability_threshold,
            focus_threshold=focus_threshold,
            scheduling_state=scheduling_state,
        )
        self._prev_token_dist: dict[str, float] | None = None
        self._last_raw: RawSignals | None = None
        self._last_control: ControlSignals | None = None
        logger.info("ModeratorSignalSystem initialized")

    def compute_raw(
        self,
        round_num: int,
        recent_messages: list,
        topic: str,
        concept_registry: dict | None = None,
        participant_ids: list[str] | None = None,
    ) -> RawSignals:
        """第一层：计算原始信号。"""
        raw, self._prev_token_dist = compute_raw_signals(
            round_num=round_num,
            recent_messages=recent_messages,
            topic=topic,
            concept_registry=concept_registry,
            participant_ids=participant_ids,
            prev_token_dist=self._prev_token_dist,
        )
        self._last_raw = raw
        return raw

    def update(self, raw: RawSignals | None = None) -> ControlSignals:
        """第二层：更新状态观测器，返回控制信号。"""
        if raw is None:
            raw = self._last_raw
        if raw is None:
            return ControlSignals()

        control = self.observer.update(raw)
        self._last_control = control

        return control

    def update_llm_feedback(self, emotional_temperature: float, perceived_tension: str) -> None:
        """接收主持人 LLM 的反馈信号。"""
        self.observer.update_llm_feedback(emotional_temperature, perceived_tension)

    def get_moderator_injection(self) -> str:
        """返回注入主持人 prompt 的文本。"""
        if self._last_control is None:
            return ""
        return self.injector.build_moderator_injection(
            self._last_control, self.observer.state,
        )

    def get_participant_injection(self) -> str:
        """返回注入参与者 round_info 的文本。"""
        if self._last_control is None:
            return ""
        return self.injector.build_participant_injection(
            self._last_control, self.observer.state,
        )

    def get_state_summary(self) -> str:
        """返回当前状态的可读摘要（用于调试和日志）。"""
        s = self.observer.state
        c = self._last_control or ControlSignals()
        return (
            f"[状态] 方向={s.direction:.2f}({s.delta_direction:+.2f}) "
            f"高度={s.height:.2f}({s.delta_height:+.2f}) "
            f"速度={s.speed:.2f}({s.delta_speed:+.2f}) "
            f"阵型={s.formation:.2f}({s.delta_formation:+.2f}) | "
            f"[控制] 可读性={c.readability_alert:.2f} 潮汐={c.depth_tide_signal} "
            f"聚焦={c.topic_focus_alert:.2f} 张力={c.tension_level} 能量={c.energy_level}"
        )


__all__ = [
    "ModeratorSignalSystem",
    "RawSignals",
    "StateVector",
    "ControlSignals",
    "SignalObserver",
    "SignalInjector",
    "compute_raw_signals",
]
