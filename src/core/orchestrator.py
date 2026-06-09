"""编排器：对话系统的框架层。

负责生命周期管理、参与者加载、记忆/转录初始化、收尾。
模式特定的调度逻辑委托给 DialogueModeStrategy。
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
import time
from pathlib import Path

from src.agents.base import BaseAgent
from src.agents.participant import ParticipantAgent
from src.config import SalonConfig
from src.core.context_manager import ContextManager
from src.core.modes import CommandSource, ModeContext, ModeFactory
from src.core.session import SessionManager, SessionState
from src.human.commands import ParsedCommand
from src.human.interface import HumanInterface
from src.llm.client import LLMClient
from src.llm.prompts import build_round_info, build_summary_prompt
from src.memory import MemorySystem
from src.memory.stream import Message
from src.output.digest import save_digest
from src.output.transcript import TranscriptWriter

logger = logging.getLogger(__name__)


class CLITerminalCommandSource(CommandSource):
    """基于 HumanInterface 的 CLI 命令源。"""

    def __init__(self, human_interface: HumanInterface):
        self._hi = human_interface

    def try_get(self) -> str | None:
        return self._hi.check_input_now()

    def wait(self, timeout: float = 30) -> str | None:
        return self._hi.wait_for_input(timeout)


class Orchestrator:
    """CLI 版本的编排器。负责框架级逻辑，模式特定逻辑委托给策略。"""

    def __init__(self, config: SalonConfig):
        self.config = config
        self.session_manager = SessionManager(config)
        self.context_manager = ContextManager(config)
        self.human_interface = HumanInterface(config.human)
        self.llm_client = LLMClient(config.llm)
        self.participants: list[ParticipantAgent] = []
        self.state = SessionState.CREATED
        self._ctx: ModeContext | None = None  # 在 run() 中初始化

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def run(self, topic: str, agent_ids: list[str], mode: str = "salon") -> None:
        """启动对话。"""
        # 加载参与者（moderator/scribe 由策略的 setup 创建）
        self._load_participants(agent_ids)

        # 创建会话
        self.session_manager.create_session(topic, agent_ids, mode=mode)
        self.state = SessionState.RUNNING
        self.session_manager.update_state(SessionState.RUNNING)

        # 初始化记忆
        memory = MemorySystem(self.config, topic=topic)
        transcript = TranscriptWriter(self.session_manager.get_transcript_path())

        # 创建策略
        strategy = ModeFactory.create(mode)

        # 构建上下文
        self._ctx = ModeContext(
            config=self.config,
            participants=self.participants,
            all_agents=list(self.participants),  # 策略 setup 后会补充 moderator/scribe
            memory=memory,
            context_manager=self.context_manager,
            llm=self.llm_client,
            transcript=transcript,
            session_manager=self.session_manager,
            command_source=CLITerminalCommandSource(self.human_interface),
        )

        # 策略初始化（辩论模式需要额外配置）
        if mode == "debate":
            from src.core.modes import DebateConfig
            # CLI 模式：默认前半正方，后半反方
            ids = [a.agent_id for a in self.participants]
            mid = len(ids) // 2
            debate_config = DebateConfig(
                resolution=topic,
                affirmative_ids=ids[:mid],
                negative_ids=ids[mid:],
            )
            strategy.setup(self._ctx, debate_config=debate_config)
        else:
            strategy.setup(self._ctx)

        # 打印 banner
        self._print_banner(topic, [a.name for a in self._ctx.all_agents], mode)

        # 启动 Web API 服务器（后台线程）
        agents_info = {
            a.agent_id: {"name": a.name, "role": a.role}
            for a in self._ctx.all_agents
        }
        try:
            from src.api import start_server
            session_dir = str(self.session_manager.session_dir) if self.session_manager.session_dir else None
            self._api_thread = start_server(memory, agents_info, session_dir=session_dir)
            print(f"[API] http://127.0.0.1:8765/replay")
            print(f"[API] http://127.0.0.1:8765/memory")
            print(f"[API] http://127.0.0.1:8765/export")
        except Exception as e:
            logger.warning(f"Failed to start API server: {e}")
            self._api_thread = None

        try:
            self._main_loop(strategy)
        except KeyboardInterrupt:
            print("\n\nDiscussion interrupted by user.")
        except Exception as e:
            logger.error(f"Discussion error: {e}", exc_info=True)
            print(f"\nError: {e}")
        finally:
            self._cleanup()

    # ------------------------------------------------------------------
    # 参与者加载（只加载参与者，moderator/scribe 由策略创建）
    # ------------------------------------------------------------------

    def _load_participants(self, agent_ids: list[str]) -> None:
        souls_dir = Path(self.config.config_dir) / "souls"
        self.participants = []

        for raw_id in agent_ids:
            aid = raw_id.strip()
            if not aid or aid in ("moderator", "scribe"):
                continue
            soul_path = souls_dir / f"{aid}.md"
            if not soul_path.exists():
                logger.warning(f"Soul file not found for {aid}, skipping")
                continue
            try:
                agent = ParticipantAgent(aid, str(soul_path), self.config)
                self.participants.append(agent)
            except Exception as e:
                logger.error(f"Failed to load soul {aid}: {e}")

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def _main_loop(self, strategy) -> None:
        ctx = self._ctx

        while strategy.should_continue(ctx) and not ctx._ended:
            # 检查人类输入（非阻塞）
            raw = ctx.command_source.try_get() if ctx.command_source else None
            if raw:
                cmd = ParsedCommand.parse(raw)
                if not self._handle_command(cmd, strategy):
                    break
                if ctx._paused:
                    self._wait_for_resume(ctx)
                    if ctx._ended:
                        break
                    continue

            if ctx._ended:
                break

            # 策略执行一轮
            ctx.round_num = strategy.execute_round(ctx)

            # 框架级后处理
            self._maybe_summarize(ctx)
            self._scribe_sync(ctx)

        # CLOSING 轮
        if not ctx._ended and ctx.moderator:
            self._closing_round(ctx)

        self._wrap_up(ctx)

    def _wait_for_resume(self, ctx: ModeContext) -> None:
        """暂停期间等待恢复或结束。"""
        while ctx._paused and not ctx._ended:
            raw = ctx.command_source.wait(timeout=1) if ctx.command_source else None
            if raw:
                cmd = ParsedCommand.parse(raw)
                if not self._handle_command(cmd, None):
                    break

    # ------------------------------------------------------------------
    # CLOSING 轮（框架级，所有模式共享）
    # ------------------------------------------------------------------

    def _closing_round(self, ctx: ModeContext) -> None:
        round_num = ctx.round_num + 1
        ctx.round_num = round_num
        ctx.session_manager.increment_round()

        if ctx.moderator:
            ctx.moderator._current_phase = "CLOSING"

        print(f"\n\n{'='*60}")
        print("  讨论进入最终总结阶段（CLOSING）")
        print(f"{'='*60}")

        closing_notice = (
            f"讨论已进入最终总结阶段（第 {round_num} 轮）。"
            "请各位参与者给出你们的总结陈词：概括你们的核心立场，以及在讨论中获得的任何让步或洞见。"
        )
        notice_msg = Message(
            id=f"msg_sys_notice_{round_num}",
            round=round_num,
            timestamp=self._now_iso(),
            agent_id="moderator",
            agent_name="System",
            agent_role="system",
            content=f"[主持人场控] {closing_notice}",
            speech_type="system_notice",
            mentions=[a.agent_id for a in ctx.participants],
        )
        ctx.memory.stream.add_message(notice_msg)
        ctx.transcript.write_message(notice_msg)
        print(f"\n[主持人场控] {closing_notice}")

        round_info = build_round_info(
            round_num=round_num,
            max_rounds=ctx.config.discussion.max_rounds,
            min_rounds=ctx.config.discussion.min_rounds,
            phase="CLOSING",
        )

        for agent in ctx.participants:
            agent_ctx = ctx.context_manager.build_context(agent, ctx.memory, round_num)
            output = agent.speak(agent_ctx, ctx.llm, round_info=round_info)
            _process_speech(ctx, agent, output, round_num)

        # Final whiteboard sync
        if ctx.scribe:
            scribe_ctx = ctx.context_manager.build_context(ctx.scribe, ctx.memory, round_num)
            sync_result = ctx.scribe.sync_whiteboard(scribe_ctx, ctx.llm)
            if sync_result and sync_result.operations:
                for op in sync_result.operations:
                    ctx.memory.whiteboard.update(
                        section=op.section, action=op.action, content=op.content,
                        round_num=round_num, added_by="scribe",
                    )

    # ------------------------------------------------------------------
    # 命令处理（框架级 + 转发给策略）
    # ------------------------------------------------------------------

    def _handle_command(self, cmd: ParsedCommand, strategy) -> bool:
        """处理命令。返回 False 表示应退出主循环。"""
        command = cmd.command
        ctx = self._ctx

        if command == "/end":
            ctx._ended = True
            return False

        elif command == "/pause":
            ctx._paused = True
            print("\n[System: Discussion paused. Type /resume to continue.]")
            return True

        elif command == "/resume":
            ctx._paused = False
            print("\n[System: Discussion resumed.]")
            return True

        elif command == "/status":
            print(f"\n--- Status ---")
            print(f"State: {self.state.value}")
            print(f"Round: {ctx.memory.stream.round_count}")
            print(f"Participants: {', '.join(a.name for a in ctx.participants)}")
            print(f"Whiteboard:\n{ctx.memory.whiteboard.to_prompt_text()}")
            return True

        elif command == "/whiteboard":
            print(f"\n--- Whiteboard ---\n{ctx.memory.whiteboard.to_prompt_text()}")
            return True

        elif command == "/notebook":
            self._cmd_notebook(cmd.target)
            return True

        elif command == "/memory":
            print(f"\n[System] Memory cards: http://127.0.0.1:8765/memory")
            self._cmd_notebook(None)
            return True

        elif command == "/monitor":
            self._cmd_monitor(cmd.content)
            return True

        elif command == "/ask":
            if cmd.target and cmd.content:
                target_agent = next((a for a in ctx.all_agents if a.name.lower() == cmd.target.lower()), None)
                if target_agent:
                    message = Message(
                        id=f"msg_human_{ctx.memory.stream.round_count}",
                        round=ctx.memory.stream.round_count,
                        timestamp=self._now_iso(),
                        agent_id="human",
                        agent_name="Human",
                        agent_role="human",
                        content=cmd.content,
                        speech_type="question",
                        mentions=[target_agent.agent_id],
                    )
                    ctx.memory.stream.add_message(message)
                    ctx.transcript.write_message(message)
                    print(f"\n[System: Question sent to {target_agent.name}]")
                else:
                    print(f"\n[System: Agent '{cmd.target}' not found.]")
            else:
                print("\n[System: Usage: /ask @role_name question]")
            return True

        elif command == "/help":
            from src.human.commands import format_help
            print(f"\n{format_help()}")
            # 显示模式特有命令
            if strategy:
                mode_cmds = strategy.get_mode_commands()
                if mode_cmds:
                    print("\n--- Mode-specific commands ---")
                    for cmd_name, desc in mode_cmds.items():
                        print(f"  {cmd_name:20s} {desc}")
            return True

        elif command == "/skip":
            print("\n[System: Skipping current topic.]")
            return True

        elif command == "/inject":
            if cmd.target and cmd.content:
                target_agent = next((a for a in ctx.all_agents if a.name.lower() == cmd.target.lower()), None)
                if target_agent:
                    print(f"\n[System: Instruction injected to {target_agent.name}]")
                else:
                    print(f"\n[System: Agent '{cmd.target}' not found.]")
            return True

        return True

    # ------------------------------------------------------------------
    # 框架级工具方法
    # ------------------------------------------------------------------

    def _maybe_summarize(self, ctx: ModeContext) -> None:
        messages = ctx.memory.stream.get_messages_for_summarization()
        if messages is None:
            return

        text = "\n".join(f"{m.agent_name}: {m.content}" for m in messages)
        topic = ctx.memory.whiteboard.sections.get("current_topic", [])
        topic_text = topic[0].content if topic else "discussion"

        summary_messages = build_summary_prompt(topic_text, text)
        try:
            summary = ctx.llm.chat(summary_messages)
            ctx.memory.stream.add_summary(summary, messages[0].round, messages[-1].round)
        except Exception as e:
            logger.warning(f"Summarization failed: {e}")

    def _scribe_sync(self, ctx: ModeContext) -> None:
        """定期白板同步。"""
        if not ctx.scribe:
            return
        wb_config = ctx.config.memory.whiteboard
        round_num = ctx.round_num
        interval_trigger = round_num > 0 and round_num % wb_config.auto_update_interval == 0
        compression_trigger = (
            wb_config.compression_threshold_chars > 0
            and ctx.memory.whiteboard.total_chars() > wb_config.compression_threshold_chars
        )
        if interval_trigger or compression_trigger:
            trigger_reason = "interval" if interval_trigger else "compression"
            logger.info(f"[ScribeSync] 触发白板同步 (round {round_num}, 原因: {trigger_reason})")

            scribe_ctx = ctx.context_manager.build_context(ctx.scribe, ctx.memory, round_num, context_type="scribe")
            sync_result = ctx.scribe.sync_whiteboard(
                scribe_ctx, ctx.llm,
                whiteboard_chars=ctx.memory.whiteboard.total_chars(),
                compression_threshold=wb_config.compression_threshold_chars,
            )

            if sync_result is None:
                logger.warning(f"[ScribeSync] sync_whiteboard 返回 None (round {round_num})")
                return

            ops = sync_result.operations or []
            logger.info(f"[ScribeSync] LLM 返回 {len(ops)} 个操作 (round {round_num})")
            for i, op in enumerate(ops):
                logger.info(f"  [{i}] {op.action} → {op.section}: {op.content[:80]}...")

            if ops:
                for op in ops:
                    ctx.memory.whiteboard.update(
                        section=op.section, action=op.action, content=op.content,
                        round_num=round_num, added_by="scribe",
                    )
            else:
                logger.info(f"[ScribeSync] 无操作需要应用 (round {round_num})")

    def _cmd_monitor(self, arg: str | None) -> None:
        """处理 /monitor 命令。"""
        ctx = self._ctx
        if not ctx or not ctx.decision_history:
            print("\n[Monitor] 暂无决策记录（还没有完成任何一轮调度）。")
            return

        arg = (arg or "").strip().lower()

        if arg == "signals":
            print("\n--- 信号趋势 ---")
            print(f"{'轮次':>4}  {'温度':>4}  {'紧张':>8}  {'密度':>5}  {'故事':>4}  {'锚点':>4}  {'可读':>5}")
            print("-" * 52)
            for ev in ctx.decision_history:
                sig = ev.get("signals") or {}
                print(
                    f"{ev['round']:>4}  "
                    f"{ev['emotional_temperature']:>4.1f}  "
                    f"{ev['perceived_tension']:>8}  "
                    f"{sig.get('density_score', '—'):>5}  "
                    f"{sig.get('rounds_since_story', '—'):>4}  "
                    f"{sig.get('rounds_since_anchor', '—'):>4}  "
                    f"{sig.get('readability_score', '—'):>5}"
                )
            return

        history = ctx.decision_history if arg == "all" else ctx.decision_history[-5:]
        label = "全部" if arg == "all" else "最近"

        print(f"\n--- {label}决策历史 ({len(history)} 轮) ---")
        for ev in history:
            rejected = ev.get("rejected", [])
            speakers = ev.get("speakers", [])
            print(f"\n  Round {ev['round']}  [{ev['phase']}]")
            print(f"    发言者: {', '.join(speakers)}")
            if rejected:
                print(f"    被跳过: {', '.join(rejected)}")
            if ev.get("agenda_note"):
                print(f"    议程: {ev['agenda_note']}")
            if ev.get("notice"):
                print(f"    场控: {ev['notice']}")
            print(f"    温度: {ev['emotional_temperature']:.1f}  紧张: {ev['perceived_tension']}")
            for aid, info in ev.get("intents", {}).items():
                mark = "✓" if aid in speakers else "✗"
                print(f"    {mark} {aid}: [{info['type']}] {info['summary']}")

    def _cmd_notebook(self, target: str | None) -> None:
        """处理 /notebook 命令：查看 agent 的会话记忆。"""
        ctx = self._ctx
        if not ctx:
            print("\n[System: No active session.]")
            return

        if not target:
            # 列出所有 agent 的记忆概览
            print("\n--- Agent Memories ---")
            for agent in ctx.all_agents:
                mem = ctx.memory.get_or_create_memory(agent.agent_id)
                n_stances = len(mem.expressed_stances)
                n_contribs = len(mem.unique_contributions)
                n_disagree = len(mem.active_disagreements)
                print(f"  {agent.name}（{agent.agent_id}）: 立场{n_stances} | 贡献{n_contribs} | 分歧{n_disagree}")
            print("\n用法: /notebook @角色名  查看详细记忆")
            return

        # 查看指定 agent 的记忆
        agent = next((a for a in ctx.all_agents if a.name.lower() == target.lower() or a.agent_id == target), None)
        if not agent:
            print(f"\n[System: Agent '{target}' not found.]")
            return

        mem = ctx.memory.get_or_create_memory(agent.agent_id)
        text = mem.to_prompt_text()
        if not text:
            print(f"\n--- {agent.name} 的记忆 ---\n（空）")
        else:
            print(f"\n--- {agent.name} 的记忆 ---\n{text}")

        # 显示该 agent 最近一条发言的推理过程
        recent = [m for m in ctx.memory.stream.messages if m.agent_id == agent.agent_id and m.speech_type not in ("intent",)]
        if recent:
            last = recent[-1]
            if last.review or last.thought:
                print(f"\n--- {agent.name} 最近一次推理（第 {last.round} 轮）---")
                if last.review:
                    print(f"  [review] {last.review[:300]}")
                if last.thought:
                    print(f"  [thought] {last.thought[:300]}")

    def _wrap_up(self, ctx: ModeContext) -> None:
        """收尾：生成纪要、保存白板、标记完成。"""
        self.state = SessionState.WRAPPING_UP
        if ctx.session_manager:
            ctx.session_manager.update_state(SessionState.WRAPPING_UP)

        print(f"\n\n{'='*60}")
        print("  讨论结束，正在生成纪要...")
        print(f"{'='*60}")

        try:
            if ctx.scribe:
                scribe_ctx = ctx.context_manager.build_context(ctx.scribe, ctx.memory, ctx.round_num)
                overview = ctx.scribe.generate_overview(scribe_ctx, ctx.llm)
                if overview:
                    print(f"\n--- 讨论概览 ---\n{overview}")

            save_digest(ctx.memory, ctx.transcript, ctx.session_manager.get_session_dir())

            if ctx.memory:
                session_dir = ctx.session_manager.get_session_dir()
                ctx.memory.whiteboard.save_to_file(str(session_dir / "whiteboard.json"))
                ctx.memory.whiteboard.save_to_markdown(str(session_dir / "whiteboard.md"))

        except Exception as e:
            logger.error(f"Wrap-up error: {e}", exc_info=True)
            print(f"\nError during wrap-up: {e}")

        self.state = SessionState.FINISHED
        if ctx.session_manager:
            ctx.session_manager.update_state(SessionState.FINISHED)

        print(f"\n{'='*60}")
        print("  讨论已完成")
        print(f"{'='*60}")

    def _cleanup(self) -> None:
        self.llm_client.close()

    def _now_iso(self) -> str:
        from datetime import datetime
        return datetime.now().isoformat()

    def _print_banner(self, topic: str, participants: list[str], mode: str) -> None:
        print(f"\n{'='*60}")
        print(f"  Salon - 多智能体对话协作系统")
        print(f"{'='*60}")
        print(f"  Topic: {topic}")
        print(f"  Agents: {', '.join(participants)}")
        print(f"  Mode: {mode}")
        print(f"  Max Rounds: {self.config.discussion.max_rounds}")
        print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _process_speech(ctx: ModeContext, agent: BaseAgent, output, round_num: int, tool_history: list | None = None) -> None:
    """将发言写入记忆和转录。"""
    from src.agents.base import SpeechOutput
    # 构建 metadata：如果有工具调用历史，附着到消息上
    metadata = {}
    if tool_history:
        metadata["tool_calls"] = [
            {
                "tool": h["tool"],
                "input": h["input"],
                "output": h["output"],
            }
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

    # 更新 agent 的会话记忆（从 SpeechOutput 结构化字段中增量提取）
    ctx.memory.update_agent_memory(
        agent_id=agent.agent_id,
        speech_text=output.speech,
        thought_text=output.thought or "",
        speech_type=output.speech_type,
        mentions=output.mentions,
        understood_claims=output.understood_claims,
    )

    role_tag = {"moderator": "Mod", "participant": "Agent", "scribe": "Scribe"}.get(agent.role, "Agent")
    print(f"\n[Round {round_num}] [{role_tag}] {agent.name}:")
    print(f"  {output.speech}")


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat()
