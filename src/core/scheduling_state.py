"""调度器状态追踪与后处理（Scheduling State Tracker）。

三层防线的基础设施：
- 追踪每轮的 novelty_score（重复度）、发言统计、沉默计数
- 提供 closing_window 计算
- 提供 post_process 后处理（第 3 层硬规则）

用法：
    from src.core.scheduling_state import SchedulingState

    state = SchedulingState(config)
    state.update(raw, control, round_num, speaker_ids, all_agent_ids)
    decision = state.post_process(decision, participants, intents, max_speakers)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agents.moderator import AgendaDecision
    from src.config import MonitorConfig
    from src.core.moderator_signal.observer import ControlSignals
    from src.core.moderator_signal.sensors import RawSignals

logger = logging.getLogger(__name__)

# 锚定关键词：检测 notice 中是否包含罗盘检查相关内容
_ANCHOR_KEYWORDS = ("原始问题", "出发", "回到最初", "回到主题", "罗盘", "compass", "original question")


@dataclass
class SchedulingState:
    """调度器的全局状态追踪器。"""

    # --- 配置 ---
    novelty_low_threshold: float = 0.2
    repetition_topic_shift_speeches: int = 12    # 连续 N 次发言新颖度低 → 强制话题转移
    repetition_exhausted_speeches: int = 20      # 连续 N 次发言新颖度低 → 穷尽提醒
    recent_speak_window: int = 3
    closing_window_min: int = 2
    closing_window_max: int = 5
    anchor_soft_trigger: int = 6
    anchor_medium_trigger: int = 10
    anchor_hard_trigger: int = 15

    # --- 重复度追踪（按发言次数计） ---
    novelty_scores: list[float] = field(default_factory=list)
    consecutive_high_repetition: int = 0         # 连续高重复轮次（保留用于日志）
    speeches_since_novel: int = 0                # 自上次新颖轮以来的累计发言次数
    topic_shifts_count: int = 0                  # 本轮讨论中已发生的话题转移次数

    # --- 发言权追踪 ---
    speak_history: list[set[str]] = field(default_factory=list)
    consecutive_silence: dict[str, int] = field(default_factory=dict)

    # --- 锚定追踪 ---
    last_compass_check_round: int = 0
    rounds_since_anchor: int = 0

    # --- KL 归一化缓冲 ---
    kl_history: list[float] = field(default_factory=list)

    # --- 当前轮次信息（供注入规则读取）---
    current_round: int = 0
    max_rounds: int = 50

    # --- 动态阈值缓存（由 update() 根据参与人数计算） ---
    dyn_topic_shift: int = 12
    dyn_exhausted: int = 20

    @classmethod
    def from_config(cls, config: MonitorConfig) -> SchedulingState:
        """从 MonitorConfig 创建实例。"""
        return cls(
            novelty_low_threshold=config.novelty_low_threshold,
            repetition_topic_shift_speeches=config.repetition_topic_shift_speeches,
            repetition_exhausted_speeches=config.repetition_exhausted_speeches,
            recent_speak_window=config.recent_speak_window,
            closing_window_min=config.closing_window_min,
            closing_window_max=config.closing_window_max,
            anchor_soft_trigger=config.anchor_soft_trigger,
            anchor_medium_trigger=config.anchor_medium_trigger,
            anchor_hard_trigger=config.anchor_hard_trigger,
        )

    # -------------------------------------------------------------------
    # 每轮更新
    # -------------------------------------------------------------------

    def update(
        self,
        raw: RawSignals,
        control: ControlSignals | None,
        round_num: int,
        speaker_ids: list[str],
        all_agent_ids: list[str],
    ) -> None:
        """每轮调用，更新所有调度状态。"""

        # 0. 记录当前轮次和动态阈值
        self.current_round = round_num
        dyn = self.dynamic_thresholds(len(all_agent_ids))
        self.dyn_topic_shift = dyn["topic_shift"]
        self.dyn_exhausted = dyn["exhausted"]

        # 1. 计算 novelty_score
        novelty = self.compute_novelty_score(raw)
        self.novelty_scores.append(novelty)

        # 2. 更新重复度追踪（按发言次数计）
        num_speeches_this_round = len(speaker_ids)
        if novelty < self.novelty_low_threshold:
            self.consecutive_high_repetition += 1
            self.speeches_since_novel += num_speeches_this_round
        else:
            # 从低新颖度恢复到高新颖度 = 一次成功的话题转移
            if self.speeches_since_novel >= 6:
                self.topic_shifts_count += 1
                logger.info(
                    f"SchedulingState: topic shift #{self.topic_shifts_count} detected "
                    f"(recovered after {self.speeches_since_novel} low-novelty speeches)"
                )
            self.consecutive_high_repetition = 0
            self.speeches_since_novel = 0

        # 3. 更新发言历史
        self.speak_history.append(set(speaker_ids))
        if len(self.speak_history) > self.recent_speak_window * 2:
            self.speak_history = self.speak_history[-(self.recent_speak_window * 2):]

        # 4. 更新连续沉默计数
        for aid in all_agent_ids:
            if aid in speaker_ids:
                self.consecutive_silence[aid] = 0
            else:
                self.consecutive_silence[aid] = self.consecutive_silence.get(aid, 0) + 1

        logger.debug(
            f"SchedulingState: round={round_num} novelty={novelty:.3f} "
            f"consec_rep={self.consecutive_high_repetition} "
            f"speeches_since_novel={self.speeches_since_novel} "
            f"silence={dict(self.consecutive_silence)}"
        )

    def update_anchor(self, round_num: int, rounds_since_anchor: int, notice: str) -> None:
        """更新锚定追踪。由 orchestrator 在每轮 moderator 决策后调用。"""
        self.rounds_since_anchor = rounds_since_anchor
        # 检测 notice 中是否包含罗盘检查内容
        if notice and any(kw in notice for kw in _ANCHOR_KEYWORDS):
            self.last_compass_check_round = round_num

    # -------------------------------------------------------------------
    # novelty_score 计算
    # -------------------------------------------------------------------

    def compute_novelty_score(self, raw: RawSignals) -> float:
        """计算本轮的新颖度分数（0-1）。高 = 有新东西，低 = 高重复。"""
        concept_turnover = raw.concept_turnover

        # KL 归一化：用最近 10 轮的 min-max 归一化
        self.kl_history.append(raw.kl_divergence)
        if len(self.kl_history) > 10:
            self.kl_history = self.kl_history[-10:]

        kl_range = max(self.kl_history) - min(self.kl_history)
        if kl_range > 1e-9:
            kl_normalized = (raw.kl_divergence - min(self.kl_history)) / kl_range
        else:
            kl_normalized = 0.5  # 所有 KL 值相同，取中间值

        return concept_turnover * 0.5 + min(1.0, kl_normalized) * 0.5

    # -------------------------------------------------------------------
    # 发言统计
    # -------------------------------------------------------------------

    def get_recent_speak_stats(self, window: int | None = None) -> dict[str, dict]:
        """返回近 N 轮的发言统计。

        Returns:
            dict[agent_id] -> {"count": int, "total": int, "ratio": float}
        """
        w = window or self.recent_speak_window
        recent = self.speak_history[-w:] if self.speak_history else []
        total = len(recent)
        if total == 0:
            return {}

        stats = {}
        for round_speakers in recent:
            for aid in round_speakers:
                if aid not in stats:
                    stats[aid] = {"count": 0, "total": total, "ratio": 0.0}
                stats[aid]["count"] += 1

        for aid in stats:
            stats[aid]["ratio"] = stats[aid]["count"] / total

        return stats

    def build_speak_stats_text(self) -> str:
        """生成发言统计注入文本（用于主持人 prompt）。"""
        stats = self.get_recent_speak_stats()
        if not stats:
            return ""

        w = self.recent_speak_window
        lines = [f"【近期发言统计（最近 {w} 轮）】"]

        # 按发言次数排序
        sorted_agents = sorted(stats.items(), key=lambda x: x[1]["count"], reverse=True)
        for aid, s in sorted_agents:
            silence = self.consecutive_silence.get(aid, 0)
            suffix = ""
            if silence >= 3:
                suffix = f" ← 连续 {silence} 轮未发言"
            elif s["count"] == w:
                suffix = " ← 连续发言"
            lines.append(f"- {aid}: {s['count']}/{w} 轮发言 ({s['ratio']:.0%}){suffix}")

        # 如果有人连续沉默 ≥ 3 轮，追加建议
        long_silent = [aid for aid, cnt in self.consecutive_silence.items() if cnt >= 3]
        if long_silent:
            lines.append(f"{', '.join(long_silent)} 已连续多轮未发言，如果本轮有相关意图建议优先考虑。")

        return "\n".join(lines)

    # -------------------------------------------------------------------
    # CLOSING 窗口
    # -------------------------------------------------------------------

    def get_latest_novelty(self) -> float:
        """获取最新一轮的新颖度分数。无数据时返回 0.5（中性）。"""
        return self.novelty_scores[-1] if self.novelty_scores else 0.5

    def get_closing_window(self, max_rounds: int) -> int:
        """计算 closing_window 大小。使用 sqrt 曲线，上界 5。"""
        return max(self.closing_window_min, min(self.closing_window_max, math.ceil(math.sqrt(max_rounds))))

    def should_force_closing(self, round_num: int, max_rounds: int) -> bool:
        """检查是否应该强制进入 CLOSING。

        仅在最后 1 轮强制触发，确保 max_rounds 轮的实际内容都能产出。
        主持人可以通过 phase 判断自行提前进入 CONVERGENCE/CLOSING。
        """
        rounds_left = max_rounds - round_num
        return rounds_left <= 1

    def get_closing_injection_text(self, round_num: int, max_rounds: int) -> str:
        """生成 closing_window 内的尾声注入文本。"""
        window = self.get_closing_window(max_rounds)
        rounds_left = max_rounds - round_num

        if rounds_left > window:
            return ""
        if rounds_left <= max(1, window // 2):
            return (
                f"【尾声提醒】讨论剩余 {rounds_left} 轮。"
                "请安排总结性发言，不要再引入全新的理论框架。"
                "如果存在无法调和的分歧，请明确指出。"
            )
        return (
            f"【尾声提醒】讨论进入尾声阶段（剩余 {rounds_left} 轮）。"
            "建议开始收敛，总结核心分歧和收获。"
        )

    # -------------------------------------------------------------------
    # 沉默保护阈值
    # -------------------------------------------------------------------

    @staticmethod
    def silence_threshold(num_participants: int, max_speakers: int) -> int:
        """动态计算沉默保护阈值。目标：纯随机下触发概率 < 0.5%。"""
        if max_speakers >= num_participants:
            return 999  # 每人都发言，不需要保护
        p_silence = 1 - max_speakers / num_participants
        if p_silence <= 0:
            return 999
        return max(4, math.ceil(math.log(0.005) / math.log(p_silence)))

    # -------------------------------------------------------------------
    # 第 3 层后处理
    # -------------------------------------------------------------------

    def dynamic_thresholds(self, num_participants: int) -> dict[str, int]:
        """根据参与人数计算动态阈值。

        策略：每人平均复读 1-2 次后触发介入。
        - topic_shift: max(6, 参与者数 * 1.5) — 约 1.5 轮
        - exhausted:   max(10, 参与者数 * 2.5) — 约 2.5 轮
        """
        return {
            "topic_shift": max(6, round(num_participants * 1.5)),
            "exhausted": max(10, round(num_participants * 2.5)),
        }

    def apply_strategy_constraint(
        self,
        decision: AgendaDecision,
        strategy,  # StrategyOutput | None
        all_intents: dict,
        participants: list,
    ) -> tuple[list[str], set[str]]:
        """将战略约束融入选人逻辑。

        设计原则：没有 avoid_agents。战略家只指定"谁更适合"（preferred_agents），
        不指定"谁不适合"。全员进入候选池，preferred_agents 获得优先级提升，
        但无人被硬删除。

        Args:
            decision: 主持人的决策
            strategy: 战略家的输出（StrategyOutput 或 None）
            all_intents: 所有参与者的意图信号
            participants: 参与者列表

        Returns:
            (final_speakers, forced_callouts)
            - final_speakers: 最终发言人列表
            - forced_callouts: 被强制点名的 agent ID 集合
        """
        if not strategy or not strategy.direction.preferred_agents:
            return list(decision.speakers or []), set()

        preferred = set(strategy.direction.preferred_agents)

        # 红线保护：沉默太久的 agent（不受战略约束影响）
        all_ids = [a.agent_id for a in participants]
        max_speakers = len(all_ids) // 2 + 1
        threshold = self.silence_threshold(len(all_ids), max_speakers)
        red_line = set()
        for agent_id, silence_count in self.consecutive_silence.items():
            if silence_count >= threshold:
                red_line.add(agent_id)

        # 强制点名：preferred 中 energy 为 "low" 的 agent
        forced_callouts = set()
        for agent_id in preferred:
            if agent_id in all_intents:
                intent = all_intents[agent_id]
                if hasattr(intent, 'energy') and intent.energy == "low":
                    if agent_id not in red_line:
                        forced_callouts.add(agent_id)

        # 重新排序：红线 > preferred > 其他
        def sort_key(agent_id):
            if agent_id in red_line:
                return 0
            if agent_id in preferred:
                return 1
            return 2

        # 候选池：当前 speakers + preferred + red_line
        current_speakers = set(decision.speakers or [])
        all_candidates = current_speakers | preferred | red_line
        ranked = sorted(all_candidates, key=sort_key)
        final = ranked[:max_speakers]

        # 保底：至少 max_speakers 人发言（与主持人选人上限一致）
        if len(final) < max_speakers:
            # 从有意图的参与者中补充（按沉默轮次排序，最沉默的优先）
            silence_ranked = sorted(
                [aid for aid in all_ids if aid not in final and aid in all_intents],
                key=lambda aid: self.consecutive_silence.get(aid, 0),
                reverse=True,
            )
            for aid in silence_ranked:
                if len(final) >= max_speakers:
                    break
                final.append(aid)

        return final, forced_callouts

    def post_process(
        self,
        decision: AgendaDecision,
        participants: list,
        intents: dict,
        max_speakers: int,
    ) -> AgendaDecision:
        """第 3 层硬规则后处理。只拦截 LLM 明显犯错的情况。"""

        all_ids = [a.agent_id for a in participants]
        threshold = self.silence_threshold(len(all_ids), max_speakers)
        dyn = self.dynamic_thresholds(len(all_ids))

        # 规则 1：连续新颖度低的发言 ≥ N 次 → 根据历史决定行为
        if self.speeches_since_novel >= dyn["topic_shift"]:
            if decision.phase == "CONVERGENCE":
                if self.topic_shifts_count >= 2:
                    # 已多次转移话题仍在重复 → 真正的穷尽，允许收敛
                    converge_notice = (
                        f"讨论已尝试 {self.topic_shifts_count} 次话题转移，核心论点仍在重复。"
                        "这是真正的论点穷尽信号——当前话题已被充分探讨。"
                        "请引导参与者总结各自立场的核心收获和剩余分歧，为收尾做准备。"
                    )
                    decision.notice = (decision.notice + "\n" if decision.notice else "") + converge_notice
                    logger.info(
                        f"SchedulingState: allowing convergence after {self.topic_shifts_count} "
                        f"topic shifts and {self.speeches_since_novel} low-novelty speeches"
                    )
                else:
                    # 尚未充分探索 → 强制转移
                    # Phase 2 变更：PhaseState 是 phase 唯一权威源，
                    # 此处的 phase 修改会被 salon.py 中 directive.phase 覆盖。
                    # 保留此行仅为向后兼容（无 SessionController 时仍生效）。
                    decision.phase = "DEEPENING"
                    shift_notice = (
                        "核心论点已趋于稳定但仍在重复。"
                        "建议暂时搁置当前分歧，转向尚未充分探讨的子问题或引入新的视角。"
                    )
                    decision.notice = (decision.notice + "\n" if decision.notice else "") + shift_notice
                    logger.info(
                        f"SchedulingState: forced topic shift after {self.speeches_since_novel} "
                        f"speeches with low novelty"
                    )

        # 规则 2：连续新颖度低的发言 ≥ N 次 → 穷尽提醒
        if self.speeches_since_novel >= dyn["exhausted"]:
            if self.topic_shifts_count >= 2:
                exhaust_notice = (
                    f"讨论已尝试 {self.topic_shifts_count} 次话题转移，核心论点仍在重复。"
                    "这表明当前主题已被充分讨论。"
                    "请引导大家做总结性发言：各自的核心收获是什么？剩余分歧在哪里？"
                )
            else:
                exhaust_notice = (
                    "讨论已多次尝试转向但核心论点仍在重复。"
                    "建议各位评估：是否还有未探索的子命题？如果没有，可以开始收敛。"
                )
            if exhaust_notice not in (decision.notice or ""):
                decision.notice = (decision.notice + "\n" if decision.notice else "") + exhaust_notice
                logger.info(
                    f"SchedulingState: exhaustion notice after {self.speeches_since_novel} "
                    f"speeches with low novelty (topic_shifts={self.topic_shifts_count})"
                )

        # 规则 3：连续沉默保护（优先插入，不被 max_speakers 截断）
        speakers = list(decision.speakers) if decision.speakers else []
        protected = []
        for aid in all_ids:
            if self.consecutive_silence.get(aid, 0) >= threshold:
                if aid not in speakers:
                    protected.append(aid)
                    logger.info(f"SchedulingState: silence protection triggered for {aid} "
                                f"(silent for {self.consecutive_silence[aid]} rounds, threshold={threshold})")
        if protected:
            speakers = protected + speakers  # 保护者优先
        decision.speakers = speakers[:max_speakers]

        return decision
