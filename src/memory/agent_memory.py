"""每个 Agent 的论证栈（Argument Stack）——动态叙事结构。

与旧版 AgentMemory 的区别：
- 旧版：回溯性碎片记录（"我说过什么"）
- 新版：前瞻性叙事结构（"我的论证走到哪了，下一步去哪"）

字段来源：
- core_thesis: Soul 文件静态定义
- current_focus: 主持人 speaker_focus 每轮更新
- established: speaker_focus 历史累积
- unresolved_challenges: 结构化摘要中提取（目标=我 且 类型=Dissent）
- understood_claims: agent 每轮发言时对他人论点的理解记录（直白语言）
- next_direction: agent 自己每轮发言后输出
- used_arguments: 白板 active_concepts × 历史发言，动态计算（不存储）
"""

from __future__ import annotations

from dataclasses import dataclass, field


# 条目上限
MAX_ESTABLISHED = 5
MAX_CHALLENGES = 5
MAX_CLAIMS = 5

# 条目字数上限
FOCUS_MAX_CHARS = 80
CHALLENGE_MAX_CHARS = 80
CLAIM_MAX_CHARS = 100


def _truncate(text: str, max_chars: int) -> str:
    """截取文本到指定长度。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


@dataclass
class ArgumentStack:
    """每个 agent 的论证栈——动态叙事结构。

    设计原则：
    - core_thesis 来自 Soul，静态不变
    - current_focus 由主持人 speaker_focus 更新
    - established 从 speaker_focus 历史累积
    - unresolved_challenges 从结构化摘要中规则提取
    - understood_claims 由 agent 每轮发言时输出，记录对他人论点的直白理解
    - next_direction 由 agent 自己输出
    - used_arguments 动态计算，不存储
    """
    agent_id: str

    # 核心主张（来自 Soul 文件，整场讨论不变）
    core_thesis: str = ""

    # 当前论证焦点（每轮由主持人 speaker_focus 更新）
    current_focus: str = ""

    # 已建立的支点（从 speaker_focus 历史累积）
    established: list[str] = field(default_factory=list)

    # 未回应的挑战（别人对我的反驳，从结构化摘要中提取）
    unresolved_challenges: list[str] = field(default_factory=list)

    # 对他人论点的理解记录（每轮发言后更新，用直白语言概括）
    understood_claims: list[str] = field(default_factory=list)

    # 下一步方向（agent 自己每轮发言后输出的一句话）
    next_direction: str = ""

    def update_from_round(
        self,
        speaker_focus: str = "",
        challenges: list[str] | None = None,
        next_dir: str = "",
        claims: list[str] | None = None,
    ) -> None:
        """每轮结束后更新论证栈。"""
        if speaker_focus:
            self.current_focus = _truncate(speaker_focus, FOCUS_MAX_CHARS)
            # 避免重复添加相同的支点
            if self.current_focus not in self.established:
                self.established.append(self.current_focus)
                if len(self.established) > MAX_ESTABLISHED:
                    self.established = self.established[-MAX_ESTABLISHED:]
        if challenges:
            for c in challenges:
                truncated = _truncate(c, CHALLENGE_MAX_CHARS)
                if truncated and truncated not in self.unresolved_challenges:
                    self.unresolved_challenges.append(truncated)
            if len(self.unresolved_challenges) > MAX_CHALLENGES:
                self.unresolved_challenges = self.unresolved_challenges[-MAX_CHALLENGES:]
        if claims:
            for c in claims:
                truncated = _truncate(c, CLAIM_MAX_CHARS)
                if truncated and truncated not in self.understood_claims:
                    self.understood_claims.append(truncated)
            if len(self.understood_claims) > MAX_CLAIMS:
                self.understood_claims = self.understood_claims[-MAX_CLAIMS:]
        if next_dir:
            self.next_direction = next_dir

    def resolve_challenge(self, challenge_text: str) -> None:
        """标记某个挑战已被回应，从未解决列表中移除。"""
        self.unresolved_challenges = [
            c for c in self.unresolved_challenges
            if challenge_text not in c and c not in challenge_text
        ]

    def to_prompt_text(self, used_arguments: list[str] | None = None) -> str:
        """生成注入 prompt 的论证栈文本。如果全部为空则返回空字符串。"""
        parts = []

        if self.core_thesis:
            parts.append(f"核心主张：{self.core_thesis}")

        if self.current_focus:
            parts.append(f"当前焦点：{self.current_focus}")

        if self.established:
            items = "\n".join(f"- {s}" for s in self.established)
            parts.append(f"已建立的支点：\n{items}")

        if self.unresolved_challenges:
            items = "\n".join(f"- {c}" for c in self.unresolved_challenges)
            parts.append(f"未回应的挑战：\n{items}")

        if self.understood_claims:
            items = "\n".join(f"- {c}" for c in self.understood_claims)
            parts.append(f"你对他人论点的理解：\n{items}")

        if used_arguments:
            items = "、".join(used_arguments)
            parts.append(f"你已用过的论据：{items}")

        if self.next_direction:
            parts.append(f"你上次说想推进的方向：{self.next_direction}")

        if not parts:
            return ""

        text = "\n\n".join(parts)
        text += "\n\n⚠️ 请不要重复已使用的论据。如果有未回应的挑战，优先处理。"
        return text


# 保留旧名称的别名，便于渐进迁移
AgentMemory = ArgumentStack
