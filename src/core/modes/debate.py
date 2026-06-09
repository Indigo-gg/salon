"""辩论赛模式策略：状态机驱动，正反方对抗。

从 DialogueModeStrategy 实现，内部使用 DebateStateMachine 管理阶段转换。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.agents.base import BaseAgent, SpeakIntent
from src.agents.moderator import ModeratorAgent
from src.agents.scribe import ScribeAgent
from src.agents.participant import ParticipantAgent
from src.core.modes.base import DialogueModeStrategy, ModeContext
from src.core.modes.debate_state import DebateConfig, DebatePhase, DebateState, Faction
from src.memory.stream import Message

if TYPE_CHECKING:
    from src.agents.base import SpeechOutput

logger = logging.getLogger(__name__)

# 辩论专用 round_info 注入
_DEBATE_INSTRUCTIONS = {
    DebatePhase.CONSTRUCTIVE: (
        "现在是【立论阶段】。请完整陈述你方的核心论点和逻辑框架。"
        "不要陷入细节争吵，不要回应对方（对方还没发言）。"
        "你的目标是让听众理解你方的基本立场和推理路径。"
        "你必须发言，不能跳过。"
    ),
    DebatePhase.FREE_DEBATE: (
        "现在是【自由辩论阶段】。请针对对方的论点进行反驳或补充你方论点。"
        "发言要简短有力，直击要害。可以引用对方之前的发言。"
        "你必须发言，不能跳过。"
    ),
    DebatePhase.CLOSING: (
        "现在是【总结陈词阶段】。请概括你方的核心立场，回应对方的主要攻击，"
        "并做最后的有力陈述。这是你最后一次发言机会。"
        "你必须发言，不能跳过。"
    ),
}


class DebateModeStrategy(DialogueModeStrategy):
    """辩论赛模式：状态机驱动的正反方对抗。"""

    @property
    def name(self) -> str:
        return "debate"

    def setup(self, ctx: ModeContext, debate_config: DebateConfig | None = None) -> None:
        """初始化辩论组件。debate_config 从 ctx.config 或参数获取。"""
        config_dir = Path(ctx.config.config_dir)
        roles_dir = config_dir / "roles"
        souls_dir = config_dir / "souls"

        # 解析辩论配置（从 session metadata 或默认）
        if debate_config is None:
            debate_config = self._build_default_config(ctx)

        # 辩论主持人
        mod_role_path = roles_dir / "debate_moderator_role.md"
        mod_role_text = mod_role_path.read_text(encoding="utf-8") if mod_role_path.exists() else ""
        ctx.moderator = ModeratorAgent("moderator", "", ctx.config)
        ctx.moderator.name = "辩论主持人"
        ctx.moderator.role = "moderator"
        if mod_role_text:
            ctx.moderator.soul.inject_role(mod_role_text)

        # 辩论记录员
        scribe_role_path = roles_dir / "debate_scribe_role.md"
        scribe_role_text = scribe_role_path.read_text(encoding="utf-8") if scribe_role_path.exists() else ""
        ctx.scribe = ScribeAgent("scribe", "", ctx.config)
        ctx.scribe.name = "辩论记录员"
        ctx.scribe.role = "scribe"
        if scribe_role_text:
            ctx.scribe.soul.inject_role(scribe_role_text)

        # 不初始化沙龙的信号系统和调度状态
        ctx.round_monitor = None
        ctx.signal_system = None
        ctx.scheduling_state = None

        # 搜索工具
        if ctx.config.search.enabled and ctx.config.search.api_key:
            from src.tools.search import WebSearchTool
            ctx.search_tool = WebSearchTool(
                api_key=ctx.config.search.api_key,
                max_results=ctx.config.search.max_results,
            )
            logger.info("DebateMode: WebSearchTool initialized")

        # 初始化状态机（自由辩论轮数根据 max_rounds 自动计算）
        effective_free = debate_config.resolve_free_rounds(ctx.max_rounds)
        self._state = DebateState(config=debate_config, effective_free_rounds=effective_free)
        logger.info(f"DebateMode: max_rounds={ctx.max_rounds}, "
                     f"constructive={debate_config.constructive_per_side*2}, "
                     f"free_debate={effective_free}, "
                     f"closing={debate_config.closing_per_side*2}")

        # 更新白板初始状态
        ctx.memory.whiteboard.update("current_topic", "add", debate_config.resolution, round_num=0, added_by="system")

        # 构建 all_agents（按阵营顺序）
        aff_agents = [a for a in ctx.participants if a.agent_id in debate_config.affirmative_ids]
        neg_agents = [a for a in ctx.participants if a.agent_id in debate_config.negative_ids]
        ctx.all_agents = [ctx.moderator] + aff_agents + neg_agents + [ctx.scribe]

        logger.info(f"DebateMode: setup complete. "
                     f"Affirmative: {[a.agent_id for a in aff_agents]}, "
                     f"Negative: {[a.agent_id for a in neg_agents]}")

    def execute_round(self, ctx: ModeContext) -> int:
        """执行一轮辩论。根据当前阶段决定发言者。"""
        state = self._state

        if state.phase == DebatePhase.CONSTRUCTIVE:
            return self._execute_constructive(ctx)
        elif state.phase == DebatePhase.FREE_DEBATE:
            return self._execute_free_debate(ctx)
        elif state.phase == DebatePhase.CLOSING:
            return self._execute_closing(ctx)
        else:
            logger.info("Debate: finished, no more rounds")
            return ctx.round_num

    def should_continue(self, ctx: ModeContext) -> bool:
        return self._state.phase != DebatePhase.FINISHED

    def get_mode_commands(self) -> dict[str, str]:
        return {
            "/debate": "查看辩论状态（阶段、阵营、发言统计）",
        }

    @property
    def debate_state(self) -> DebateState:
        return self._state

    # ------------------------------------------------------------------
    # 阶段执行
    # ------------------------------------------------------------------

    def _execute_constructive(self, ctx: ModeContext) -> int:
        """立论阶段：固定顺序交替发言。"""
        speaker_info = self._state.get_constructive_speaker()
        if speaker_info is None:
            self._state.advance_constructive()
            return ctx.round_num

        faction, agent_id = speaker_info
        agent = self._find_agent(ctx, agent_id)
        if agent is None:
            self._state.advance_constructive()
            return ctx.round_num

        ctx.round_num += 1
        ctx.session_manager.increment_round()

        faction_label = "正方" if faction == Faction.AFFIRMATIVE else "反方"
        round_info = self._build_round_info(ctx, f"你是{faction_label}辩手。{_DEBATE_INSTRUCTIONS[DebatePhase.CONSTRUCTIVE]}")

        # 宣布发言者（主持人）
        self._emit_moderator_notice(ctx, f"立论阶段。请{faction_label} — {agent.name} 陈述。")

        # 发言
        agent_ctx = ctx.context_manager.build_context(agent, ctx.memory, ctx.round_num)
        output = agent.speak(agent_ctx, ctx.llm, round_info=round_info)
        self._process_speech(ctx, agent, output, ctx.round_num, faction)

        self._state.advance_constructive()
        return ctx.round_num

    def _execute_free_debate(self, ctx: ModeContext) -> int:
        """自由辩论：当前阵营的所有成员举手，启发式选最有攻击性的。"""
        faction = self._state.get_free_debate_faction()
        candidates = self._state.get_free_debate_candidates()
        faction_label = "正方" if faction == Faction.AFFIRMATIVE else "反方"

        # 收集意图
        intents = self._collect_intents(ctx, candidates)

        if not intents:
            # 该方无人举手，跳过
            self._emit_moderator_notice(ctx, f"{faction_label}无人举手，跳过本轮。")
            self._state.advance_free_debate()
            return ctx.round_num

        # 启发式选择：Dissent > Ask > New_Angle > Extend > Clarify > Pass
        speaker_id = self._select_best_debater(intents)
        agent = self._find_agent(ctx, speaker_id)
        if agent is None:
            self._state.advance_free_debate()
            return ctx.round_num

        ctx.round_num += 1
        ctx.session_manager.increment_round()

        round_info = self._build_round_info(ctx, f"你是{faction_label}辩手。{_DEBATE_INSTRUCTIONS[DebatePhase.FREE_DEBATE]}")

        # 发言
        agent_ctx = ctx.context_manager.build_context(agent, ctx.memory, ctx.round_num)
        output = agent.speak(agent_ctx, ctx.llm, round_info=round_info)
        self._process_speech(ctx, agent, output, ctx.round_num, faction)

        self._state.advance_free_debate()
        return ctx.round_num

    def _execute_closing(self, ctx: ModeContext) -> int:
        """总结陈词：反方先总结，正方后总结。"""
        speaker_info = self._state.get_closing_speaker()
        if speaker_info is None:
            self._state.advance_closing()
            return ctx.round_num

        faction, agent_id = speaker_info
        agent = self._find_agent(ctx, agent_id)
        if agent is None:
            self._state.advance_closing()
            return ctx.round_num

        ctx.round_num += 1
        ctx.session_manager.increment_round()

        faction_label = "正方" if faction == Faction.AFFIRMATIVE else "反方"
        round_info = self._build_round_info(ctx, f"你是{faction_label}辩手。{_DEBATE_INSTRUCTIONS[DebatePhase.CLOSING]}")

        self._emit_moderator_notice(ctx, f"总结陈词。请{faction_label} — {agent.name} 做最终陈述。")

        agent_ctx = ctx.context_manager.build_context(agent, ctx.memory, ctx.round_num)
        output = agent.speak(agent_ctx, ctx.llm, round_info=round_info)
        self._process_speech(ctx, agent, output, ctx.round_num, faction)

        self._state.advance_closing()
        return ctx.round_num

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _collect_intents(self, ctx: ModeContext, agent_ids: list[str]) -> dict[str, SpeakIntent]:
        """收集指定 agent 的举手意图。"""
        import concurrent.futures
        intents: dict[str, SpeakIntent] = {}

        def _get_intent(agent):
            agent_ctx = ctx.context_manager.build_context(agent, ctx.memory, ctx.round_num)
            return agent, agent.generate_intent(agent_ctx, ctx.llm, round_info="自由辩论轮到你方发言，请举手说明你的意图。")

        agents = [a for a in ctx.participants if a.agent_id in agent_ids]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents)) as executor:
            futures = [executor.submit(_get_intent, agent) for agent in agents]
            for future in concurrent.futures.as_completed(futures):
                try:
                    agent, intent = future.result()
                    if intent and intent.intent_type != "Pass":
                        intents[agent.agent_id] = intent
                except Exception as e:
                    logger.error(f"Intent generation failed: {e}")

        return intents

    def _select_best_debater(self, intents: dict[str, SpeakIntent]) -> str:
        """启发式选择最有攻击性的发言者。优先级：Dissent > Ask > New_Angle > Extend > Clarify。"""
        priority = {"Dissent": 0, "Ask": 1, "New_Angle": 2, "Extend": 3, "Clarify": 4, "Pass": 5}
        sorted_intents = sorted(intents.items(), key=lambda x: priority.get(x[1].intent_type, 99))
        return sorted_intents[0][0]

    def _find_agent(self, ctx: ModeContext, agent_id: str) -> BaseAgent | None:
        return next((a for a in ctx.participants if a.agent_id == agent_id), None)

    def _build_round_info(self, ctx: ModeContext, debate_instruction: str) -> str:
        from src.llm.prompts import build_round_info
        base = build_round_info(
            round_num=ctx.round_num,
            max_rounds=ctx.max_rounds,
            min_rounds=ctx.config.discussion.min_rounds,
            phase=self._state.phase.value,
        )
        phase_display = self._state.get_phase_display()
        return f"{base}\n\n【辩论赛】{phase_display}\n{debate_instruction}"

    def _emit_moderator_notice(self, ctx: ModeContext, text: str) -> None:
        """主持人发言（程序性通知）。"""
        print(f"\n[辩论主持人] {text}")
        notice_msg = Message(
            id=f"msg_debate_mod_{ctx.round_num}",
            round=ctx.round_num,
            timestamp=_now_iso(),
            agent_id="moderator",
            agent_name="辩论主持人",
            agent_role="moderator",
            content=text,
            speech_type="system_notice",
            mentions=[],
        )
        ctx.memory.stream.add_message(notice_msg)
        ctx.transcript.write_message(notice_msg)

    def _process_speech(self, ctx: ModeContext, agent: BaseAgent, output: SpeechOutput, round_num: int, faction: Faction) -> None:
        """将发言写入记忆，标记阵营。"""
        faction_label = "正方" if faction == Faction.AFFIRMATIVE else "反方"
        message = Message(
            id=f"msg_{round_num:04d}_{agent.agent_id}",
            round=round_num,
            timestamp=_now_iso(),
            agent_id=agent.agent_id,
            agent_name=agent.name,
            agent_role=agent.role,
            content=output.speech,
            speech_type=output.speech_type,
            mentions=output.mentions,
            review=output.review,
            thought=output.thought,
            metadata={"faction": faction.value},
        )
        ctx.memory.stream.add_message(message)
        ctx.transcript.write_message(message)

        tag = f"[{faction_label}]"
        print(f"\n[Round {round_num}] {tag} {agent.name}:")
        print(f"  {output.speech}")

    def _build_default_config(self, ctx: ModeContext) -> DebateConfig:
        """从 participants 构建默认的辩论配置（前半正方，后半反方）。"""
        ids = [a.agent_id for a in ctx.participants]
        mid = len(ids) // 2
        return DebateConfig(
            resolution=ctx.config.discussion.max_rounds,  # resolution 从 topic 获取
            affirmative_ids=ids[:mid],
            negative_ids=ids[mid:],
        )


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat()
