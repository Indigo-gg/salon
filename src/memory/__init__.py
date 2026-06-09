from __future__ import annotations

import re

from src.config import SalonConfig
from src.memory.agent_memory import ArgumentStack
from src.memory.stream import ConversationStream
from src.memory.whiteboard import SharedWhiteboard


class MemorySystem:
    def __init__(self, config: SalonConfig, topic: str = ""):
        self.stream = ConversationStream(config.memory.conversation_stream)
        self.whiteboard = SharedWhiteboard(config.memory.whiteboard, topic=topic)
        self.agent_memories: dict[str, ArgumentStack] = {}
        self.config = config

    def get_or_create_memory(self, agent_id: str) -> ArgumentStack:
        """获取指定 agent 的论证栈，不存在则创建。"""
        if agent_id not in self.agent_memories:
            self.agent_memories[agent_id] = ArgumentStack(agent_id=agent_id)
        return self.agent_memories[agent_id]

    def set_core_thesis(self, agent_id: str, core_thesis: str) -> None:
        """设置 agent 的核心主张（从 Soul 文件初始化时调用）。"""
        mem = self.get_or_create_memory(agent_id)
        mem.core_thesis = core_thesis

    def update_from_speech(
        self,
        agent_id: str,
        next_direction: str = "",
    ) -> None:
        """发言后更新论证栈（next_direction）。"""
        mem = self.get_or_create_memory(agent_id)
        if next_direction:
            mem.next_direction = next_direction

    def update_from_moderator(
        self,
        agent_id: str,
        speaker_focus: str = "",
    ) -> None:
        """主持人决策后更新论证栈（speaker_focus → current_focus + established）。"""
        mem = self.get_or_create_memory(agent_id)
        if speaker_focus:
            mem.update_from_round(speaker_focus=speaker_focus)

    def extract_challenges_from_summary(self, summary_text: str, all_agent_ids: list[str]) -> None:
        """从结构化摘要中提取未回应的挑战，分发给被反驳的 agent。

        摘要格式预期：
        - [发言者] → [目标] [Dissent]: 核心论点
        - [发言者] [Extend]: 核心论点
        """
        # 匹配格式：- xxx → yyy [Dissent]: zzz
        pattern = r'-\s*\S+\s*→\s*(\S+)\s*\[Dissent\]\s*:\s*(.+)'
        for match in re.finditer(pattern, summary_text):
            target_name = match.group(1).strip()
            challenge_desc = match.group(2).strip()
            # 尝试匹配到 agent_id
            for aid in all_agent_ids:
                if aid in target_name or target_name in aid:
                    mem = self.get_or_create_memory(aid)
                    mem.update_from_round(challenges=[challenge_desc])
                    break

    # 保留旧接口的兼容方法
    def update_agent_memory(
        self,
        agent_id: str,
        speech_text: str,
        thought_text: str,
        speech_type: str,
        mentions: list[str],
        understood_claims: list[str] | None = None,
    ) -> None:
        """更新 agent 的会话记忆——提取对他人论点的理解。"""
        if understood_claims:
            mem = self.get_or_create_memory(agent_id)
            mem.update_from_round(claims=understood_claims)
