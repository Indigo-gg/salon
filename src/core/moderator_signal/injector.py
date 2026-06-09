"""注入器：ControlSignals + StateVector → 注入文本。

改进点：
1. 互斥/截断机制：每次最多注入 1 条内容指令 + 1 条互动指令，避免 prompt 冲突
2. 强指令风格：用"导演提词卡"替代"考虑..."，明确要求不暴露主持痕迹
3. 靶向目标：动态插入 @dominant / @silent / @last_speaker 名字
4. 参与者注入使用"内心独白"风格，不破坏角色扮演
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from src.core.moderator_signal.observer import ControlSignals, StateVector
from src.core.scheduling_state import SchedulingState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 注入规则
# ---------------------------------------------------------------------------

@dataclass
class InjectionRule:
    """一条注入规则。"""
    name: str
    target: str          # "moderator" | "participant" | "both"
    category: str        # "content"（内容指令：高度/方向）| "interaction"（互动指令：阵型/能量）
    condition: Callable[[ControlSignals, StateVector], bool]
    text_builder: Callable[[ControlSignals, StateVector], str]
    priority: int = 0


# ---------------------------------------------------------------------------
# 信号注入器
# ---------------------------------------------------------------------------

class SignalInjector:
    """信号注入器：将控制信号翻译为注入文本。

    互斥机制：每次最多输出 1 条 content + 1 条 interaction，取各自优先级最高的。
    """

    def __init__(
        self,
        dive_threshold: int = 3,
        surface_threshold: int = 3,
        readability_threshold: float = 0.7,
        focus_threshold: float = 0.6,
        rules: list[InjectionRule] | None = None,
        scheduling_state: SchedulingState | None = None,
    ):
        self.dive_threshold = dive_threshold
        self.surface_threshold = surface_threshold
        self.readability_threshold = readability_threshold
        self.focus_threshold = focus_threshold
        self.scheduling_state = scheduling_state
        self.rules = rules or self._build_default_rules()

    def build_moderator_injection(self, control: ControlSignals, state: StateVector) -> str:
        """返回注入主持人 prompt 的文本。应用互斥截断。"""
        # 按 category + priority 分组，每组只取最高优先级
        best_content: InjectionRule | None = None
        best_interaction: InjectionRule | None = None

        for rule in self.rules:
            if rule.target not in ("moderator", "both"):
                continue
            if not rule.condition(control, state):
                continue
            if rule.category == "content":
                if best_content is None or rule.priority > best_content.priority:
                    best_content = rule
            elif rule.category == "interaction":
                if best_interaction is None or rule.priority > best_interaction.priority:
                    best_interaction = rule

        parts = []
        if best_content:
            parts.append(best_content.text_builder(control, state))
        if best_interaction:
            parts.append(best_interaction.text_builder(control, state))

        return "\n".join(parts)

    def build_participant_injection(self, control: ControlSignals, state: StateVector) -> str:
        """返回注入参与者 round_info 的文本。应用互斥截断（最多 1 条）。"""
        best: InjectionRule | None = None

        for rule in self.rules:
            if rule.target not in ("participant", "both"):
                continue
            if not rule.condition(control, state):
                continue
            if best is None or rule.priority > best.priority:
                best = rule

        if best:
            return best.text_builder(control, state)
        return ""

    def _build_default_rules(self) -> list[InjectionRule]:
        """构建默认注入规则集。"""
        return [
            # =============================================
            # 主持人注入规则 —— 内容指令（category=content）
            # 弱化为感知数据呈现，由主持人根据原则自行决定干预方式
            # =============================================

            # 1. 可读性过载：高度过高
            InjectionRule(
                name="readability_overload",
                target="moderator",
                category="content",
                condition=lambda c, s: c.readability_alert > self.readability_threshold,
                text_builder=lambda c, s: (
                    f"【感知：可进入性】讨论持续悬浮在高空（抽象度 {s.height:.0%}），听众可能跟不上。"
                    f"建议：要求某位参与者用具体案例落地，或自己先用一个场景来翻译核心观点。"
                ),
                priority=10,
            ),

            # 2. 深度潮汐 — 需要浮出
            InjectionRule(
                name="depth_dive",
                target="moderator",
                category="content",
                condition=lambda c, s: c.depth_tide_signal == "dive",
                text_builder=lambda c, s: (
                    f"【感知：接地性】讨论已连续多轮深潜（抽象度 {s.height:.0%}），距上次具体场景较远。"
                    f"建议：引导参与者用具体案例落地，或自己先给出一个具体场景作为示范。"
                ),
                priority=9,
            ),

            # 3. 深度潮汐 — 需要深潜
            InjectionRule(
                name="depth_surface",
                target="moderator",
                category="content",
                condition=lambda c, s: c.depth_tide_signal == "surface",
                text_builder=lambda c, s: (
                    f"【感知：深度】讨论已连续多轮停留在故事和案例层面（抽象度 {s.height:.0%}），缺乏理论推进。"
                    f"建议：追问案例背后的共同规律，或将逻辑推向极端来检验。"
                ),
                priority=9,
            ),

            # 4. 话题聚焦 — 跑偏
            InjectionRule(
                name="topic_drift",
                target="moderator",
                category="content",
                condition=lambda c, s: c.topic_focus_alert > self.focus_threshold,
                text_builder=lambda c, s: (
                    f"【感知：聚焦度】讨论正在偏离原始主题（聚焦度 {s.direction:.0%}）。"
                    f"建议：做一个罗盘检查，展示当前讨论与原始问题的逻辑连接，温和引导回归。"
                ),
                priority=8,
            ),

            # =============================================
            # 主持人注入规则 —— 互动指令（category=interaction）
            # 弱化为感知数据呈现
            # =============================================

            # 5. 对话张力 — 独白垄断
            InjectionRule(
                name="tension_monologue",
                target="moderator",
                category="interaction",
                condition=lambda c, s: c.tension_level == "monologue",
                text_builder=lambda c, s: (
                    f"【感知：对位性】{_name_or_fallback(s.dominant_speaker, '某位嘉宾')} "
                    f"连续主导了讨论，{_name_or_fallback(s.silent_speaker, '其他人')} 的声音被压制。"
                    f"建议：点名沉默者，用具体的挑战性问题邀请TA发言。"
                ),
                priority=7,
            ),

            # 6. 对话张力 — 各说各话
            InjectionRule(
                name="tension_parallel",
                target="moderator",
                category="interaction",
                condition=lambda c, s: c.tension_level == "parallel",
                text_builder=lambda c, s: (
                    f"【感知：交锋质量】参与者在各说各话，没有真正的交锋。"
                    f"建议：挑出两位嘉宾观点中矛盾的地方，制造一次正面碰撞。"
                ),
                priority=7,
            ),

            # 7. 认知能量 — 耗竭
            InjectionRule(
                name="energy_exhausted",
                target="moderator",
                category="interaction",
                condition=lambda c, s: c.energy_level == "exhausted",
                text_builder=lambda c, s: (
                    f"【感知：能量】讨论正在耗竭（代谢率 {s.speed:.0%}，正在下降）。"
                    f"建议：引入新视角、反直觉的事实，或做一次话题转向来注入新能量。"
                ),
                priority=6,
            ),

            # =============================================
            # 参与者注入规则 —— 原则提醒风格
            # 提醒角色关注原则，而非规定具体做法
            # =============================================

            # 8. 深潜时提醒接地性
            InjectionRule(
                name="breathing_hint",
                target="participant",
                category="content",
                condition=lambda c, s: c.depth_tide_signal == "dive",
                text_builder=lambda c, s: (
                    "（原则提醒：接地性——讨论已连续多轮在抽象层面。"
                    "考虑在发言中用一个具体的当代场景来承载你的论点，让听众能'看见'它。）"
                ),
                priority=5,
            ),

            # 9. 各说各话时提醒对位性
            InjectionRule(
                name="engage_hint",
                target="participant",
                category="interaction",
                condition=lambda c, s: c.tension_level == "parallel",
                text_builder=lambda c, s: (
                    "（原则提醒：对位性——讨论中各说各话。"
                    "考虑先回应一个具体的交锋点，再展开自己的观点。）"
                ),
                priority=4,
            ),

            # =============================================
            # 调度器防线注入规则
            # 基于 SchedulingState 的状态递增注入
            # =============================================

            # 10. 收敛递增 L1 — 连续低新颖度发言（早期预警）
            InjectionRule(
                name="convergence_repetition_L1",
                target="moderator",
                category="content",
                condition=lambda c, s: (
                    self.scheduling_state is not None
                    and self.scheduling_state.speeches_since_novel >= max(4, self.scheduling_state.dyn_topic_shift // 2)
                    and self.scheduling_state.speeches_since_novel < self.scheduling_state.dyn_topic_shift
                ),
                text_builder=lambda c, s: (
                    f"【感知：新颖度】最近 {self.scheduling_state.speeches_since_novel} 次发言的新颖度持续偏低。"
                    "请根据讨论的实际内容判断：参与者是否在用新论据、新案例推进？如果是，无需干预。"
                ),
                priority=12,
            ),

            # 11. 收敛递增 L2 — 连续低新颖度发言（建议转移）
            InjectionRule(
                name="convergence_repetition_L2",
                target="moderator",
                category="content",
                condition=lambda c, s: (
                    self.scheduling_state is not None
                    and self.scheduling_state.speeches_since_novel >= self.scheduling_state.dyn_topic_shift
                    and self.scheduling_state.speeches_since_novel < self.scheduling_state.dyn_exhausted
                ),
                text_builder=lambda c, s: (
                    f"【感知：新颖度升级】最近 {self.scheduling_state.speeches_since_novel} 次发言新颖度持续偏低。"
                    "建议：引入新视角、反直觉事实，或追问此前被忽略的子命题。请独立判断是否真在重复。"
                ),
                priority=13,
            ),

            # 12. 收敛递增 L3 — 连续低新颖度发言（强感知）
            InjectionRule(
                name="convergence_repetition_L3",
                target="moderator",
                category="content",
                condition=lambda c, s: (
                    self.scheduling_state is not None
                    and self.scheduling_state.speeches_since_novel >= self.scheduling_state.dyn_exhausted
                    and self.scheduling_state.topic_shifts_count < 2
                ),
                text_builder=lambda c, s: (
                    f"【感知：新颖度⚠️】最近 {self.scheduling_state.speeches_since_novel} 次发言新颖度极低。"
                    "当前子话题可能已充分讨论。建议在 notice 中告知参与者，引导转向新方向或引入全新视角。"
                ),
                priority=14,
            ),

            # 12b. 收敛递增 L3b — 多次转移后仍在重复（引导综合）
            InjectionRule(
                name="convergence_synthesis",
                target="moderator",
                category="content",
                condition=lambda c, s: (
                    self.scheduling_state is not None
                    and self.scheduling_state.speeches_since_novel >= self.scheduling_state.dyn_topic_shift
                    and self.scheduling_state.topic_shifts_count >= 2
                ),
                text_builder=lambda c, s: (
                    f"【感知：论证穷尽】讨论已尝试 {self.scheduling_state.topic_shifts_count} 次话题转移，"
                    f"核心论点仍在重复（连续 {self.scheduling_state.speeches_since_novel} 次发言新颖度低）。"
                    "当前主题已被充分探讨。建议以主持人权威做终结性综合：总结各方立场，"
                    "标出已达成的共识和不可调和的分歧（注意：不要掩盖未解决的分歧），宣布进入收束阶段。"
                ),
                priority=15,
            ),

            # 13. 时间驱动 — closing_window 尾声提醒
            InjectionRule(
                name="closing_window_reminder",
                target="moderator",
                category="content",
                condition=lambda c, s: (
                    self.scheduling_state is not None
                    and self.scheduling_state.get_closing_injection_text(
                        self.scheduling_state.current_round,
                        self.scheduling_state.max_rounds,
                    ) != ""
                ),
                text_builder=lambda c, s: (
                    self.scheduling_state.get_closing_injection_text(
                        self.scheduling_state.current_round,
                        self.scheduling_state.max_rounds,
                    )
                    if self.scheduling_state else ""
                ),
                priority=11,
            ),

            # 14. 发言统计注入
            InjectionRule(
                name="speak_stats_injection",
                target="moderator",
                category="interaction",
                condition=lambda c, s: (
                    self.scheduling_state is not None
                    and any(
                        cnt >= 3
                        for cnt in self.scheduling_state.consecutive_silence.values()
                    )
                ),
                text_builder=lambda c, s: (
                    self.scheduling_state.build_speak_stats_text()
                    if self.scheduling_state else ""
                ),
                priority=5,
            ),

            # 15. 锚定提醒 — 温和
            InjectionRule(
                name="anchor_soft",
                target="moderator",
                category="content",
                condition=lambda c, s: (
                    self.scheduling_state is not None
                    and self.scheduling_state.rounds_since_anchor >= self.scheduling_state.anchor_soft_trigger
                    and self.scheduling_state.rounds_since_anchor < self.scheduling_state.anchor_medium_trigger
                ),
                text_builder=lambda c, s: (
                    f"【感知：锚定】已 {self.scheduling_state.rounds_since_anchor} 轮未显式连接回原始问题。"
                    f"考虑在 agenda_note 中提醒参与者回归主线。"
                ),
                priority=6,
            ),

            # 16. 锚定提醒 — 中等
            InjectionRule(
                name="anchor_medium",
                target="moderator",
                category="content",
                condition=lambda c, s: (
                    self.scheduling_state is not None
                    and self.scheduling_state.rounds_since_anchor >= self.scheduling_state.anchor_medium_trigger
                    and self.scheduling_state.rounds_since_anchor < self.scheduling_state.anchor_hard_trigger
                ),
                text_builder=lambda c, s: (
                    f"【感知：锚定⚠️】已 {self.scheduling_state.rounds_since_anchor} 轮未回锚原始问题。"
                    f"建议做一个罗盘检查：概括从原始问题出发探索到了哪里，然后自然引导回归。"
                ),
                priority=7,
            ),

            # 17. 锚定提醒 — 强制
            InjectionRule(
                name="anchor_hard",
                target="moderator",
                category="content",
                condition=lambda c, s: (
                    self.scheduling_state is not None
                    and self.scheduling_state.rounds_since_anchor >= self.scheduling_state.anchor_hard_trigger
                ),
                text_builder=lambda c, s: (
                    f"【感知：锚定⚠️⚠️】已 {self.scheduling_state.rounds_since_anchor} 轮未回锚原始问题。"
                    f"强烈建议在本轮 notice 中做罗盘检查：明确讨论从原始问题出发探索到了什么位置。"
                ),
                priority=8,
            ),
        ]


# ---------------------------------------------------------------------------
# 辅助函数：动态名字插入
# ---------------------------------------------------------------------------

def _target_name(state: StateVector) -> str:
    """选择一个合适的被邀请发言的人。优先沉默者，其次最后发言者。"""
    if state.silent_speaker:
        return f"@{state.silent_speaker}"
    if state.last_speaker:
        return f"@{state.last_speaker}"
    return "一位参与者"


def _name_or_fallback(agent_id: str, fallback: str) -> str:
    """将 agent_id 转为可读名字，如果没有则用 fallback。"""
    if agent_id:
        return f"@{agent_id}"
    return fallback
