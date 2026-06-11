"""沙龙模式策略：AI 主持人自动调度，信号系统驱动。

从 CLI Orchestrator._participant_turn 和 WebOrchestrator._participant_turn 提取。
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import TYPE_CHECKING

from src.agents.base import BaseAgent, HandSignal
from src.agents.moderator import ModeratorAgent
from src.agents.scribe import ScribeAgent
from src.agents.strategist import TopicStrategist
from src.core.moderator_signal import ModeratorSignalSystem
from src.core.modes.base import DialogueModeStrategy, ModeContext
from src.core.round_monitor import RoundMonitor
from src.core.scheduling_state import SchedulingState
from src.core.session_controller import SessionController
from src.llm.prompts import build_round_info
from src.memory.stream import Message

if TYPE_CHECKING:
    from src.agents.base import SpeechOutput

logger = logging.getLogger(__name__)


class SalonModeStrategy(DialogueModeStrategy):
    """沙龙模式：AI 主持人自动调度，参与者并发举手 → 主持人决策 → 串行发言。"""

    @property
    def name(self) -> str:
        return "salon"

    def setup(self, ctx: ModeContext) -> None:
        """初始化主持人、记录员、信号系统、调度状态。"""
        from pathlib import Path

        config_dir = Path(ctx.config.config_dir)
        souls_dir = config_dir / "souls"
        roles_dir = config_dir / "roles"

        # 主持人
        moderator_role_path = roles_dir / "moderator_role.md"
        moderator_role_text = moderator_role_path.read_text(encoding="utf-8") if moderator_role_path.exists() else ""
        ctx.moderator = ModeratorAgent("moderator", "", ctx.config)
        ctx.moderator.name = "主持人"
        ctx.moderator.role = "moderator"
        if moderator_role_text:
            ctx.moderator.soul.inject_role(moderator_role_text)

        # 记录员
        scribe_role_path = roles_dir / "scribe_role.md"
        scribe_role_text = scribe_role_path.read_text(encoding="utf-8") if scribe_role_path.exists() else ""
        ctx.scribe = ScribeAgent("scribe", "", ctx.config)
        ctx.scribe.name = "记录员"
        ctx.scribe.role = "scribe"
        if scribe_role_text:
            ctx.scribe.soul.inject_role(scribe_role_text)

        # 信号系统 + 调度状态
        ctx.round_monitor = RoundMonitor(ctx.config.monitor)
        ctx.scheduling_state = SchedulingState.from_config(ctx.config.monitor)
        ctx.scheduling_state.max_rounds = ctx.config.discussion.max_rounds
        ctx.signal_system = ModeratorSignalSystem(scheduling_state=ctx.scheduling_state)

        # 搜索工具
        if ctx.config.search.enabled and ctx.config.search.api_key:
            from src.tools.search import WebSearchTool, SearchTool
            from src.tools import ToolRegistry
            ctx.search_tool = WebSearchTool(
                api_key=ctx.config.search.api_key,
                max_results=ctx.config.search.max_results,
            )
            # 创建工具注册表，注册搜索工具
            ctx.tool_registry = ToolRegistry()
            ctx.tool_registry.register(SearchTool(ctx.search_tool))
            logger.info("SalonMode: WebSearchTool + ToolRegistry initialized")

        # 战略家
        strategist_role_path = roles_dir / "strategist_role.md"
        strategist_role_text = strategist_role_path.read_text(encoding="utf-8") if strategist_role_path.exists() else ""
        ctx.strategist = TopicStrategist("strategist", "", ctx.config)
        ctx.strategist.name = "战略家"
        ctx.strategist.role = "strategist"
        if strategist_role_text:
            ctx.strategist.soul.inject_role(strategist_role_text)

        # 初始化讨论路线图（锁定不可放弃的维度）
        self._init_roadmap(ctx)

        # 初始化聚合调度器（持有 DimensionState + PhaseState + QualityGate）
        if ctx.strategist and ctx.strategist.roadmap:
            ctx.session_ctrl = SessionController(
                roadmap=ctx.strategist.roadmap,
                config=ctx.config,
                scheduling_state=ctx.scheduling_state,
            )
            logger.info("SalonMode: SessionController initialized")

        # 更新 all_agents（加入 moderator 和 scribe）
        ctx.all_agents = [ctx.moderator] + ctx.participants + [ctx.scribe]

        # 初始化各 agent 的论证栈 core_thesis（从 soul 文件中读取）
        for agent in ctx.participants:
            if agent.soul.core_thesis:
                ctx.memory.set_core_thesis(agent.agent_id, agent.soul.core_thesis)

        logger.info("SalonMode: setup complete (moderator + scribe + strategist + signal system)")

    def _init_roadmap(self, ctx: ModeContext) -> None:
        """初始化讨论路线图（开局一次性，锁定不可放弃的维度）。"""
        if not ctx.strategist:
            return
        try:
            topic_sections = ctx.memory.whiteboard.sections.get("current_topic", [])
            topic = topic_sections[-1].content if topic_sections else ""
            if not topic:
                logger.warning("[Strategist] 无法初始化路线图：话题为空")
                return
            if ctx.token_tracker:
                ctx.token_tracker.set_context(agent_id="strategist", context_type="roadmap")
            try:
                roadmap = ctx.strategist.initialize_roadmap(
                    topic, ctx.llm,
                    total_rounds=ctx.config.discussion.max_rounds,
                    language=ctx.config.discussion.language,
                )
            finally:
                if ctx.token_tracker:
                    ctx.token_tracker.clear_context()
            if roadmap:
                # 将路线图也写入白板 dimension_map（供记录员和主持人查看）
                import yaml
                dim_data = {
                    "roadmap": {
                        "core_question": roadmap.core_question,
                        "sequence": roadmap.dimension_sequence,
                    },
                    "dimensions": [
                        {
                            "id": d.id,
                            "label": d.label,
                            "core_question": d.core_question,
                            "status": "pending",
                            "depth": 0,
                            "notes": d.why_mandatory,
                            "type": "core",
                        }
                        for d in roadmap.mandatory_dimensions
                    ],
                    "current_dimension": roadmap.dimension_sequence[0] if roadmap.dimension_sequence else "",
                }
                ctx.memory.whiteboard.update(
                    "dimension_map",
                    "rewrite",
                    yaml.dump(dim_data, allow_unicode=True, default_flow_style=False),
                    round_num=0,
                    added_by="strategist",
                )
                logger.info(f"[Strategist] 路线图已初始化: {len(roadmap.mandatory_dimensions)} 个维度")
        except Exception as e:
            logger.warning(f"[Strategist] 路线图初始化失败: {e}")

    def execute_round(self, ctx: ModeContext) -> int:
        """完整的一轮：SessionController 推进 → 战略家 → 意图 → 信号 → 主持人 → 后处理 → 发言。"""
        import time as _time

        round_num = ctx.round_num + 1
        ctx.round_num = round_num
        ctx.session_manager.increment_round()

        # --- Phase 0: SessionController 推进（代码状态机驱动） ---
        anchor_quality = self._get_last_anchor_quality(ctx)
        if ctx.session_ctrl:
            directive = ctx.session_ctrl.advance_round(round_num, anchor_quality)
            ctx.current_directive = directive
            # 记录维度覆盖质量（来自上一轮记录员分析）
            self._record_dimension_coverage(ctx)
        else:
            directive = None

        # 使用 PhaseState 的阶段作为权威源
        current_phase = directive.phase if directive else (ctx.moderator.phase if ctx.moderator else "EXPLORATION")
        round_info = self._get_round_info(ctx, round_num, phase_override=current_phase)
        logger.info(f"[Round {round_num}] === 开始 === phase={current_phase}, dim={directive.dimension_id if directive else '?'}")

        # --- 战略家决策（stride=2，代码信号强制触发） ---
        strategy = None
        if ctx.strategist and (round_num == 1 or round_num % 2 == 0 or self._should_force_strategy(ctx)):
            strategy = self._strategist_decide(ctx, round_num)
        if strategy:
            # 质量门验证（交叉检查锚点回应质量）
            if ctx.session_ctrl:
                strategy = ctx.session_ctrl.validate_strategy(strategy)
            ctx.last_strategy = strategy

        # --- Phase 1: 并发收集意图 ---
        t0 = _time.time()
        intents = self._collect_intents(ctx, round_num, round_info)
        logger.info(f"[Round {round_num}] Phase1 意图收集完成: {len(intents)}人, 耗时{_time.time()-t0:.1f}s")
        if ctx._ended:
            logger.info(f"[Round {round_num}] 检测到终止，提前返回")
            return round_num

        # --- Phase 2: 信号计算 ---
        t0 = _time.time()
        signals, raw_signals, control = self._compute_signals(ctx, round_num, intents)
        logger.info(f"[Round {round_num}] Phase2 信号计算完成: 耗时{_time.time()-t0:.1f}s")

        # --- Phase 3: 主持人决策 ---
        t0 = _time.time()
        decision = self._moderator_decide(ctx, round_num, intents, signals=signals)
        logger.info(f"[Round {round_num}] Phase3 主持人决策完成: speakers={decision.speakers}, 耗时{_time.time()-t0:.1f}s")
        if ctx._ended:
            logger.info(f"[Round {round_num}] 检测到终止，提前返回")
            return round_num

        # --- Phase 4: 调度防线后处理 ---
        decision = self._post_process(ctx, round_num, decision, raw_signals, control, signals, intents=intents)

        # --- Phase 5: 记录决策 + emit ---
        self._emit_decision(ctx, round_num, decision, intents, signals)

        # --- Phase 6: 串行发言 ---
        t0 = _time.time()
        self._serial_speak(ctx, round_num, round_info, decision, intents)
        logger.info(f"[Round {round_num}] Phase6 串行发言完成: 耗时{_time.time()-t0:.1f}s")

        logger.info(f"[Round {round_num}] === 结束 ===")
        return round_num

    def should_continue(self, ctx: ModeContext) -> bool:
        # 检查轮次上限
        if ctx.round_num >= ctx.max_rounds:
            return False
        # 优先从 PhaseState 读取阶段（权威源）
        if ctx.session_ctrl and ctx.session_ctrl.phase.phase == "CLOSING":
            return False
        # 兼容：无 SessionController 时检查 moderator
        if not ctx.session_ctrl and ctx.moderator and ctx.moderator.phase == "CLOSING":
            return False
        return True

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_round_info(self, ctx: ModeContext, round_num: int, phase_override: str | None = None) -> str:
        phase = phase_override or (ctx.moderator.phase if ctx.moderator else "EXPLORATION")
        return build_round_info(
            round_num=round_num,
            max_rounds=ctx.config.discussion.max_rounds,
            min_rounds=ctx.config.discussion.min_rounds,
            phase=phase,
        )

    def _get_last_anchor_quality(self, ctx: ModeContext) -> str:
        """从上一轮记录员分析中提取锚点回应质量。"""
        if ctx.last_round_analysis and ctx.last_round_analysis.anchor_coverage:
            return ctx.last_round_analysis.anchor_coverage.quality
        return "unknown"

    def _record_dimension_coverage(self, ctx: ModeContext) -> None:
        """将记录员分析的维度覆盖质量记录到 SessionController。"""
        if not ctx.session_ctrl or not ctx.last_round_analysis:
            return
        analysis = ctx.last_round_analysis
        # 记录锚点覆盖质量
        if analysis.anchor_coverage:
            ctx.session_ctrl.record_anchor_coverage(analysis.anchor_coverage.quality)
        # 记录维度覆盖（基于 covered_dimensions）
        for dim in (analysis.covered_dimensions or []):
            quality = "deep" if dim.confidence == "high" else "surface"
            ctx.session_ctrl.dimension.record_coverage(dim.id, quality)

    def _collect_intents(self, ctx: ModeContext, round_num: int, round_info: str) -> dict[str, HandSignal]:
        """并发收集所有参与者的举手信号（轻量级方向信号）。"""
        import time as _time
        intents: dict[str, HandSignal] = {}

        def _get_intent(agent):
            agent_ctx = ctx.context_manager.build_context(agent, ctx.memory, round_num, context_type="intent")
            if ctx.token_tracker:
                ctx.token_tracker.set_context(agent_id=agent.agent_id, context_type="intent")
            try:
                return agent, agent.generate_intent(agent_ctx, ctx.llm, round_info=round_info)
            finally:
                if ctx.token_tracker:
                    ctx.token_tracker.clear_context()

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ctx.participants)) as executor:
            futures = {executor.submit(_get_intent, agent): agent for agent in ctx.participants}
            for future in concurrent.futures.as_completed(futures):
                agent_name = futures[future].name
                try:
                    agent, signal = future.result()
                    intents[agent.agent_id] = signal
                    logger.info(f"[Round {round_num}] 意图收集: {agent_name} → {signal.direction}")
                except Exception as e:
                    logger.error(f"[Round {round_num}] 意图收集失败 {agent_name}: {e}")

        # Emit lightweight signal messages
        for agent in ctx.participants:
            signal = intents.get(agent.agent_id)
            if not signal:
                continue
            target_str = f" → {signal.target}" if signal.target else ""
            content_str = f"[举手: {signal.direction}]{target_str}"
            signal_msg = Message(
                id=f"msg_signal_{round_num}_{agent.agent_id}",
                round=round_num,
                timestamp=_now_iso(),
                agent_id=agent.agent_id,
                agent_name=agent.name,
                agent_role=agent.role,
                content=content_str,
                speech_type="intent",
                mentions=[],
            )
            ctx.memory.stream.add_message(signal_msg)
            ctx.transcript.write_message(signal_msg)
            if ctx.emit_event:
                ctx.emit_event("message", signal_msg.to_dict())

        return intents

    def _compute_signals(self, ctx: ModeContext, round_num: int, intents: dict):
        """计算信号（旧系统 + 新系统）。"""
        intent_types = [i.direction for i in intents.values() if i]
        recent_messages = ctx.memory.stream.get_recent_messages(max_rounds=3)
        topic_sections = ctx.memory.whiteboard.sections.get("current_topic", [])
        topic_text = topic_sections[-1].content if topic_sections else ""

        # 旧系统
        signals = ctx.round_monitor.compute(round_num, recent_messages, topic_text, intent_types=intent_types)

        # 新系统
        participant_ids = [a.agent_id for a in ctx.participants]
        raw_signals = ctx.signal_system.compute_raw(
            round_num, recent_messages, topic_text,
            concept_registry=ctx.round_monitor._concept_registry,
            participant_ids=participant_ids,
        )
        control = ctx.signal_system.update(raw_signals)
        logger.info(f"Signal state: {ctx.signal_system.get_state_summary()}")

        return signals, raw_signals, control

    def _build_perception_data(self, ctx: ModeContext, round_num: int, signals) -> str:
        """从信号数据生成精简感知摘要（主持人只做战术调度，不做内容质量判断）。"""
        parts = []

        # 概念负荷（保留，帮助主持人判断是否需要轮换发言人）
        active_concepts = ctx.round_monitor.get_active_concepts()
        concept_count = len(active_concepts)
        if concept_count > 0:
            concept_names = [c.name for c in active_concepts[:10]]
            status = "高" if concept_count > 8 else ("中" if concept_count > 5 else "低")
            parts.append(f"概念负荷：{status}（当前活跃概念 {concept_count} 个：{', '.join(concept_names)}）")

        # 搜索素材池（保留）
        search_entries = ctx.memory.whiteboard._get_active_entries("search_materials")
        if search_entries:
            parts.append(f"已有检索素材：{len(search_entries)} 条（优先复用，避免重复搜索）")

        # 注：抽象度检测、具体性检测已移除——由战略家负责判断
        # 注：隐喻追踪已移除——由记录员负责

        return "\n".join(parts) if parts else ""

    def _detect_metaphor_drift(self, ctx: ModeContext, round_num: int) -> str:
        """检测近5轮中被多人使用的隐喻，标记含义漂移。"""
        # 简单实现：统计近5轮中出现频率高的关键词
        # 完整实现需要语义分析，这里用频率作为近似
        recent = ctx.memory.stream.get_recent_messages(max_rounds=5)
        if not recent:
            return ""

        # 收集近5轮的所有发言文本
        from collections import Counter
        word_count: Counter = Counter()
        word_rounds: dict[str, set] = {}

        for msg in recent:
            if msg.speech_type in ("intent", "system_notice"):
                continue
            if not hasattr(msg, 'round') or msg.round < round_num - 4:
                continue
            # 简单分词：提取4字以上的中文词
            import re
            words = re.findall(r'[一-鿿]{4,}', msg.content)
            for w in words:
                word_count[w] += 1
                if w not in word_rounds:
                    word_rounds[w] = set()
                word_rounds[w].add(msg.round)

        # 找出在多轮中出现的高频词
        drift_words = []
        for word, count in word_count.most_common(20):
            if count >= 3 and len(word_rounds.get(word, set())) >= 2:
                drift_words.append(f"「{word}」({count}次/{len(word_rounds[word])}轮)")

        if drift_words:
            return "以下词在近期被频繁使用，注意含义是否漂移：" + "、".join(drift_words[:5])
        return ""

    def _moderator_decide(self, ctx: ModeContext, round_num: int, intents: dict, signals=None):
        """主持人 LLM 决策。"""
        # 构建 agent_id → name 映射，帮助 LLM 区分 ID 和名字
        id_to_name = {a.agent_id: a.name for a in ctx.participants}
        intents_summary = {
            a_id: f"[{i.direction}] → {i.target or '自由'}" for a_id, i in intents.items() if i
        }
        signal_injection = ctx.signal_system.get_moderator_injection()

        # 注入战略家的场控通知（主持人只做传递）
        if ctx.last_strategy and ctx.last_strategy.moderator_notice:
            strategist_notice = f"【战略家通知】{ctx.last_strategy.moderator_notice}"
            signal_injection = f"{signal_injection}\n\n{strategist_notice}" if signal_injection else strategist_notice

        max_speakers = len(ctx.participants) // 2 + 1
        ctx_mod = ctx.context_manager.build_context(ctx.moderator, ctx.memory, round_num, context_type="moderator")

        # 精简感知数据（移除抽象度检测）
        perception_data = self._build_perception_data(ctx, round_num, signals)

        logger.info(f"[Round {round_num}] 主持人输入: {len(intents_summary)} 个意图, max_speakers={max_speakers}")

        if ctx.token_tracker:
            ctx.token_tracker.set_context(agent_id="moderator", context_type="moderator")
        try:
            decision = ctx.moderator.decide_agenda_and_speakers(
                ctx_mod, intents_summary, ctx.llm, max_speakers=max_speakers,
                signal_injection=signal_injection, perception_data=perception_data,
                round_num=round_num, id_to_name=id_to_name,
            )
        finally:
            if ctx.token_tracker:
                ctx.token_tracker.clear_context()

        # 如果战略家要求具体化，注入到主持人通知
        if ctx.last_strategy and ctx.last_strategy.grounding_needed and not decision.notice:
            decision.notice = "讨论中抽象概念比例较高，请发言者关联具体场景或例子。"

        logger.info(f"[Round {round_num}] 主持人决策: speakers={decision.speakers}, phase={decision.phase}")

        # LLM 反馈
        ctx.signal_system.update_llm_feedback(
            emotional_temperature=decision.emotional_temperature,
            perceived_tension=decision.perceived_tension,
        )
        return decision

    def _post_process(self, ctx: ModeContext, round_num: int, decision, raw_signals, control, signals, intents=None):
        """调度防线后处理。"""
        participant_ids = [a.agent_id for a in ctx.participants]
        max_speakers = len(ctx.participants) // 2 + 1

        ctx.scheduling_state.update(
            raw=raw_signals, control=control, round_num=round_num,
            speaker_ids=list(decision.speakers or []),
            all_agent_ids=participant_ids,
        )
        rounds_since_anchor = getattr(signals, 'rounds_since_anchor', 0)
        ctx.scheduling_state.update_anchor(round_num, rounds_since_anchor, decision.notice)

        # 战略约束：调整发言人优先级
        if ctx.last_strategy and intents:
            # 适配新 StrategyOutput：target_dimension 从 DimensionState 读取
            class _StrategyCompat:
                """将新 StrategyOutput 适配为 apply_strategy_constraint 期望的接口"""
                def __init__(self, strategy, session_ctrl):
                    target_dim = (
                        session_ctrl.dimension.current_dimension_id
                        if session_ctrl
                        else ""
                    )
                    self.direction = type('Dir', (), {
                        'preferred_agents': strategy.preferred_agents,
                        'anchor_question': strategy.anchor_question,
                        'target_dimension': target_dim,
                    })()
                    self.convergence_response = None

            compat = _StrategyCompat(ctx.last_strategy, ctx.session_ctrl)
            original_speakers = list(decision.speakers or [])
            final_speakers, forced = ctx.scheduling_state.apply_strategy_constraint(
                decision, compat, intents, ctx.participants
            )
            decision.speakers = final_speakers
            ctx._forced_callouts = forced
            logger.info(f"[Round {round_num}] 战略约束: {original_speakers} -> {final_speakers}")

        pre_pp_speakers = list(decision.speakers or [])
        decision = ctx.scheduling_state.post_process(decision, ctx.participants, intents={}, max_speakers=max_speakers)
        if list(decision.speakers or []) != pre_pp_speakers:
            logger.info(f"[Round {round_num}] post_process 改变了 speakers: {pre_pp_speakers} -> {decision.speakers}")

        # Phase 2: 使用 PhaseState 作为 phase 唯一权威源
        # （替代原 should_force_closing 直接修改 decision.phase 的逻辑）
        if ctx.current_directive:
            decision.phase = ctx.current_directive.phase
        elif ctx.scheduling_state.should_force_closing(round_num, ctx.config.discussion.max_rounds):
            # 兼容无 SessionController 的情况
            if decision.phase != "CLOSING":
                closing_notice = "讨论时间已接近尾声，现在进入最终总结阶段。请各位给出核心立场的最终陈述。"
                decision.phase = "CLOSING"
                decision.notice = (decision.notice + "\n" if decision.notice else "") + closing_notice
                logger.info(f"SchedulingState: forced CLOSING at round {round_num}")

        # 最终保底：确保至少 max_speakers 人发言
        max_sp = len(ctx.participants) // 2 + 1
        if len(decision.speakers or []) < max_sp:
            all_ids = [a.agent_id for a in ctx.participants]
            missing = [aid for aid in all_ids if aid not in (decision.speakers or [])]
            for aid in missing:
                if len(decision.speakers or []) >= max_sp:
                    break
                decision.speakers = list(decision.speakers or []) + [aid]
            logger.warning(f"[Round {round_num}] 最终保底: speakers 补充为 {decision.speakers}")

        return decision

    def _emit_decision(self, ctx: ModeContext, round_num: int, decision, intents: dict, signals):
        """记录决策到白板和事件。"""
        import dataclasses
        import json

        # 主持人 notice
        if decision.notice:
            print(f"\n[主持人场控] {decision.notice}")
            notice_msg = Message(
                id=f"msg_sys_notice_{round_num}",
                round=round_num,
                timestamp=_now_iso(),
                agent_id="moderator",
                agent_name="System",
                agent_role="system",
                content=f"[主持人场控] {decision.notice}",
                speech_type="system_notice",
                mentions=[a.name for a in ctx.participants],
            )
            ctx.memory.stream.add_message(notice_msg)
            ctx.transcript.write_message(notice_msg)
            if ctx.emit_event:
                ctx.emit_event("message", notice_msg.to_dict())

        # 主持人提问锚定：将核心问题写入 current_focus
        if decision.pending_question:
            ctx.memory.whiteboard.update(
                section="current_focus",
                action="rewrite",
                content=f"【待回答】{decision.pending_question}",
                round_num=round_num,
                added_by="moderator",
            )
            logger.info(f"[Moderator] 锚定核心问题到 current_focus: {decision.pending_question}")

        # 记录被驳回的意图
        if decision.reject_intents:
            for rejected_id in decision.reject_intents:
                logger.info(f"Agent {rejected_id}'s intent was rejected by moderator.")

        # 白板议程轨迹
        speaker_names = [a.name for a in ctx.participants if a.agent_id in (decision.speakers or [])]
        trace_parts = [f"[第{round_num}轮] {decision.phase}"]
        if speaker_names:
            trace_parts.append(f"发言者: {', '.join(speaker_names)}")
        if decision.notice:
            trace_parts.append(f"场控: {decision.notice}")
        # 维度信息（从 directive 读取，不再依赖 LLM 的 StrategyOutput）
        dim_id = ctx.current_directive.dimension_id if ctx.current_directive else None
        if dim_id:
            anchor_q = ctx.last_strategy.anchor_question if ctx.last_strategy else ""
            label_part = f" — {anchor_q}" if anchor_q else ""
            trace_parts.append(f"→ 维度: {dim_id}{label_part}")
            # 维度切换信息（从 directive 读取）
            if ctx.current_directive.should_switch_dim:
                trace_parts.append(f"[维度切换: {ctx.current_directive.switch_reason}]")
        ctx.memory.whiteboard.update("agenda_trace", "add", " | ".join(trace_parts), round_num=round_num, added_by="moderator")

        # 决策事件（用于 /monitor）
        signals_dict = dataclasses.asdict(signals) if signals and dataclasses.is_dataclass(signals) else signals
        strategy_dim = ctx.current_directive.dimension_id if ctx.current_directive else None
        strategy_anchor = ctx.last_strategy.anchor_question if ctx.last_strategy else None
        strategy_switch = ctx.current_directive.should_switch_dim if ctx.current_directive else False
        event = {
            "event": "round_decision",
            "round": round_num,
            "phase": decision.phase,
            "speakers": decision.speakers or [],
            "rejected": list(set(intents.keys()) - set(decision.speakers or [])),
            "strategy_dimension": strategy_dim,
            "strategy_anchor": strategy_anchor,
            "strategy_switch": strategy_switch,
            "notice": decision.notice,
            "emotional_temperature": decision.emotional_temperature,
            "perceived_tension": decision.perceived_tension,
            "signals": signals_dict,
            "intents": {aid: {"direction": i.direction, "target": i.target, "energy": i.energy} for aid, i in intents.items()},
        }
        ctx.decision_history.append(event)
        logger.info(f"Decision: {json.dumps(event, ensure_ascii=False)}")

    def _serial_speak(self, ctx: ModeContext, round_num: int, round_info: str, decision, intents: dict):
        """被选中的参与者逐个发言。"""
        import time as _time

        speaker_ids = decision.speakers or [a.agent_id for a in ctx.participants]
        speakers = [
            a for aid in speaker_ids
            if (a := next((p for p in ctx.participants if p.agent_id == aid), None))
        ]
        logger.info(f"[Round {round_num}] _serial_speak: {len(speakers)}位发言者 {[s.name for s in speakers]}")

        breathing_hints = ctx.signal_system.get_participant_injection()

        for speaker in speakers:
            # 每人发言前检查终止（优先）和暂停
            if ctx._ended:
                logger.info(f"[Round {round_num}] 检测到终止信号，跳过剩余发言")
                break
            if ctx._paused:
                logger.info(f"[Round {round_num}] 检测到暂停信号，等待恢复 ({speaker.name})")
                while ctx._paused and not ctx._ended:
                    _time.sleep(0.5)
                if ctx._ended:
                    break

            my_signal = intents.get(speaker.agent_id)

            dynamic_round_info = round_info
            if breathing_hints:
                dynamic_round_info = f"{dynamic_round_info}\n\n{breathing_hints}"

            # 战略方向注入
            strategy_text = self._build_strategy_injection(ctx, speaker.agent_id)
            if strategy_text:
                dynamic_round_info = f"{strategy_text}\n\n{dynamic_round_info}"

            agent_ctx = ctx.context_manager.build_context(speaker, ctx.memory, round_num, context_type="speak")
            logger.info(f"[Round {round_num}] 开始发言: {speaker.name} (LLM调用中...)")
            if ctx.token_tracker:
                ctx.token_tracker.set_context(agent_id=speaker.agent_id, context_type="speak")
            t_speak = _time.time()
            try:
                output = speaker.speak(
                    agent_ctx, ctx.llm,
                    round_info=dynamic_round_info,
                    tools=ctx.tool_registry,
                    emit_event=ctx.emit_event,
                )
            finally:
                if ctx.token_tracker:
                    ctx.token_tracker.clear_context()
            logger.info(f"[Round {round_num}] {speaker.name} 发言完成: type={output.speech_type}, len={len(output.speech)}, 耗时{_time.time()-t_speak:.1f}s")

            # 读取工具调用历史
            tool_history = getattr(speaker, '_last_tool_history', [])
            _process_speech(ctx, speaker, output, round_num, tool_history=tool_history)

            # 更新论证栈的 next_direction
            if output.next_direction:
                ctx.memory.update_from_speech(
                    agent_id=speaker.agent_id,
                    next_direction=output.next_direction,
                )

        # 记录员白板同步（每轮发言结束后触发）
        self._scribe_sync(ctx, round_num)

        # 记录员每轮结构化分析（Phase 1 依赖此数据）
        round_analysis = self._scribe_analyze(ctx, round_num)
        if round_analysis:
            ctx.last_round_analysis = round_analysis

    def _scribe_sync(self, ctx: ModeContext, round_num: int) -> None:
        """记录员白板同步。每轮发言结束后调用。"""
        if not ctx.scribe:
            return

        wb_config = ctx.config.memory.whiteboard
        whiteboard_chars = ctx.memory.whiteboard.total_chars()

        # 判断是否触发同步：周期触发 或 压缩触发
        interval_trigger = round_num > 0 and round_num % wb_config.auto_update_interval == 0
        compression_trigger = (
            wb_config.compression_threshold_chars > 0
            and whiteboard_chars > wb_config.compression_threshold_chars
        )

        if not (interval_trigger or compression_trigger):
            return

        trigger_reason = "interval" if interval_trigger else "compression"
        logger.info(f"[ScribeSync] 触发白板同步 (round {round_num}, 原因: {trigger_reason}, 白板字数: {whiteboard_chars})")

        try:
            scribe_ctx = ctx.context_manager.build_context(ctx.scribe, ctx.memory, round_num, context_type="scribe")
            if ctx.token_tracker:
                ctx.token_tracker.set_context(agent_id="scribe", context_type="scribe")
            try:
                sync_result = ctx.scribe.sync_whiteboard(
                    scribe_ctx, ctx.llm,
                    whiteboard_chars=whiteboard_chars,
                    compression_threshold=wb_config.compression_threshold_chars,
                )
            finally:
                if ctx.token_tracker:
                    ctx.token_tracker.clear_context()

            if sync_result is None:
                logger.warning(f"[ScribeSync] sync_whiteboard 返回 None (round {round_num})")
                self._write_scribe_log(ctx, round_num, "LLM调用失败", [])
                return

            ops = sync_result.operations or []
            logger.info(f"[ScribeSync] LLM 返回 {len(ops)} 个操作 (round {round_num})")
            for i, op in enumerate(ops):
                logger.info(f"  [{i}] {op.action} → {op.section}: {op.content[:80]}...")

            # 质量门验证：白板操作 allowlist 检查
            if ctx.session_ctrl:
                ops = ctx.session_ctrl.quality_gate.validate_whiteboard_operations(ops)
                if len(ops) != len(sync_result.operations or []):
                    logger.info(f"[ScribeSync] 质量门过滤后剩余 {len(ops)} 个操作")

            # 写入会话日志
            self._write_scribe_log(ctx, round_num, "成功", ops)

            if ops:
                for op in ops:
                    ctx.memory.whiteboard.update(
                        section=op.section, action=op.action, content=op.content,
                        round_num=round_num, added_by="scribe",
                    )
                logger.info(f"[ScribeSync] 已应用 {len(ops)} 个白板操作 (round {round_num})")
            else:
                logger.info(f"[ScribeSync] 无操作需要应用 (round {round_num})")

        except Exception as e:
            logger.warning(f"[ScribeSync] 白板同步异常: {e}", exc_info=True)
            self._write_scribe_log(ctx, round_num, f"异常: {e}", [])

    def _scribe_analyze(self, ctx: ModeContext, round_num: int):
        """记录员每轮结构化分析。在白板同步之后运行。"""
        if not ctx.scribe:
            return None

        scribe_ctx = ctx.context_manager.build_context(
            ctx.scribe, ctx.memory, round_num, context_type="scribe"
        )
        dim_labels = self._get_dimension_labels(ctx)

        # 获取本轮锚定问题（从战略家输出）
        anchor_question = ""
        if ctx.last_strategy:
            anchor_question = ctx.last_strategy.anchor_question

        if ctx.token_tracker:
            ctx.token_tracker.set_context(agent_id="scribe", context_type="scribe_analyze")
        try:
            result = ctx.scribe.analyze_round(
                scribe_ctx, ctx.llm, dim_labels,
                anchor_question=anchor_question,
                language=ctx.config.discussion.language,
            )
            if result:
                # 质量门验证：交叉检查 LLM 的锚点回应判断
                if result.anchor_coverage and ctx.session_ctrl:
                    novelty = ctx.scheduling_state.get_latest_novelty() if ctx.scheduling_state else 0.5
                    dim_round_count = ctx.session_ctrl.dimension.dim_round_count
                    result.anchor_coverage = ctx.session_ctrl.quality_gate.validate_anchor_coverage(
                        result.anchor_coverage, novelty, dim_round_count
                    )

                coverage_info = ""
                if result.anchor_coverage:
                    ac = result.anchor_coverage
                    coverage_info = f", anchor={'addressed' if ac.was_addressed else 'ignored'}({ac.quality})"
                logger.info(
                    f"[ScribeAnalyze] Round {round_num}: "
                    f"{len(result.arguments)} args, "
                    f"{len(result.new_angles)} new angles, "
                    f"{len(result.covered_dimensions)} dims covered{coverage_info}"
                )
            return result
        except Exception as e:
            logger.warning(f"[ScribeAnalyze] 分析失败 (round {round_num}): {e}")
            return None
        finally:
            if ctx.token_tracker:
                ctx.token_tracker.clear_context()

    def _get_dimension_labels(self, ctx: ModeContext) -> list[str]:
        """从白板 dimension_map section 提取维度标签列表。"""
        entries = ctx.memory.whiteboard.sections.get("dimension_map", [])
        if not entries:
            return []
        try:
            import yaml
            data = yaml.safe_load(entries[-1].content)
            if isinstance(data, dict) and "dimensions" in data:
                return [
                    f"{d['label']}（核心问题：{d.get('core_question', '?')}）"
                    if isinstance(d, dict) and d.get('core_question')
                    else d.get('label', '?')
                    for d in data["dimensions"]
                    if isinstance(d, dict)
                ]
        except Exception:
            pass
        return []

    def _parse_dimension_map(self, ctx: ModeContext) -> dict | None:
        """解析白板中的 dimension_map YAML 数据。"""
        entries = ctx.memory.whiteboard.sections.get("dimension_map", [])
        if not entries:
            return None
        try:
            import yaml
            data = yaml.safe_load(entries[-1].content)
            if isinstance(data, dict):
                return data
            # 兜底：如果记录员写了列表格式，转换为 dict
            if isinstance(data, list):
                logger.warning("[DimensionMap] YAML 为列表格式，自动转换为字典")
                return {"dimensions": data, "emergent": [], "last_new_dimension_round": 0}
            logger.warning(f"[DimensionMap] YAML 解析结果类型异常: {type(data).__name__}")
            return None
        except Exception:
            return None

    def _should_force_strategy(self, ctx: ModeContext) -> bool:
        """代码级强制触发判断——不依赖 LLM 布尔值。"""
        # 信号1：维度轮次接近上限（SessionController 驱动）
        if ctx.session_ctrl:
            dim_state = ctx.session_ctrl.dimension
            if dim_state.dim_round_count >= dim_state.max_rounds_per_dim - 1:
                logger.info(f"[Strategy] 强制触发：维度轮次 {dim_state.dim_round_count}/{dim_state.max_rounds_per_dim}")
                return True
            if dim_state.consecutive_low_coverage >= 1:
                logger.info(f"[Strategy] 强制触发：连续低覆盖 {dim_state.consecutive_low_coverage} 轮")
                return True

        # 信号2：新颖度分数持续走低
        if ctx.scheduling_state:
            novelty = ctx.scheduling_state.get_latest_novelty()
            if novelty < ctx.scheduling_state.novelty_low_threshold:
                logger.info(f"[Strategy] 强制触发：novelty={novelty:.2f} < {ctx.scheduling_state.novelty_low_threshold}")
                return True

        # 信号3（兼容旧逻辑）：记录员判断需要升级
        if ctx.last_round_analysis and ctx.last_round_analysis.anchor_coverage:
            if ctx.last_round_analysis.anchor_coverage.needs_escalation:
                logger.info("[Strategy] 强制触发：记录员判断 needs_escalation=True")
                return True

        return False

    def _strategist_decide(self, ctx: ModeContext, round_num: int):
        """战略家决策——在意图收集之前运行。"""
        if not ctx.strategist:
            return None

        strat_ctx = ctx.context_manager.build_context(
            ctx.strategist, ctx.memory, round_num, context_type="scribe"
        )

        analysis_text = self._format_round_analysis(ctx.last_round_analysis)

        # 获取上一轮锚定问题的回应检查
        last_anchor = ""
        last_coverage = None
        if ctx.last_strategy:
            last_anchor = ctx.last_strategy.anchor_question
        if ctx.last_round_analysis and ctx.last_round_analysis.anchor_coverage:
            last_coverage = ctx.last_round_analysis.anchor_coverage

        if ctx.token_tracker:
            ctx.token_tracker.set_context(agent_id="strategist", context_type="strategy")
        try:
            return ctx.strategist.decide_strategy(
                context=strat_ctx,
                llm=ctx.llm,
                round_analysis_text=analysis_text,
                round_num=round_num,
                total_rounds=ctx.config.discussion.max_rounds,
                last_anchor_question=last_anchor,
                last_anchor_coverage=last_coverage,
                language=ctx.config.discussion.language,
            )
        finally:
            if ctx.token_tracker:
                ctx.token_tracker.clear_context()

    def _format_round_analysis(self, analysis) -> str:
        """将 RoundAnalysis 格式化为战略家可读的文本。"""
        if not analysis:
            return "（尚无分析数据）"

        parts = []
        if analysis.arguments:
            parts.append("核心论点：")
            for arg in analysis.arguments:
                line = f"  - {arg.agent_id}: {arg.core_claim}"
                if arg.key_metaphor:
                    line += f" [比喻: {arg.key_metaphor}]"
                if arg.responds_to:
                    line += f" [回应: {arg.responds_to}]"
                parts.append(line)

        if analysis.new_angles:
            parts.append(f"新讨论角度：{', '.join(analysis.new_angles)}")

        if analysis.covered_dimensions:
            parts.append("触及的维度：")
            for dim in analysis.covered_dimensions:
                parts.append(f"  - {dim.id} ({dim.confidence}): {dim.evidence}")

        if analysis.convergence_hint:
            parts.append(f"收敛判断：{analysis.convergence_hint}")

        # 锚定问题回应检查（新增）
        if analysis.anchor_coverage:
            ac = analysis.anchor_coverage
            quality_map = {
                "deep": "深入回应", "surface": "表面回应",
                "token": "敷衍", "ignored": "完全没回应", "unknown": "未知",
            }
            parts.append(f"锚定问题回应：{quality_map.get(ac.quality, ac.quality)}")
            if ac.who_addressed:
                parts.append(f"  回应者：{', '.join(ac.who_addressed)}")
            if ac.evidence:
                parts.append(f"  证据：{ac.evidence[:100]}")

        return "\n".join(parts) if parts else "（无分析数据）"

    def _format_dimension_map(self, ctx: ModeContext) -> str:
        """将维度地图格式化为可读文本（兼容新路线图格式）。"""
        dim_map = self._parse_dimension_map(ctx)
        if not dim_map:
            return "（维度地图尚未初始化）"

        parts = []

        # 路线图信息
        roadmap = dim_map.get("roadmap", {})
        if roadmap:
            parts.append(f"核心追问：{roadmap.get('core_question', '?')}")
            parts.append(f"探索顺序：{' → '.join(roadmap.get('sequence', []))}")
            parts.append("")

        current_dim = dim_map.get("current_dimension", "")

        for d in dim_map.get("dimensions", []):
            if not isinstance(d, dict):
                continue
            status = d.get("status", "unknown")
            depth = d.get("depth", 0)
            dim_id = d.get("id", "?")
            is_current = "▶ " if dim_id == current_dim else "  "
            parts.append(f"{is_current}[{status}] {dim_id}: {d.get('label', '?')} (depth={depth})")
            if d.get("core_question"):
                parts.append(f"      核心问题: {d['core_question']}")
            if d.get("notes"):
                parts.append(f"      备注: {d['notes']}")

        return "\n".join(parts) if parts else "（维度地图为空）"

    def _build_strategy_signal_summary(self, ctx: ModeContext) -> str:
        """为战略家构建信号摘要（含收敛信号）。"""
        parts = []
        current_round = ctx.round_num

        # 简单收敛信号
        dim_map = self._parse_dimension_map(ctx)
        if dim_map:
            participants = ctx.participants

            # 信号 1：维度锁定——只有一个 active 维度且深度超过阈值
            active_dims = [
                d for d in dim_map.get("dimensions", [])
                if isinstance(d, dict) and d.get("status") == "active"
            ]
            if len(active_dims) == 1:
                depth = active_dims[0].get("depth", 0)
                threshold = max(6, int(len(participants) * 1.5))
                if depth >= threshold:
                    parts.append(
                        f"⚠️ 维度锁定：'{active_dims[0].get('label', '?')}' "
                        f"已连续讨论 {depth} 轮（阈值 {threshold}）"
                    )

            # 信号 2：维度发现活力丧失——距离上次新增维度已过 N 轮
            last_new_round = dim_map.get("last_new_dimension_round")
            if last_new_round is not None and current_round > 0:
                stale_threshold = max(4, int(len(participants) * 1.0))
                stale_rounds = current_round - last_new_round
                if stale_rounds >= stale_threshold:
                    parts.append(
                        f"⚠️ 维度发现停滞：距离上次新增维度已过 {stale_rounds} 轮"
                        f"（阈值 {stale_threshold}）。讨论可能在已知维度中空转。"
                    )

        # 从信号系统获取基础信号
        if ctx.signal_system:
            state = ctx.signal_system.get_state_summary()
            if state:
                parts.append(f"信号状态: {state}")

        return "\n".join(parts) if parts else "（无信号数据）"

    def _build_strategy_injection(self, ctx: ModeContext, agent_id: str) -> str:
        """构建 CoT 强制思考模板，注入发言者的思考过程。"""
        strategy = ctx.last_strategy
        if not strategy:
            return ""

        injection = strategy.cot_template

        # 如果是强制点名的 agent（preferred 但 energy=0）
        forced = getattr(ctx, '_forced_callouts', set())
        if agent_id in forced:
            injection += (
                f"\n\n⚠️ 主持人直接向你提问：{strategy.anchor_question}\n"
                f"请你必须回应这个问题。即使你这一轮没有主动举手，"
                f"主持人认为你的视角对这个方向至关重要。"
            )

        return injection

    def _write_scribe_log(self, ctx: ModeContext, round_num: int, status: str, operations: list) -> None:
        """将记录员同步结果写入会话目录的日志文件。"""
        try:
            session_dir = ctx.session_manager.session_dir if ctx.session_manager else None
            if not session_dir:
                return
            log_path = session_dir / "scribe_sync.log"
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{timestamp}] Round {round_num} | 状态: {status}\n")
                if operations:
                    for i, op in enumerate(operations):
                        f.write(f"  操作{i+1}: {op.action} → {op.section}\n")
                        f.write(f"    内容: {op.content}\n")
                else:
                    f.write("  操作: （无）\n")
                # 写入当前白板快照
                if ctx.memory:
                    f.write(f"\n--- 白板快照 (round {round_num}) ---\n")
                    for section, entries in ctx.memory.whiteboard.sections.items():
                        active = [e for e in entries if not e.cold]
                        if active:
                            f.write(f"\n## {section}\n")
                            for e in active:
                                f.write(f"  - [{e.round}] {e.content}\n")
                        else:
                            cold = [e for e in entries if e.cold]
                            f.write(f"\n## {section}\n")
                            if cold:
                                f.write(f"  （{len(cold)}条已归档）\n")
                            else:
                                f.write("  （空）\n")
        except Exception as e:
            logger.warning(f"[ScribeSync] 写入日志失败: {e}")
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat()


def _process_speech(ctx: ModeContext, agent: BaseAgent, output: SpeechOutput, round_num: int, tool_history: list | None = None) -> None:
    """将发言写入记忆和转录，打印到终端，推送 SSE 事件。"""
    metadata = {}
    if tool_history:
        metadata["tool_calls"] = [
            {"tool": h["tool"], "input": h["input"], "output": h["output"]}
            for h in tool_history
        ]
    # Mode A 原生思维链（仅当 thought 为空时存入，避免覆盖 Mode B 的外部化思考）
    native_thinking = getattr(agent, '_last_thinking', '')
    if native_thinking and not output.thought:
        metadata["native_thinking"] = native_thinking
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
        metadata=metadata,
    )
    ctx.memory.stream.add_message(message)
    ctx.transcript.write_message(message)

    # 注意：论证栈的更新由调用方负责（speaker_focus 在 Phase 3.5，next_direction 在 _serial_speak 中）

    role_tag = {"moderator": "Mod", "participant": "Agent", "scribe": "Scribe"}.get(agent.role, "Agent")
    print(f"\n[Round {round_num}] [{role_tag}] {agent.name}:")
    print(f"  {output.speech}")

    # 推送 SSE 事件到前端
    if ctx.emit_event:
        ctx.emit_event("message", message.to_dict())
        # 白板更新（非每条都推，由 scribe 定期同步时推送）
