"""会谈模式策略：人类主持人驱动，参与者举手等待批准。

从 WebHostOrchestrator 提取。
"""

from __future__ import annotations

import concurrent.futures
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.agents.base import BaseAgent, SpeakIntent
from src.agents.scribe import ScribeAgent
from src.core.modes.base import DialogueModeStrategy, ModeContext
from src.memory.stream import Message

if TYPE_CHECKING:
    from src.agents.base import SpeechOutput

logger = logging.getLogger(__name__)


class InterviewModeStrategy(DialogueModeStrategy):
    """会谈模式：人类主持人提问 → 参与者举手 → 主持人批准发言。"""

    @property
    def name(self) -> str:
        return "interview"

    def setup(self, ctx: ModeContext) -> None:
        """会谈模式不需要 AI 主持人和信号系统。"""
        from pathlib import Path

        config_dir = Path(ctx.config.config_dir)
        roles_dir = config_dir / "roles"

        # 记录员
        scribe_role_path = roles_dir / "scribe_role.md"
        scribe_role_text = scribe_role_path.read_text(encoding="utf-8") if scribe_role_path.exists() else ""
        ctx.scribe = ScribeAgent("scribe", "", ctx.config)
        ctx.scribe.name = "记录员"
        ctx.scribe.role = "scribe"
        if scribe_role_text:
            ctx.scribe.soul.inject_role(scribe_role_text)

        # 不初始化主持人和信号系统
        ctx.moderator = None
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
            logger.info("InterviewMode: WebSearchTool initialized")

        ctx.all_agents = ctx.participants + [ctx.scribe]

        logger.info("InterviewMode: setup complete (no moderator, no signal system)")

    def execute_round(self, ctx: ModeContext) -> int:
        """等待人类输入 → 处理命令 → 返回。一轮可能不产生任何发言。"""
        if ctx.command_source is None:
            logger.warning("InterviewMode: no command_source, skipping round")
            return ctx.round_num

        # 阻塞等待人类输入
        raw = ctx.command_source.wait(timeout=30)
        if raw is None:
            return ctx.round_num  # 超时，继续等

        raw = raw.strip()
        if not raw:
            return ctx.round_num

        # 处理命令
        self._handle_input(ctx, raw)
        return ctx.round_num

    def should_continue(self, ctx: ModeContext) -> bool:
        """会谈模式持续到人类 /end。"""
        return not ctx._ended

    def get_mode_commands(self) -> dict[str, str]:
        return {
            "/approve <名字>": "指定发言人回答",
            "直接输入文字": "作为主持人发言，触发参与者举手",
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _handle_input(self, ctx: ModeContext, raw: str) -> None:
        """处理人类输入：/approve 或普通文字。"""

        # /approve: 指定发言人
        if raw.startswith("/approve"):
            self._handle_approve(ctx, raw)
            return

        # /ask: 提问并触发举手
        if raw.startswith("/ask"):
            self._handle_ask(ctx, raw)
            return

        # 普通文字：作为主持人发言，触发举手
        if not raw.startswith("/"):
            self._handle_host_message(ctx, raw)
            return

        # 其他命令：尝试框架级处理（由编排器转发）
        logger.info(f"InterviewMode: unknown command '{raw}', ignoring")

    def _handle_host_message(self, ctx: ModeContext, text: str) -> None:
        """主持人发言 → 存入记忆 → 触发参与者举手。"""
        ctx.session_manager.increment_round()
        ctx.round_num = ctx.memory.stream.round_count

        message = Message(
            id=f"msg_host_{int(datetime.now().timestamp() * 1000)}",
            round=ctx.round_num,
            timestamp=datetime.now().isoformat(),
            agent_id="host",
            agent_name="主持人",
            agent_role="host",
            content=text,
            speech_type="question",
            mentions=[],
        )
        ctx.memory.stream.add_message(message)
        ctx.transcript.write_message(message)
        _emit(ctx, "message", _msg_to_dict(message))

        # 触发举手
        self._trigger_hand_raising(ctx)

    def _handle_approve(self, ctx: ModeContext, raw: str) -> None:
        """主持人批准某个参与者发言。"""
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            return

        target_name = parts[1].strip()
        target_agent = next(
            (a for a in ctx.all_agents if a.name.lower() == target_name.lower()), None,
        )
        if not target_agent:
            logger.warning(f"InterviewMode: agent '{target_name}' not found")
            return

        round_num = ctx.memory.stream.round_count
        round_info = "你正在接受主持人采访。请直接回答主持人的问题，然后再展开讨论。"

        agent_ctx = ctx.context_manager.build_context(target_agent, ctx.memory, round_num)
        output = target_agent.speak(agent_ctx, ctx.llm, round_info=round_info)
        _process_speech(ctx, target_agent, output, round_num)

    def _handle_ask(self, ctx: ModeContext, raw: str) -> None:
        """主持人用 /ask 提问 → 存入记忆 → 触发举手。"""
        ctx.session_manager.increment_round()
        ctx.round_num = ctx.memory.stream.round_count

        # 提取问题内容
        question = raw[4:].strip()  # 去掉 "/ask "
        message = Message(
            id=f"msg_host_{int(datetime.now().timestamp() * 1000)}",
            round=ctx.round_num,
            timestamp=datetime.now().isoformat(),
            agent_id="host",
            agent_name="主持人",
            agent_role="host",
            content=question,
            speech_type="question",
            mentions=[],
        )
        ctx.memory.stream.add_message(message)
        ctx.transcript.write_message(message)
        _emit(ctx, "message", _msg_to_dict(message))

        # 触发举手
        self._trigger_hand_raising(ctx)

    def _trigger_hand_raising(self, ctx: ModeContext) -> None:
        """主持人发言后，并发收集所有参与者的举手意图。"""
        round_num = ctx.memory.stream.round_count
        round_info = "主持人刚刚发言了。请判断你是否想要回应，如果想，请举手说明你的意图。"

        agents = [a for a in ctx.participants + [ctx.scribe] if a is not None]

        def _get_intent(agent):
            agent_ctx = ctx.context_manager.build_context(agent, ctx.memory, round_num)
            return agent, agent.generate_intent(agent_ctx, ctx.llm, round_info=round_info)

        intents: dict[str, SpeakIntent] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(agents)) as executor:
            futures = [executor.submit(_get_intent, agent) for agent in agents]
            for future in concurrent.futures.as_completed(futures):
                try:
                    agent, intent = future.result()
                    intents[agent.agent_id] = intent
                except Exception as e:
                    logger.error(f"Intent generation failed: {e}")

        # Emit intent messages
        for agent in agents:
            intent = intents.get(agent.agent_id)
            if not intent:
                continue
            content_str = f"[举手意图: {intent.intent_type}] {intent.summary}"
            intent_msg = Message(
                id=f"msg_intent_{int(datetime.now().timestamp() * 1000)}_{agent.agent_id}",
                round=round_num,
                timestamp=datetime.now().isoformat(),
                agent_id=agent.agent_id,
                agent_name=agent.name,
                agent_role=agent.role,
                content=content_str,
                speech_type="intent",
                mentions=[],
            )
            ctx.memory.stream.add_message(intent_msg)
            ctx.transcript.write_message(intent_msg)
            _emit(ctx, "message", _msg_to_dict(intent_msg))


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _emit(ctx: ModeContext, event_type: str, data: dict) -> None:
    """通过回调发送事件（Web 模式用）。CLI 模式 emit_event 为 None，静默忽略。"""
    if ctx.emit_event:
        ctx.emit_event(event_type, data)


def _msg_to_dict(msg: Message) -> dict:
    return {
        "id": msg.id,
        "round": msg.round,
        "agent_id": msg.agent_id,
        "agent_name": msg.agent_name,
        "agent_role": msg.agent_role,
        "content": msg.content,
        "speech_type": msg.speech_type,
        "mentions": msg.mentions,
        "timestamp": msg.timestamp,
    }


def _process_speech(ctx: ModeContext, agent: BaseAgent, output: SpeechOutput, round_num: int) -> None:
    """将发言写入记忆和转录，发送事件。"""
    message = Message(
        id=f"msg_{round_num:04d}_{agent.agent_id}",
        round=round_num,
        timestamp=datetime.now().isoformat(),
        agent_id=agent.agent_id,
        agent_name=agent.name,
        agent_role=agent.role,
        content=output.speech,
        speech_type=output.speech_type,
        mentions=output.mentions,
        review=output.review,
        thought=output.thought,
    )
    ctx.memory.stream.add_message(message)
    ctx.transcript.write_message(message)

    role_tag = {"moderator": "Mod", "participant": "Agent", "scribe": "Scribe"}.get(agent.role, "Agent")
    print(f"\n[Round {round_num}] [{role_tag}] {agent.name}:")
    print(f"  {output.speech}")

    _emit(ctx, "message", _msg_to_dict(message))
