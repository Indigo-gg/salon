
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from src.config import ConversationStreamConfig


@dataclass
class Message:
    id: str
    round: int
    timestamp: str
    agent_id: str
    agent_name: str
    agent_role: str
    content: str
    speech_type: str
    mentions: list[str] = field(default_factory=list)
    review: str | None = None
    thought: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "round": self.round,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "content": self.content,
            "speech_type": self.speech_type,
            "mentions": self.mentions,
        }
        if self.review:
            d["review"] = self.review
        if self.thought:
            d["thought"] = self.thought
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    def to_prompt_line(self) -> str:
        if self.agent_role == "host":
            return f"★ [主持人 / HOST] {self.content}"
        return f"[{self.agent_name}] {self.content}"


@dataclass
class Summary:
    text: str
    from_round: int
    to_round: int


class ConversationStream:
    def __init__(self, config: ConversationStreamConfig):
        self.messages: list[Message] = []
        self.summaries: list[Summary] = []
        self.summary_batch_size = config.summary_batch_size

    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    @property
    def regular_messages(self) -> list[Message]:
        return [m for m in self.messages if m.speech_type != "intent"]

    def get_recent_messages(self, max_rounds: int = 3) -> list[Message]:
        """Return messages from the last max_rounds rounds."""
        return self.get_recent_round_messages(max_rounds)

    def get_summarized_history(self) -> str:
        if not self.summaries:
            return ""
        return "\n".join(f"[Summary rounds {s.from_round}-{s.to_round}] {s.text}" for s in self.summaries)

    def get_all_messages_text(self) -> str:
        return "\n".join(m.to_prompt_line() for m in self.messages if m.speech_type != "intent")

    def get_recent_messages_text(self, max_rounds: int = 3) -> str:
        return "\n".join(m.to_prompt_line() for m in self.get_recent_messages(max_rounds) if m.speech_type != "intent")

    def get_recent_messages_brief(self, n: int = 3, max_chars: int = 80) -> str:
        """Condensed recent messages for intent generation. Truncates each message."""
        recent = self.get_recent_round_messages(max_rounds=2)[-n:]
        lines = []
        for m in recent:
            content = m.content[:max_chars] + ("..." if len(m.content) > max_chars else "")
            lines.append(f"[{m.agent_name}] {content}")
        return "\n".join(lines)

    def get_last_round_summary(self) -> str:
        """返回最新一条摘要的文本，用于意图收集的精简 context。"""
        if not self.summaries:
            return ""
        return self.summaries[-1].text

    def get_recent_round_messages(self, max_rounds: int = 2) -> list[Message]:
        """返回最近 N 轮的完整消息（按轮次过滤）。"""
        regular = self.regular_messages
        if not regular:
            return []
        last_round = regular[-1].round
        cutoff_round = last_round - max_rounds + 1
        return [m for m in regular if m.round >= cutoff_round]

    def count_rounds_since_last_spoke(self, agent_id: str) -> int:
        regular = self.regular_messages
        for i in range(len(regular) - 1, -1, -1):
            if regular[i].agent_id == agent_id:
                return len(regular) - 1 - i
        return len(regular)

    def count_recent_mentions(self, agent_id: str, window: int = 3) -> int:
        recent = self.regular_messages[-window:]
        count = 0
        for msg in recent:
            if agent_id in msg.mentions:
                count += 1
        return count

    def was_directly_asked(self, agent_id: str) -> bool:
        regular = self.regular_messages
        if not regular:
            return False
        last = regular[-1]
        return agent_id in last.mentions and last.speech_type == "question"

    def count_consecutive_speaks(self, agent_id: str) -> int:
        count = 0
        for msg in reversed(self.regular_messages):
            if msg.agent_id == agent_id:
                count += 1
            else:
                break
        return count

    def get_messages_for_summarization(self, max_rounds: int) -> list[Message] | None:
        """Return the oldest batch of messages older than max_rounds, or None."""
        regular = self.regular_messages
        if not regular:
            return None
        last_round = regular[-1].round
        cutoff = last_round - max_rounds + 1
        old_messages = [m for m in regular if m.round < cutoff]
        already_summarized = len(self.summaries) * self.summary_batch_size
        unsummarized = old_messages[already_summarized:]
        if len(unsummarized) >= self.summary_batch_size:
            return unsummarized[:self.summary_batch_size]
        return None

    def add_summary(self, text: str, from_round: int, to_round: int) -> None:
        self.summaries.append(Summary(text=text, from_round=from_round, to_round=to_round))
        # Compress old summaries when there are too many (>5), merge oldest 2 into 1
        if len(self.summaries) > 5:
            old = self.summaries[:2]
            combined = "\n".join(s.text for s in old)
            self.summaries = [Summary(
                text=combined,
                from_round=old[0].from_round,
                to_round=old[-1].to_round,
            )] + self.summaries[2:]

    @property
    def round_count(self) -> int:
        regular = self.regular_messages
        if not regular:
            return 0
        return regular[-1].round
