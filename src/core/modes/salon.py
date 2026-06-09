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
from src.core.moderator_signal import ModeratorSignalSystem
from src.core.modes.base import DialogueModeStrategy, ModeContext
from src.core.round_monitor import RoundMonitor
from src.core.scheduling_state import SchedulingState
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

        # 更新 all_agents（加入 moderator 和 scribe）
        ctx.all_agents = [ctx.moderator] + ctx.participants + [ctx.scribe]

        # 初始化各 agent 的论证栈 core_thesis（从 soul 文件中读取）
        for agent in ctx.participants:
            if agent.soul.core_thesis:
                ctx.memory.set_core_thesis(agent.agent_id, agent.soul.core_thesis)

        logger.info("SalonMode: setup complete (moderator + scribe + signal system)")

    def execute_round(self, ctx: ModeContext) -> int:
        """完整的一轮：意图收集 → 信号 → 主持人决策 → 后处理 → 发言。"""
        import time as _time

        round_num = ctx.round_num + 1
        ctx.round_num = round_num
        ctx.session_manager.increment_round()

        round_info = self._get_round_info(ctx, round_num)
        logger.info(f"[Round {round_num}] === 开始 === phase={ctx.moderator.phase if ctx.moderator else '?'}")

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

        # --- Phase 3.5: 将主持人 speaker_focus 写入各 agent 的论证栈 ---
        if decision.speaker_focus:
            for agent_id, focus in decision.speaker_focus.items():
                ctx.memory.update_from_moderator(agent_id=agent_id, speaker_focus=focus)

        # --- Phase 4: 调度防线后处理 ---
        decision = self._post_process(ctx, round_num, decision, raw_signals, control, signals)

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
        # 检查调度器是否强制 CLOSING
        if ctx.moderator and ctx.moderator.phase == "CLOSING":
            return False
        return True

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_round_info(self, ctx: ModeContext, round_num: int) -> str:
        phase = ctx.moderator.phase if ctx.moderator else "EXPLORATION"
        return build_round_info(
            round_num=round_num,
            max_rounds=ctx.config.discussion.max_rounds,
            min_rounds=ctx.config.discussion.min_rounds,
            phase=phase,
        )

    def _collect_intents(self, ctx: ModeContext, round_num: int, round_info: str) -> dict[str, HandSignal]:
        """并发收集所有参与者的举手信号（轻量级方向信号）。"""
        import time as _time
        intents: dict[str, HandSignal] = {}

        def _get_intent(agent):
            agent_ctx = ctx.context_manager.build_context(agent, ctx.memory, round_num, context_type="intent")
            return agent, agent.generate_intent(agent_ctx, ctx.llm, round_info=round_info)

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
        recent_messages = ctx.memory.stream.get_recent_messages()
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
        """从信号数据生成感知摘要，供主持人决策参考。"""
        parts = []

        # 概念负荷
        active_concepts = ctx.round_monitor.get_active_concepts()
        concept_count = len(active_concepts)
        if concept_count > 0:
            concept_names = [c.name for c in active_concepts[:10]]
            status = "高" if concept_count > 8 else ("中" if concept_count > 5 else "低")
            parts.append(f"概念负荷：{status}（当前活跃概念 {concept_count} 个：{', '.join(concept_names)}）")

        # 具体性
        if signals and hasattr(signals, 'rounds_since_story'):
            rounds_since = signals.rounds_since_story
            if rounds_since > 0:
                urgency = "⚠️ 需要着陆" if rounds_since >= 3 else ""
                parts.append(f"具体性：距上次具体场景已 {rounds_since} 轮 {urgency}")

        # 可读性
        if signals and hasattr(signals, 'readability_score'):
            score = signals.readability_score
            if score > 0:
                level = "高（难以理解）" if score > 0.6 else ("中等" if score > 0.4 else "低（易理解）")
                parts.append(f"可读性：{level}（抽象词比例 {signals.abstract_ratio:.0%}，长句比例 {signals.long_sentence_ratio:.0%}）")

        # 高频隐喻追踪（从近期消息中检测）
        metaphor_tracking = self._detect_metaphor_drift(ctx, round_num)
        if metaphor_tracking:
            parts.append(f"隐喻追踪：{metaphor_tracking}")

        # 搜索素材池
        search_entries = ctx.memory.whiteboard._get_active_entries("search_materials")
        if search_entries:
            parts.append(f"已有检索素材：{len(search_entries)} 条（优先复用，避免重复搜索）")

        return "\n".join(parts) if parts else ""

    def _detect_metaphor_drift(self, ctx: ModeContext, round_num: int) -> str:
        """检测近5轮中被多人使用的隐喻，标记含义漂移。"""
        # 简单实现：统计近5轮中出现频率高的关键词
        # 完整实现需要语义分析，这里用频率作为近似
        recent = ctx.memory.stream.get_recent_messages()
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
        intents_summary = {
            a_id: f"[{i.direction}] → {i.target or '自由'}" for a_id, i in intents.items() if i
        }
        signal_injection = ctx.signal_system.get_moderator_injection()
        max_speakers = len(ctx.participants) // 2 + 1
        ctx_mod = ctx.context_manager.build_context(ctx.moderator, ctx.memory, round_num, context_type="moderator")

        # 生成感知数据摘要
        perception_data = self._build_perception_data(ctx, round_num, signals)

        decision = ctx.moderator.decide_agenda_and_speakers(
            ctx_mod, intents_summary, ctx.llm, max_speakers=max_speakers,
            signal_injection=signal_injection, perception_data=perception_data,
        )
        # LLM 反馈
        ctx.signal_system.update_llm_feedback(
            emotional_temperature=decision.emotional_temperature,
            perceived_tension=decision.perceived_tension,
        )
        return decision

    def _post_process(self, ctx: ModeContext, round_num: int, decision, raw_signals, control, signals):
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

        decision = ctx.scheduling_state.post_process(decision, ctx.participants, intents={}, max_speakers=max_speakers)

        if ctx.scheduling_state.should_force_closing(round_num, ctx.config.discussion.max_rounds):
            if decision.phase != "CLOSING":
                closing_notice = "讨论时间已接近尾声，现在进入最终总结阶段。请各位给出核心立场的最终陈述。"
                decision.phase = "CLOSING"
                decision.notice = (decision.notice + "\n" if decision.notice else "") + closing_notice
                logger.info(f"SchedulingState: forced CLOSING at round {round_num}")

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
        if decision.agenda_note:
            trace_parts.append(f"→ {decision.agenda_note}")
        ctx.memory.whiteboard.update("agenda_trace", "add", " | ".join(trace_parts), round_num=round_num, added_by="moderator")

        # 决策事件（用于 /monitor）
        signals_dict = dataclasses.asdict(signals) if signals and dataclasses.is_dataclass(signals) else signals
        event = {
            "event": "round_decision",
            "round": round_num,
            "phase": decision.phase,
            "speakers": decision.speakers or [],
            "rejected": list(set(intents.keys()) - set(decision.speakers or [])),
            "agenda_note": decision.agenda_note,
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

            agent_ctx = ctx.context_manager.build_context(speaker, ctx.memory, round_num, context_type="speak")
            logger.info(f"[Round {round_num}] 开始发言: {speaker.name} (LLM调用中...)")
            t_speak = _time.time()
            output = speaker.speak(
                agent_ctx, ctx.llm,
                round_info=dynamic_round_info,
                tools=ctx.tool_registry,
                emit_event=ctx.emit_event,
            )
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
            sync_result = ctx.scribe.sync_whiteboard(
                scribe_ctx, ctx.llm,
                whiteboard_chars=whiteboard_chars,
                compression_threshold=wb_config.compression_threshold_chars,
            )

            if sync_result is None:
                logger.warning(f"[ScribeSync] sync_whiteboard 返回 None (round {round_num})")
                self._write_scribe_log(ctx, round_num, "LLM调用失败", [])
                return

            ops = sync_result.operations or []
            logger.info(f"[ScribeSync] LLM 返回 {len(ops)} 个操作 (round {round_num})")
            for i, op in enumerate(ops):
                logger.info(f"  [{i}] {op.action} → {op.section}: {op.content[:80]}...")

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
