from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from src.agents.base import BaseAgent, SpeechOutput, SpeakIntent
from src.agents.moderator import ModeratorAgent
from src.agents.participant import ParticipantAgent
from src.agents.scribe import ScribeAgent
from src.config import SalonConfig, load_config
from src.core.context_manager import ContextManager
from src.core.modes import ModeContext, ModeFactory, WebCommandSource
from src.core.session import SessionManager, SessionState
from src.llm.client import LLMClient
from src.llm.prompts import build_round_info, build_summary_prompt
from src.memory import MemorySystem
from src.memory.stream import Message
from src.output.digest import save_digest
from src.output.transcript import TranscriptWriter

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path("data/sessions")
AGENTS_DIR = Path("config/agents")
SOULS_DIR = Path("config/souls")


def _load_name_to_id() -> dict[str, str]:
    """Build name→id mapping from config/agents/*.json and config/souls/*.md."""
    mapping: dict[str, str] = {}

    if AGENTS_DIR.exists():
        for f in AGENTS_DIR.glob("*.json"):
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
                aid = meta.get("id", f.stem)
                aname = meta.get("name", "")
                if aid and aname:
                    mapping[aname] = aid
            except Exception:
                continue

    if SOULS_DIR.exists():
        for f in SOULS_DIR.glob("*.md"):
            agent_id = f.stem
            if agent_id in mapping.values():
                continue
            try:
                text = f.read_text(encoding="utf-8")
                title_match = re.search(r"^#\s+(.+?)(?:\s*[—–-]\s*(.+))?$", text, re.MULTILINE)
                name = title_match.group(2).strip() if title_match and title_match.group(2) else (
                    title_match.group(1).strip() if title_match else agent_id
                )
                mapping[name] = agent_id
            except Exception:
                continue

    # Legacy compatibility
    if "moderator" in mapping.values():
        for legacy in ("苏格拉底", "主持人"):
            if legacy not in mapping:
                mapping[legacy] = "moderator"

    return mapping


_NAME_TO_ID = _load_name_to_id()


def _resolve_agent_id(name: str) -> str:
    """Resolve Chinese name or agent ID to agent ID."""
    return _NAME_TO_ID.get(name, name)


class WebOrchestrator:
    """Orchestrator variant for web UI. Runs dialogue in a background thread,
    emits SSE events via a queue, and accepts commands via another queue."""

    def __init__(self, session_id: str, config: SalonConfig, agent_ids: list[str], topic: str, mode: str = "salon", mode_config: dict | None = None):
        self.session_id = session_id
        self.config = config
        self.topic = topic
        self.agent_ids = agent_ids
        self.mode = mode
        self._mode_config = mode_config or {}

        # Queues for web integration
        self.event_queue: queue.Queue = queue.Queue()
        self.cmd_queue: queue.Queue = queue.Queue()

        # Core components
        self.context_manager = ContextManager(config)
        self.llm_client = LLMClient(config.llm)
        self.memory: MemorySystem | None = None
        self.moderator: ModeratorAgent | None = None
        self.scribe: ScribeAgent | None = None
        self.participants: list[ParticipantAgent] = []
        self.all_agents: list[BaseAgent] = []
        self.transcript: TranscriptWriter | None = None
        self.session_manager: SessionManager | None = None

        # 模式策略
        self.strategy = ModeFactory.create(mode)
        self._ctx: ModeContext | None = None

        self.state = SessionState.CREATED
        self._paused = False
        self._ended = False
        self._thread: threading.Thread | None = None

        # 后台线程池：用于异步白板同步等非阻塞任务
        self._bg_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg-task")
        self._pending_bg_futures: list = []  # 跟踪后台任务，pause 时等待完成

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the dialogue in a background thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def send_command(self, command: str) -> None:
        self.cmd_queue.put(command)

    def stop(self) -> None:
        self._ended = True
        self._paused = False
        if self._ctx:
            self._ctx._ended = True

    def pause(self) -> None:
        self._paused = True
        if self._ctx:
            self._ctx._paused = True

    def resume(self) -> None:
        self._paused = False
        if self._ctx:
            self._ctx._paused = False

    # ------------------------------------------------------------------
    # Internal run loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        try:
            self._load_agents()
            self._init_session()
            self._setup_strategy()
            # 恢复轮次计数（从已持久化的消息中读取最后一轮的轮号）
            restored_round = self.memory.stream.round_count if self.memory else 0
            if restored_round > 0:
                self._ctx.round_num = restored_round
                logger.info(f"Resumed session from round {restored_round}")
            self._emit_status("running", restored_round)
            self._main_loop()
        except Exception as e:
            logger.error(f"WebOrchestrator error: {e}", exc_info=True)
            self._emit("error", {"message": str(e)})
        finally:
            # Always save state on exit (crash recovery)
            self._save_checkpoint()
            self._cleanup()
            self._emit("done", {"reason": "finished" if not self._ended else "stopped"})

    def _init_session(self) -> None:
        self.session_manager = SessionManager(self.config)

        # Set session dir from session_id (for resume) or create new
        session_dir = Path(self.config.storage.sessions_dir) / self.session_id
        self.session_manager.session_dir = session_dir

        # If session dir already exists (resume), don't recreate
        if not (session_dir / "metadata.json").exists():
            agent_ids = [a.agent_id for a in self.all_agents]
            self.session_manager.create_session(self.topic, agent_ids, mode=self.mode)
        else:
            session_dir.mkdir(parents=True, exist_ok=True)
            # 恢复已有 metadata，确保 round_count 等状态正确
            self.session_manager.load_metadata()
            logger.info(f"Loaded existing metadata for session {self.session_id}")

        self.state = SessionState.RUNNING
        self.session_manager.update_state(SessionState.RUNNING)

        self.memory = MemorySystem(self.config, topic=self.topic)
        self.transcript = TranscriptWriter(self.session_manager.get_transcript_path())

        # Load saved state if resuming (白板从 JSON 加载，不重复添加 topic)
        self._load_checkpoint()

        # 新会话：初始化 current_topic（恢复会话时 _load_checkpoint 已加载）
        if self.topic and not self.memory.whiteboard.sections.get("current_topic"):
            self.memory.whiteboard.update("current_topic", "add", self.topic, round_num=0, added_by="system")

        # Save initial metadata
        self._save_metadata()

    def _setup_strategy(self) -> None:
        """创建 ModeContext 并初始化策略。"""
        self._ctx = ModeContext(
            config=self.config,
            participants=self.participants,
            all_agents=list(self.all_agents),
            memory=self.memory,
            context_manager=self.context_manager,
            llm=self.llm_client,
            transcript=self.transcript,
            session_manager=self.session_manager,
            command_source=WebCommandSource(self.cmd_queue),
            emit_event=self._emit,
        )

        # 初始化搜索工具和工具注册表
        if self.config.search.enabled and self.config.search.api_key:
            from src.tools.search import WebSearchTool, SearchTool
            from src.tools import ToolRegistry
            search_tool = WebSearchTool(
                api_key=self.config.search.api_key,
                max_results=self.config.search.max_results,
            )
            self._ctx.tool_registry = ToolRegistry()
            self._ctx.tool_registry.register(SearchTool(search_tool))
            logger.info("WebOrchestrator: ToolRegistry initialized with SearchTool")

        # 辩论模式需要额外的 DebateConfig
        if self.mode == "debate":
            from src.core.modes import DebateConfig
            factions = self._mode_config.get("factions", {})
            debate_config = DebateConfig(
                resolution=self.topic,
                affirmative_ids=[aid for aid, f in factions.items() if f == "affirmative"],
                negative_ids=[aid for aid, f in factions.items() if f == "negative"],
            )
            self.strategy.setup(self._ctx, debate_config=debate_config)
        else:
            self.strategy.setup(self._ctx)

        # 策略 setup 可能修改了 all_agents（添加 moderator/scribe）
        self.all_agents = self._ctx.all_agents
        self.moderator = self._ctx.moderator
        self.scribe = self._ctx.scribe

    def _load_checkpoint(self) -> None:
        """Load saved state from disk (for resume)."""
        session_dir = self.session_manager.session_dir
        if not self.memory:
            return

        # Load messages from transcript
        try:
            messages_data = self.transcript.read_all()
            for m_dict in messages_data:
                msg = Message(**m_dict)
                self.memory.stream.messages.append(msg)
            logger.info(f"Restored {len(messages_data)} messages from transcript")
        except Exception as e:
            logger.warning(f"Failed to restore messages from transcript: {e}")

        # Load whiteboard from JSON (优先) 或 Markdown (兼容旧版)
        wb_json_path = session_dir / "whiteboard.json"
        wb_md_path = session_dir / "whiteboard.md"
        if wb_json_path.exists():
            try:
                self.memory.whiteboard.load_from_file(str(wb_json_path))
                logger.info(f"Restored whiteboard from {wb_json_path}")
            except Exception as e:
                logger.warning(f"Failed to restore whiteboard JSON: {e}")
        elif wb_md_path.exists():
            try:
                wb_text = wb_md_path.read_text(encoding="utf-8")
                self._restore_whiteboard_from_markdown(wb_text)
                logger.info(f"Restored whiteboard from legacy markdown {wb_md_path}")
            except Exception as e:
                logger.warning(f"Failed to restore whiteboard markdown: {e}")



    def _restore_whiteboard_from_markdown(self, text: str) -> None:
        """从旧版 Markdown 格式恢复白板（向后兼容）。"""
        if not self.memory:
            return
        current_section = None
        in_cold_section = False
        section_map = {
            # 当前 save_to_file 使用的标签（与 whiteboard.py labels 字典一致）
            "当前的焦点（即刻交锋点）": "current_focus",
            "讨论所处阶段": "discussion_phase",
            "全局主题": "current_topic",
            "已达成的共识": "consensus",
            "活跃的分歧": "disagreements",
            "议题积压区": "backlog",
            "意外发现": "surprises",
            "议程轨迹": "agenda_trace",
            "活跃概念清单": "active_concepts",
            # 兼容旧版标签
            "当前主题": "current_topic",
            "搁置的问题": "backlog",
            "待探索的方向": "backlog",
            "Current Topic": "current_topic",
            "Consensus": "consensus",
            "Active Disagreements": "disagreements",
            "Parked Questions": "backlog",
            "To Explore": "backlog",
            "Surprises": "surprises",
        }
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("## "):
                header = line[3:].strip()
                if header == "冷板凳（已归档）":
                    in_cold_section = True
                    current_section = None
                else:
                    in_cold_section = False
                    current_section = section_map.get(header)
            elif line.startswith("### ") and in_cold_section:
                # 冷板凳下的子标题映射回原始 section
                sub_header = line[4:].strip()
                current_section = section_map.get(sub_header)
            elif line.startswith("- ") and current_section:
                content = line[2:].strip()
                # Extract round number from metadata before stripping
                round_num = 0
                added_by = "restored"
                if "（第 " in content and "添加）" in content:
                    meta_start = content.index("（第 ")
                    meta = content[meta_start:]
                    # Parse "（第 X 轮，由 Y 添加）"
                    m = re.search(r"第\s*(\d+)\s*轮", meta)
                    if m:
                        round_num = int(m.group(1))
                    m2 = re.search(r"由\s*(\S+)\s*添加", meta)
                    if m2:
                        added_by = m2.group(1)
                    content = content[:meta_start].strip()
                # Also handle English format "(round X, by Y)"
                if " (round " in content:
                    en_start = content.index(" (round ")
                    en_meta = content[en_start:]
                    m = re.search(r"round\s*(\d+)", en_meta)
                    if m:
                        round_num = int(m.group(1))
                    m2 = re.search(r"by\s*(\S+)", en_meta)
                    if m2:
                        added_by = m2.group(1)
                    content = content[:en_start].strip()
                if content and content != "（空）" and content != "(empty)":
                    self.memory.whiteboard.update(
                        current_section, "add", content,
                        round_num=round_num, added_by=added_by,
                    )
                    # Mark as cold if restored from cold section
                    if in_cold_section:
                        entries = self.memory.whiteboard.sections.get(current_section, [])
                        if entries:
                            entries[-1].cold = True

    def _save_checkpoint(self) -> None:
        """Save whiteboard to disk (for crash recovery)."""
        if not self.session_manager or not self.memory:
            return

        # 等待后台白板同步任务完成，避免丢失最新更新
        if self._pending_bg_futures:
            from concurrent.futures import wait, FIRST_EXCEPTION
            try:
                wait(self._pending_bg_futures, timeout=10)
            except Exception:
                pass
            self._pending_bg_futures = []

        try:
            session_dir = self.session_manager.session_dir
            if session_dir:
                # JSON 格式（用于恢复，保留 metadata 和 cold 标记）
                self.memory.whiteboard.save_to_file(str(session_dir / "whiteboard.json"))
                # Markdown 格式（用于人类阅读/UI）
                self.memory.whiteboard.save_to_markdown(str(session_dir / "whiteboard.md"))

            self._update_metadata()
            logger.info(f"Checkpoint saved for session {self.session_id}")
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")

    def _persist_whiteboard(self) -> None:
        """每轮结束后持久化白板到磁盘（轻量级，只写 JSON）。"""
        if not self.session_manager or not self.memory:
            return
        try:
            session_dir = self.session_manager.session_dir
            if session_dir:
                self.memory.whiteboard.save_to_file(str(session_dir / "whiteboard.json"))
        except Exception as e:
            logger.warning(f"Failed to persist whiteboard: {e}")

    def _save_metadata(self) -> None:
        meta_path = self.session_manager.session_dir / "metadata.json"
        # Read existing metadata first to preserve fields like mode, created_at
        if meta_path.exists():
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            existing = {}
        existing.update({
            "session_id": self.session_id,
            "topic": self.topic,
            "mode": existing.get("mode", self.mode),
            "participants": [a.agent_id for a in self.all_agents],
            "state": self.state.value,
            "round_count": existing.get("round_count", 0),
            "created_at": existing.get("created_at", datetime.now().isoformat()),
            "archived": existing.get("archived", False),
        })
        meta_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    def _update_metadata(self) -> None:
        if not self.session_manager:
            return
        meta_path = self.session_manager.session_dir / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            meta = {}
        meta["state"] = self.state.value
        meta["round_count"] = self.memory.stream.round_count if self.memory else 0
        if self.state == SessionState.FINISHED:
            meta["finished_at"] = datetime.now().isoformat()
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Agent loading
    # ------------------------------------------------------------------

    def _load_agents(self) -> None:
        """加载参与者。moderator/scribe 由策略的 setup 创建。"""
        from src.agents.soul import Soul
        souls_dir = Path(self.config.config_dir) / "souls"

        self.participants = []
        for raw_id in self.agent_ids:
            aid = _resolve_agent_id(raw_id)
            if aid in ("moderator", "scribe"):
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

        # all_agents 在 _setup_strategy 中由策略补充 moderator/scribe
        self.all_agents = list(self.participants)

    # ------------------------------------------------------------------
    # Main loop (adapted from Orchestrator)
    # ------------------------------------------------------------------

    def _main_loop(self) -> None:
        ctx = self._ctx

        while self.strategy.should_continue(ctx) and not ctx._ended:
            # Handle pause
            if self._paused:
                self._emit_status("paused", ctx.round_num)
                while self._paused and not ctx._ended:
                    self._drain_commands()
                    time.sleep(0.5)
                if ctx._ended:
                    break
                self._emit_status("running", ctx.round_num)

            # Check commands (框架级)
            # interview 模式由策略自己从 command_source 读取输入，不预先 drain
            if self.mode != 'interview':
                self._drain_commands()
            if ctx._ended:
                break

            # 策略执行一轮
            ctx.round_num = self.strategy.execute_round(ctx)

            # 推送状态和白板更新到前端
            self._emit_status("running", ctx.round_num)
            self._emit("whiteboard", {"content": ctx.memory.whiteboard.to_prompt_text()})

            self._maybe_summarize()

            # 每轮结束后持久化白板（JSON），防止崩溃丢失
            self._persist_whiteboard()

            # Periodic full checkpoint every 5 rounds (JSON + Markdown + metadata)
            if ctx.round_num > 0 and ctx.round_num % 5 == 0:
                self._save_checkpoint()

            self._update_metadata()

        # CLOSING round: all agents give final statements
        if not ctx._ended and ctx.moderator and ctx.memory:
            ctx.round_num = self._closing_round(ctx.round_num)

        self._wrap_up()

    def _closing_round(self, round_num: int) -> int:
        """CLOSING round: all participants give closing statements."""
        round_num += 1
        self.session_manager.increment_round()

        # Force CLOSING phase
        self.moderator._current_phase = "CLOSING"

        self._emit_status("closing", round_num)

        # Moderator closing announcement
        closing_notice = (
            f"讨论已达到最大轮次（{self.config.discussion.max_rounds} 轮），现在进入最终总结阶段。"
            "请各位参与者给出你们的总结陈词：概括你们的核心立场，以及在讨论中获得的任何让步或洞见。"
        )
        notice_msg = Message(
            id=f"msg_sys_notice_{round_num}",
            round=round_num,
            timestamp=datetime.now().isoformat(),
            agent_id="moderator",
            agent_name="System",
            agent_role="system",
            content=f"[主持人场控] {closing_notice}",
            speech_type="system_notice",
            mentions=[a.agent_id for a in self.participants],
        )
        self.memory.stream.add_message(notice_msg)
        self.transcript.write_message(notice_msg)
        self._emit("message", {
            "id": notice_msg.id,
            "round": round_num,
            "agent_id": notice_msg.agent_id,
            "agent_name": notice_msg.agent_name,
            "agent_role": notice_msg.agent_role,
            "content": notice_msg.content,
            "speech_type": notice_msg.speech_type,
            "mentions": notice_msg.mentions,
            "timestamp": notice_msg.timestamp,
        })

        # All participants give closing statements
        round_info = build_round_info(
            round_num=round_num,
            max_rounds=self.config.discussion.max_rounds,
            min_rounds=self.config.discussion.min_rounds,
            phase="CLOSING",
        )

        for agent in self.participants:
            ctx = self.context_manager.build_context(agent, self.memory, round_num)
            output = agent.speak(ctx, self.llm_client, round_info=round_info)
            self._process_speech(agent, output, round_num)

        # Final whiteboard sync
        if self.scribe:
            logger.info(f"[ScribeSync-Closing] 触发最终白板同步 (round {round_num})")
            scribe_ctx = self.context_manager.build_context(self.scribe, self.memory, round_num)
            try:
                sync_result = self.scribe.sync_whiteboard(scribe_ctx, self.llm_client)
                if sync_result is None:
                    logger.warning(f"[ScribeSync-Closing] sync_whiteboard 返回 None (round {round_num})")
                    self._write_scribe_log(round_num, "LLM调用失败", [])
                else:
                    ops = sync_result.operations or []
                    logger.info(f"[ScribeSync-Closing] LLM 返回 {len(ops)} 个操作 (round {round_num})")
                    for i, op in enumerate(ops):
                        logger.info(f"  [{i}] {op.action} → {op.section}: {op.content[:80]}...")
                    self._write_scribe_log(round_num, "成功", ops)
                    if ops:
                        for op in ops:
                            self.memory.whiteboard.update(
                                op.section, op.action, op.content,
                                round_num=round_num, added_by=self.scribe.name,
                            )
                        logger.info(f"[ScribeSync-Closing] 已应用 {len(ops)} 个白板操作 (round {round_num})")
            except Exception as e:
                logger.warning(f"[ScribeSync-Closing] 最终白板同步失败: {e}", exc_info=True)
                self._write_scribe_log(round_num, f"异常: {e}", [])

        self._save_checkpoint()
        self._update_metadata()

        return round_num

    def _get_round_info(self, round_num: int) -> str:
        return build_round_info(
            round_num=round_num,
            max_rounds=self.config.discussion.max_rounds,
            min_rounds=self.config.discussion.min_rounds,
            phase=self.moderator.phase if self.moderator else "discussion",
        )

    def _participant_turn(self, round_num: int) -> int:
        round_num += 1
        self.session_manager.increment_round()

        round_info = self._get_round_info(round_num)

        import concurrent.futures
        intents: dict[str, SpeakIntent] = {}
        eligible_agents = [a for a in self.participants if a is not None]

        # Generate intents concurrently — each agent only sees the shared history,
        # no dependency on other agents' intents this round.
        def _get_intent(agent):
            ctx = self.context_manager.build_context(agent, self.memory, round_num)
            return agent, agent.generate_intent(ctx, self.llm_client, round_info=round_info)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(eligible_agents)) as executor:
            futures = [executor.submit(_get_intent, agent) for agent in eligible_agents]
            for future in concurrent.futures.as_completed(futures):
                try:
                    agent, intent = future.result()
                    intents[agent.agent_id] = intent
                except Exception as e:
                    logger.error(f"Intent generation failed: {e}")
                    continue

        # Emit intent messages after all collected
        for agent in eligible_agents:
            intent = intents.get(agent.agent_id)
            if not intent:
                continue
            content_str = f"[举手意图: {intent.intent_type}] {intent.summary}"
            intent_msg = Message(
                id=f"msg_intent_{round_num}_{agent.agent_id}",
                round=round_num,
                timestamp=datetime.now().isoformat(),
                agent_id=agent.agent_id,
                agent_name=agent.name,
                agent_role=agent.role,
                content=content_str,
                speech_type="intent",
                mentions=[]
            )
            self.memory.stream.add_message(intent_msg)
            self.transcript.write_message(intent_msg)
            self._emit("message", {
                "id": intent_msg.id,
                "round": round_num,
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
                "agent_role": agent.role,
                "content": content_str,
                "speech_type": "intent",
                "mentions": [],
                "timestamp": intent_msg.timestamp,
            })

        # 整理意图供大模型决策
        intents_summary = {
            a_id: f"[{i.intent_type}] {i.summary}" for a_id, i in intents.items() if i
        }

        # 调用主持人进行议程与发言者决策
        max_speakers = len(self.participants) // 2 + 1
        ctx_mod = self.context_manager.build_context(self.moderator, self.memory, round_num)
        decision = self.moderator.decide_agenda_and_speakers(ctx_mod, intents_summary, self.llm_client, max_speakers=max_speakers)

        # 处理主持人干预（如果有）
        if decision.notice:
            print(f"\n[主持人场控] {decision.notice}")
            notice_msg = Message(
                id=f"msg_sys_notice_{round_num}",
                round=round_num,
                timestamp=datetime.now().isoformat(),
                agent_id="moderator",
                agent_name="System",
                agent_role="system",
                content=f"[主持人场控] {decision.notice}",
                speech_type="system_notice",
                mentions=[a.agent_id for a in self.participants]
            )
            self.memory.stream.add_message(notice_msg)
            self.transcript.write_message(notice_msg)
            self._emit("message", {
                "id": notice_msg.id,
                "round": round_num,
                "agent_id": notice_msg.agent_id,
                "agent_name": notice_msg.agent_name,
                "agent_role": notice_msg.agent_role,
                "content": notice_msg.content,
                "speech_type": notice_msg.speech_type,
                "mentions": notice_msg.mentions,
                "timestamp": notice_msg.timestamp,
            })

        # 处理被驳回的意图
        if decision.reject_intents:
            for rejected_id in decision.reject_intents:
                logger.info(f"Agent {rejected_id}'s intent was rejected by moderator.")

        # Record to agenda trace: phase + speakers + notice + agenda note
        speaker_names = [a.name for a in self.participants if a.agent_id in (decision.speakers or [])]
        trace_parts = [f"[第{round_num}轮] {decision.phase}"]
        if speaker_names:
            trace_parts.append(f"发言者: {', '.join(speaker_names)}")
        if decision.notice:
            trace_parts.append(f"场控: {decision.notice}")
        if decision.agenda_note:
            trace_parts.append(f"→ {decision.agenda_note}")
        self.memory.whiteboard.update(
            "agenda_trace", "add",
            " | ".join(trace_parts),
            round_num=round_num, added_by="moderator",
        )

        # 选出发言者列表
        speaker_ids = decision.speakers or [a.agent_id for a in self.participants]
        speakers = [
            a for aid in speaker_ids
            if (a := next((p for p in self.participants if p.agent_id == aid), None))
        ]

        for speaker in speakers:
            ctx = self.context_manager.build_context(speaker, self.memory, round_num)

            my_intent = intents.get(speaker.agent_id)
            own_intent_text = ""
            if my_intent and my_intent.intent_type != "Pass":
                own_intent_text = (
                    f"【你的发言意图提醒】你刚才举手争取发言的核心意图是：[{my_intent.intent_type}] {my_intent.summary}。\n"
                    f"请确保接下来的发言重点兑现这个意图，不要偏题。\n"
                )

            dynamic_round_info = f"{round_info}\n\n{own_intent_text}".strip()

            output = speaker.speak(
                ctx, self.llm_client,
                round_info=dynamic_round_info,
                tools=self._ctx.tool_registry if self._ctx else None,
                emit_event=self._emit,
            )
            tool_history = getattr(speaker, '_last_tool_history', [])
            self._process_speech(speaker, output, round_num, tool_history=tool_history)

        # 将 scribe 白板同步移至后台线程池执行
        if self.scribe:
            scribe_ctx = self.context_manager.build_context(self.scribe, self.memory, round_num)
            fut = self._bg_executor.submit(self._background_whiteboard_sync, scribe_ctx)
            self._pending_bg_futures.append(fut)
            # 清理已完成的 future，防止列表无限增长
            self._pending_bg_futures = [f for f in self._pending_bg_futures if not f.done()]

        return round_num

    # ------------------------------------------------------------------
    # Speech processing — emits SSE events
    # ------------------------------------------------------------------

    def _process_speech(self, agent: BaseAgent, output: SpeechOutput, round_num: int, tool_history: list | None = None) -> None:
        """非流式语音处理（用于 intent、structured output 等场景，保持向后兼容）。"""
        metadata = {}
        if tool_history:
            metadata["tool_calls"] = [
                {"tool": h["tool"], "input": h["input"], "output": h["output"]}
                for h in tool_history
            ]
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
            metadata=metadata,
        )

        self.memory.stream.add_message(message)
        self.transcript.write_message(message)

        # Emit SSE event
        event_data = {
            "id": message.id,
            "round": round_num,
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "agent_role": agent.role,
            "content": output.speech,
            "speech_type": output.speech_type,
            "mentions": output.mentions,
            "timestamp": message.timestamp,
        }
        if metadata:
            event_data["metadata"] = metadata
        self._emit("message", event_data)

        self._emit_status("running", round_num)

        # Emit whiteboard update
        self._emit("whiteboard", {
            "content": self.memory.whiteboard.to_prompt_text(),
        })



    def _process_speech_stream(
        self,
        agent: BaseAgent,
        context,
        llm: LLMClient,
        round_num: int,
        round_info: str = "",
        speech_type: str = "Extend",
    ) -> None:
        """流式语音处理：逐块发送 SSE 事件，完成后提交后台笔记本更新。

        解析 <thought> 和 <content> 标签：
        - <thought> 内容：发送 thought_start/thought_end 事件，不发送 speech_chunk
        - <content> 内容：发送 speech_chunk 事件，作为可见发言
        - 完整文本（含 thought）写入 memory/transcript 用于笔记本更新
        """
        msg_id = f"msg_{round_num:04d}_{agent.agent_id}"

        # 1. 发送 speech_start 事件
        self._emit("speech_start", {
            "id": msg_id,
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "agent_role": agent.role,
            "round": round_num,
            "speech_type": speech_type,
        })

        # 2. 流式迭代，解析标签后发送事件
        full_text = ""
        content_text = ""  # 仅 <speech> 中的发言内容
        buffer = ""
        in_thought = False
        in_content = False
        in_mentions = False
        thought_emitted = False
        mentions_buffer = ""
        extracted_mentions = []

        try:
            for chunk in agent.stream_speak(context, llm, round_info):
                full_text += chunk
                buffer += chunk

                # 解析 buffer 中的标签
                while buffer:
                    if not in_thought and not in_content:
                        # 寻找 <thought>, <speech> 或 <mentions>
                        t_idx = buffer.find("<thought>")
                        s_idx = buffer.find("<speech>")
                        m_idx = buffer.find("<mentions>")

                        # 过滤掉找不到的 index (-1)，取最小值找最先出现的标签
                        valid_indices = [(tag, idx) for tag, idx in [("thought", t_idx), ("speech", s_idx), ("mentions", m_idx)] if idx != -1]
                        
                        if valid_indices:
                            first_tag, first_idx = min(valid_indices, key=lambda x: x[1])
                            
                            if first_tag == "thought":
                                buffer = buffer[first_idx + len("<thought>"):]
                                in_thought = True
                                if not thought_emitted:
                                    self._emit("thought_start", {"id": msg_id})
                                    thought_emitted = True
                            elif first_tag == "speech":
                                buffer = buffer[first_idx + len("<speech>"):]
                                in_content = True
                            elif first_tag == "mentions":
                                buffer = buffer[first_idx + len("<mentions>"):]
                                in_mentions = True
                        else:
                            # 都没找到，检查是否有部分标签在末尾
                            partial_found = False
                            for tag in ["<thought>", "<speech>", "<mentions>"]:
                                for i in range(1, min(len(tag), len(buffer) + 1)):
                                    if buffer.endswith(tag[:i]):
                                        partial_found = True
                                        break
                                if partial_found:
                                    break
                            if partial_found:
                                break  # 等待更多数据
                            else:
                                buffer = ""  # 丢弃无标签内容
                                break

                    elif in_mentions:
                        end_idx = buffer.find("</mentions>")
                        if end_idx == -1:
                            mentions_buffer += buffer
                            buffer = ""
                            break
                        else:
                            mentions_buffer += buffer[:end_idx]
                            buffer = buffer[end_idx + len("</mentions>"):]
                            in_mentions = False
                            # 提取并发送 mentions
                            mentions_list = [m.strip() for m in mentions_buffer.split(",") if m.strip()]
                            extracted_mentions.extend(mentions_list)
                            self._emit("mentions", {"id": msg_id, "mentions": mentions_list})
                            mentions_buffer = ""

                    elif in_thought:
                        end_idx = buffer.find("</thought>")
                        if end_idx == -1:
                            buffer = ""  # 还在 thought 中，继续等待
                            break
                        else:
                            buffer = buffer[end_idx + len("</thought>"):]
                            in_thought = False
                            self._emit("thought_end", {"id": msg_id})

                    elif in_content:
                        end_idx = buffer.find("</speech>")
                        if end_idx == -1:
                            # 还在 speech 中，发送 buffer
                            content_text += buffer
                            self._emit("speech_chunk", {"id": msg_id, "chunk": buffer})
                            buffer = ""
                            break
                        else:
                            # speech 结束
                            content_chunk = buffer[:end_idx]
                            if content_chunk:
                                content_text += content_chunk
                                self._emit("speech_chunk", {"id": msg_id, "chunk": content_chunk})
                            buffer = buffer[end_idx + len("</speech>"):]
                            in_content = False

        except Exception as e:
            logger.error(f"流式发言异常 ({agent.name}): {e}")
            if not full_text:
                full_text = f"[{agent.name}的发言生成遇到问题，请稍后重试]"

        # 处理残留 buffer
        if in_content and buffer:
            content_text += buffer
            self._emit("speech_chunk", {"id": msg_id, "chunk": buffer})

        # 处理未闭合的 <thought> 标签（LLM 输出被截断）
        if in_thought:
            self._emit("thought_end", {"id": msg_id})
            in_thought = False

        # 如果从未进入 content 模式（LLM 没用标签，或标签未闭合），把 full_text 清理后当 content
        if not content_text and full_text:
            # 去掉闭合的 thought 标签及其内容
            cleaned = re.sub(r"<thought>.*?</thought>", "", full_text, flags=re.DOTALL)
            # 去掉闭合的 review 标签及其内容
            cleaned = re.sub(r"<review>.*?</review>", "", cleaned, flags=re.DOTALL)
            # 去掉闭合的 mentions 标签及其内容
            cleaned = re.sub(r"<mentions>.*?</mentions>", "", cleaned, flags=re.DOTALL)
            # 去掉未闭合的 thought/review/mentions 标签及其后内容（截断场景）
            for tag in ["<thought>", "<review>", "<mentions>"]:
                open_idx = cleaned.find(tag)
                if open_idx != -1:
                    cleaned = cleaned[:open_idx]
            # 提取 speech 标签内容（如果有）
            speech_match = re.search(r"<speech>(.*?)</speech>", cleaned, flags=re.DOTALL)
            if speech_match:
                cleaned = speech_match.group(1)
            # 去掉残留标签
            cleaned = re.sub(r"</?(?:thought|review|speech|mentions)>", "", cleaned).strip()
            if cleaned:
                content_text = cleaned
                self._emit("speech_chunk", {"id": msg_id, "chunk": cleaned})

        # 记录空内容警告（便于排查）
        if not content_text:
            logger.warning(
                f"发言内容为空 ({agent.name}, round {round_num}): "
                f"full_text={len(full_text)} chars, "
                f"in_thought={in_thought}, in_content={in_content}, "
                f"preview={full_text[:200]!r}"
            )

        # 3. 发送 speech_end 事件
        self._emit("speech_end", {
            "id": msg_id,
        })

        # 4. 用完整文本（含 thought）写入 memory 和 transcript
        message = Message(
            id=msg_id,
            round=round_num,
            timestamp=datetime.now().isoformat(),
            agent_id=agent.agent_id,
            agent_name=agent.name,
            agent_role=agent.role,
            content=full_text,  # 完整文本，含 thought
            speech_type=speech_type,
            mentions=extracted_mentions,
        )
        self.memory.stream.add_message(message)
        self.transcript.write_message(message)



        self._emit_status("running", round_num)

        # 6. 发送白板和笔记本状态更新
        self._emit("whiteboard", {
            "content": self.memory.whiteboard.to_prompt_text(),
        })


    def _background_whiteboard_sync(self, scribe_ctx) -> None:
        """后台线程：执行 scribe 白板同步任务。"""
        try:
            if not self.scribe:
                return
            round_num = self.memory.stream.round_count if self.memory else 0
            logger.info(f"[ScribeSync] 开始白板同步 (round {round_num})")

            sync_result = self.scribe.sync_whiteboard(scribe_ctx, self.llm_client)

            if sync_result is None:
                logger.warning(f"[ScribeSync] sync_whiteboard 返回 None（LLM 调用失败）(round {round_num})")
                self._write_scribe_log(round_num, "LLM调用失败", [])
                return

            ops = sync_result.operations or []
            logger.info(f"[ScribeSync] LLM 返回 {len(ops)} 个操作 (round {round_num})")
            for i, op in enumerate(ops):
                logger.info(f"  [{i}] {op.action} → {op.section}: {op.content[:80]}...")

            # 写入会话日志
            self._write_scribe_log(round_num, "成功", ops)

            if ops and self.memory:
                for op in ops:
                    self.memory.whiteboard.update(
                        op.section, op.action, op.content,
                        round_num=round_num,
                        added_by=self.scribe.name,
                    )
                self._emit("whiteboard", {
                    "content": self.memory.whiteboard.to_prompt_text(),
                })
                logger.info(f"[ScribeSync] 已应用 {len(ops)} 个白板操作 (round {round_num})")
            else:
                logger.info(f"[ScribeSync] 无操作需要应用 (round {round_num})")

        except Exception as e:
            logger.warning(f"[ScribeSync] 后台白板同步异常: {e}", exc_info=True)
            self._write_scribe_log(
                self.memory.stream.round_count if self.memory else 0,
                f"异常: {e}", [],
            )

    def _write_scribe_log(self, round_num: int, status: str, operations: list) -> None:
        """将记录员同步结果写入会话目录的日志文件。"""
        try:
            if not self.session_manager or not self.session_manager.session_dir:
                return
            log_path = self.session_manager.session_dir / "scribe_sync.log"
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
                if self.memory:
                    f.write(f"\n--- 白板快照 (round {round_num}) ---\n")
                    for section, entries in self.memory.whiteboard.sections.items():
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

    def _maybe_summarize(self) -> None:
        messages = self.memory.stream.get_messages_for_summarization()
        if messages is None:
            return

        text = "\n".join(f"{m.agent_name}: {m.content}" for m in messages)
        topic = self.memory.whiteboard.sections.get("current_topic", [])
        topic_text = topic[0].content if topic else "discussion"

        summary_messages = build_summary_prompt(topic_text, text)
        try:
            summary = self.llm_client.chat(summary_messages)
            self.memory.stream.add_summary(
                summary, messages[0].round, messages[-1].round,
            )
        except Exception as e:
            logger.warning(f"Summarization failed: {e}")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _drain_commands(self) -> None:
        while not self.cmd_queue.empty():
            try:
                raw = self.cmd_queue.get_nowait()
                self._handle_command(raw)
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Error handling command: {e}", exc_info=True)
                self._emit("error", {"message": str(e)})

    def _handle_command(self, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            return

        if not raw.startswith("/"):
            if self.memory:
                message = Message(
                    id=f"msg_human_{self.memory.stream.round_count}",
                    round=self.memory.stream.round_count,
                    timestamp=datetime.now().isoformat(),
                    agent_id="human",
                    agent_name="Human",
                    agent_role="human",
                    content=raw,
                    speech_type="intervention",
                    mentions=[],
                )
                self.memory.stream.add_message(message)
                self.transcript.write_message(message)
                self._emit("message", {
                    "id": message.id,
                    "round": message.round,
                    "agent_id": "human",
                    "agent_name": "Human",
                    "agent_role": "human",
                    "content": raw,
                    "speech_type": "intervention",
                    "mentions": [],
                    "timestamp": message.timestamp,
                })
            return

        if raw == "/pause":
            self._paused = True
            if self._ctx:
                self._ctx._paused = True
            self._save_checkpoint()
            self._emit("status", {"state": "paused", "message": "Discussion paused"})
        elif raw == "/resume":
            self._paused = False
            if self._ctx:
                self._ctx._paused = False
            self._emit("status", {"state": "running", "message": "Discussion resumed"})
        elif raw == "/end":
            self._ended = True
            if self._ctx:
                self._ctx._ended = True
            self._save_checkpoint()
            self._emit("status", {"state": "ending", "message": "Discussion ending..."})
        elif raw == "/whiteboard":
            self._emit("whiteboard", {
                "content": self.memory.whiteboard.to_prompt_text(),
            })
        elif raw.startswith("/ask") and self.memory:
            parts = raw.split(maxsplit=2)
            if len(parts) >= 3:
                target_name = parts[1].strip().lstrip("@")
                question = parts[2]
                target_agent = next(
                    (a for a in self.all_agents if a.name.lower() == target_name.lower()), None,
                )
                if target_agent:
                    message = Message(
                        id=f"msg_human_{self.memory.stream.round_count}",
                        round=self.memory.stream.round_count,
                        timestamp=datetime.now().isoformat(),
                        agent_id="human",
                        agent_name="Human",
                        agent_role="human",
                        content=question,
                        speech_type="question",
                        mentions=[target_agent.agent_id],
                    )
                    self.memory.stream.add_message(message)
                    self.transcript.write_message(message)
                    self._emit("message", {
                        "id": message.id,
                        "round": message.round,
                        "agent_id": "human",
                        "agent_name": "Human",
                        "agent_role": "human",
                        "content": question,
                        "speech_type": "question",
                        "mentions": [target_agent.agent_id],
                        "timestamp": message.timestamp,
                    })

    # ------------------------------------------------------------------
    # Wrap up
    # ------------------------------------------------------------------

    def _wrap_up(self) -> None:
        self.state = SessionState.WRAPPING_UP
        if self.session_manager:
            self.session_manager.update_state(SessionState.WRAPPING_UP)

        overview = ""
        if self.config.output.digest_auto_generate and self.scribe and self.memory:
            transcript_text = self.transcript.get_transcript_text()
            whiteboard_text = self.memory.whiteboard.to_prompt_text()
            topic = self.memory.whiteboard.sections.get("current_topic", [])
            topic_text = topic[0].content if topic else "discussion"
            participant_names = [a.name for a in self.participants]
            round_count = self.memory.stream.round_count

            # Generate overview (总览)
            try:
                overview = self.scribe.generate_overview(
                    topic_text, transcript_text,
                    self.memory.whiteboard.sections,
                    round_count, participant_names,
                    self.llm_client,
                )
            except Exception as e:
                logger.warning(f"Overview generation failed: {e}")

            # Generate detailed digest (纪要)
            try:
                digest = self.scribe.generate_digest(
                    topic_text, transcript_text, whiteboard_text,
                    self.memory.whiteboard.sections, self.llm_client,
                )
                digest_path = self.session_manager.get_digest_path()
                if digest_path:
                    save_digest(digest, digest_path, overview=overview)
            except Exception as e:
                logger.warning(f"Digest generation failed: {e}")

        # Save whiteboard (JSON + Markdown)
        if self.session_manager and self.memory:
            session_dir = self.session_manager.session_dir
            if session_dir:
                self.memory.whiteboard.save_to_file(str(session_dir / "whiteboard.json"))
                self.memory.whiteboard.save_to_markdown(str(session_dir / "whiteboard.md"))

        self.state = SessionState.FINISHED
        if self.session_manager:
            self.session_manager.finish()
        self._update_metadata()

    def _cleanup(self) -> None:
        self._bg_executor.shutdown(wait=False)
        self.llm_client.close()

    # ------------------------------------------------------------------
    # SSE helpers
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, data: dict) -> None:
        self.event_queue.put({"type": event_type, "data": data})

    def _emit_status(self, state: str, round_num: int) -> None:
        self._emit("status", {
            "state": state,
            "round": round_num,
            "paused": self._paused,
        })


# WebHostOrchestrator 已删除 — 逻辑移入 InterviewModeStrategy
# 通过 ModeFactory.create("interview") 自动选择策略


# ----------------------------------------------------------------------
# Factory function used by chat.py route
# ----------------------------------------------------------------------

def create_web_session(session_id: str) -> dict | None:
    """Create a WebOrchestrator from a session's metadata.

    Returns a dict with 'run', 'event_queue', 'cmd_queue' keys,
    or None if the session doesn't exist.
    """
    session_dir = SESSIONS_DIR / session_id
    meta_path = session_dir / "metadata.json"

    if not meta_path.exists():
        return None

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    topic = meta.get("topic", "")
    mode = meta.get("mode", "salon")
    raw_ids = meta.get("participants", [])
    agent_ids = [_resolve_agent_id(p) for p in raw_ids]
    mode_config = meta.get("mode_config")

    config = load_config()

    orchestrator = WebOrchestrator(session_id, config, agent_ids, topic, mode=mode, mode_config=mode_config)

    return {
        "run": orchestrator.start,
        "stop": orchestrator.stop,
        "pause": orchestrator.pause,
        "resume": orchestrator.resume,
        "event_queue": orchestrator.event_queue,
        "cmd_queue": orchestrator.cmd_queue,
        "orchestrator": orchestrator,
    }
