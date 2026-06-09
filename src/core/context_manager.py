from __future__ import annotations

from typing import TYPE_CHECKING

from src.agents.base import BaseAgent, DiscussionContext
from src.config import SalonConfig

if TYPE_CHECKING:
    from src.memory import MemorySystem


def estimate_tokens(text: str) -> int:
    """Rough token estimate. Chinese ~1.5 tokens/char, English ~0.25 tokens/word."""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 1.5 + other_chars * 0.4)


class ContextManager:
    def __init__(self, config: SalonConfig):
        self.config = config
        self.allocation = config.context.allocation
        self.max_tokens = config.context.max_prompt_tokens

    def build_context(
        self,
        agent: BaseAgent,
        memory: MemorySystem,
        round_number: int,
        context_type: str = "speak",
    ) -> DiscussionContext:
        """为指定 Agent 构建上下文。

        Args:
            context_type: 上下文类型，决定组装哪些内容和使用哪个 token 预算。
                - "intent": 极简，仅 topic + 白板焦点 + 上轮摘要
                - "speak": 精简，topic + 白板焦点 + 最近 2 轮 + 摘要 + 笔记本
                - "moderator": 较完整，topic + 全景白板 + 最近 3 轮 + 摘要
                - "scribe": 白板+近期，topic + 全景白板 + 最近 2 轮
        """
        ctx_config = self.config.context

        # 根据 context_type 选择 token 预算
        budget_map = {
            "intent": ctx_config.intent_max_tokens,
            "speak": ctx_config.speak_max_tokens,
            "moderator": ctx_config.moderator_max_tokens,
            "scribe": ctx_config.scribe_max_tokens,
        }
        max_tokens = budget_map.get(context_type, ctx_config.speak_max_tokens)

        # Topic（所有类型都需要）
        topic_entries = memory.whiteboard.sections.get("current_topic", [])
        topic_text = topic_entries[-1].content if topic_entries else ""

        # 白板视野分离
        whiteboard_text = memory.whiteboard.to_prompt_text(round_number)   # 全景（主持人/记录员）
        whiteboard_brief = memory.whiteboard.to_brief_prompt_text()        # 聚焦（参与者）

        # --- intent 模式：极简上下文 ---
        if context_type == "intent":
            last_summary = memory.stream.get_last_round_summary()
            # 只用白板焦点 + 上轮摘要，截断到预算
            sections = {
                "whiteboard": whiteboard_brief,
                "summarized_history": last_summary,
            }
            sections = self._truncate_to_budget(sections, max_tokens=max_tokens)
            return DiscussionContext(
                topic=topic_text,
                recent_messages=[],
                recent_messages_text="",
                summarized_history=sections["summarized_history"],
                whiteboard_text="",
                whiteboard_brief=sections["whiteboard"],
                archive_text="",
                round_number=round_number,
                agent_memory_text="",
            )

        # --- scribe 模式：白板全景 + 最近 2 轮 ---
        if context_type == "scribe":
            recent = memory.stream.get_recent_round_messages(max_rounds=2)
            recent_text = "\n".join(m.to_prompt_line() for m in recent)
            sections = {
                "whiteboard": whiteboard_text,
                "recent_messages": recent_text,
            }
            sections = self._truncate_to_budget(sections, max_tokens=max_tokens)
            return DiscussionContext(
                topic=topic_text,
                recent_messages=recent,
                recent_messages_text=sections["recent_messages"],
                summarized_history="",
                whiteboard_text=sections["whiteboard"],
                whiteboard_brief=whiteboard_brief,
                archive_text="",
                round_number=round_number,
                agent_memory_text="",
            )

        # --- moderator 模式：全景白板 + 最近 3 轮 + 摘要 ---
        if context_type == "moderator":
            recent = memory.stream.get_recent_round_messages(max_rounds=3)
            recent_text = "\n".join(m.to_prompt_line() for m in recent)
            summarized_history = self._build_summarized_with_overflow(memory)
            sections = {
                "whiteboard": whiteboard_text,
                "recent_messages": recent_text,
                "summarized_history": summarized_history,
            }
            sections = self._truncate_to_budget(sections, max_tokens=max_tokens)
            return DiscussionContext(
                topic=topic_text,
                recent_messages=recent,
                recent_messages_text=sections["recent_messages"],
                summarized_history=sections["summarized_history"],
                whiteboard_text=sections["whiteboard"],
                whiteboard_brief=whiteboard_brief,
                archive_text="",
                round_number=round_number,
                agent_memory_text="",
            )

        # --- speak 模式（默认）：白板焦点 + 最近 2 轮 + 摘要 + 笔记本 ---
        recent = memory.stream.get_recent_round_messages(max_rounds=2)
        recent_text = "\n".join(m.to_prompt_line() for m in recent)
        summarized_history = self._build_summarized_with_overflow(memory)

        sections = {
            "recent_messages": recent_text,
            "summarized_history": summarized_history,
            "whiteboard": whiteboard_brief,
        }
        sections = self._truncate_to_budget(sections, max_tokens=max_tokens)

        # 获取该 agent 的论证栈（含动态计算的 used_arguments）
        used_arguments = self._compute_used_arguments(agent.agent_id, memory)
        agent_memory_text = memory.get_or_create_memory(agent.agent_id).to_prompt_text(
            used_arguments=used_arguments
        )

        return DiscussionContext(
            topic=topic_text,
            recent_messages=recent,
            recent_messages_text=sections["recent_messages"],
            summarized_history=sections["summarized_history"],
            whiteboard_text="",
            whiteboard_brief=sections["whiteboard"],
            archive_text="",
            round_number=round_number,
            agent_memory_text=agent_memory_text,
        )

    def _build_summarized_with_overflow(self, memory: MemorySystem) -> str:
        """构建包含未摘要溢出消息的摘要历史文本。"""
        summarized_history = memory.stream.get_summarized_history()
        overflow = memory.stream.get_unsummarized_overflow()
        if overflow:
            overflow_text = "\n".join(
                f"[第{m.round}轮] {m.agent_name}: {m.content}" for m in overflow
            )
            if summarized_history:
                return f"[未摘要的早期对话]\n{overflow_text}\n\n{summarized_history}"
            return f"[未摘要的早期对话]\n{overflow_text}"
        return summarized_history

    def _compute_used_arguments(self, agent_id: str, memory: MemorySystem) -> list[str]:
        """从白板 active_concepts × agent 历史发言中动态计算已使用的论据。"""
        concepts = [
            e.content for e in memory.whiteboard.sections.get("active_concepts", [])
            if not e.cold
        ]
        if not concepts:
            return []

        recent = memory.stream.get_recent_messages()
        used = []
        for msg in recent:
            if msg.agent_id == agent_id:
                for concept_raw in concepts:
                    # active_concepts 格式: "concept_name | introducer_name | round_N | active"
                    concept_name = concept_raw.split("|")[0].strip()
                    if concept_name and concept_name in msg.content:
                        used.append(concept_name)
        return list(set(used))

    def _truncate_to_budget(self, sections: dict[str, str], max_tokens: int = 0) -> dict[str, str]:
        """截断各区段到预算内。

        Args:
            max_tokens: 总 token 预算。如果 > 0，按比例分配到各区段；
                        如果 == 0，使用默认的 allocation 配置。
        """
        alloc = self.allocation
        default_budget_map = {
            "recent_messages": alloc.recent_messages,
            "summarized_history": alloc.summarized_history,
            "whiteboard": alloc.whiteboard,
        }

        if max_tokens > 0:
            # 按各区段默认比例分配总预算
            total_default = sum(default_budget_map.get(k, 1000) for k in sections)
            budget_map = {}
            for key in sections:
                default = default_budget_map.get(key, 1000)
                budget_map[key] = int(max_tokens * default / total_default) if total_default > 0 else max_tokens
        else:
            budget_map = default_budget_map

        result = {}
        for key, text in sections.items():
            budget = budget_map.get(key, 1000)
            tokens = estimate_tokens(text)
            if tokens > budget:
                ratio = budget / tokens
                char_limit = int(len(text) * ratio * 0.9)
                if char_limit > 0:
                    if key == "recent_messages":
                        # For recent messages, we MUST keep the end (newest messages)
                        truncated = text[-char_limit:]
                        # Cut at first sentence boundary to avoid mid-sentence cuts at the start
                        for sep in ["\n\n", "\n", "。", ".", "！", "!", "？", "?"]:
                            first = truncated.find(sep)
                            if 0 <= first < char_limit * 0.5:
                                truncated = truncated[first + len(sep):]
                                break
                        result[key] = "...(truncated)\n" + truncated
                    else:
                        truncated = text[:char_limit]
                        # Cut at last sentence boundary to avoid mid-sentence cuts at the end
                        for sep in ["\n\n", "\n", "。", ".", "！", "!", "？", "?"]:
                            last = truncated.rfind(sep)
                            if last > char_limit * 0.5:
                                truncated = truncated[:last + len(sep)]
                                break
                        result[key] = truncated + "\n...(truncated)"
                else:
                    result[key] = ""
            else:
                result[key] = text

        return result
