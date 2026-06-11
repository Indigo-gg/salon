from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Generator

from pydantic import BaseModel, Field

from src.agents.soul import Soul
from src.config import SalonConfig
from src.llm.prompts import (
    build_hand_signal_prompt,
    build_speak_prompt,
    build_stream_speak_prompt,
    build_intermediate_step_prompt,
)

if TYPE_CHECKING:
    from src.llm.client import LLMClient
    from src.memory.stream import Message
    from src.tools import ToolRegistry

logger = logging.getLogger(__name__)


class SpeechOutput(BaseModel):
    review: str | None = Field(default=None, description="信息咀嚼：客观梳理对话流，盘点他人观点。")
    thought: str | None = Field(default=None, description="逻辑推演：作为角色的内在思考过程（CoT）。你的世界观如何处理这些信息？你打算如何表达才能让听众直接听懂？")
    speech: str = Field(description="正式开口：你最终公开发表的发言内容。直接回应对方的论证，不要使用礼貌性垫词。")
    speech_type: str = Field(
        description="你的发言类型，必须与你的意图一致",
        json_schema_extra={"enum": ["Extend", "Dissent", "New_Angle", "Clarify", "Ask", "Pass"]},
    )
    mentions: list[str] = Field(
        default_factory=list,
        description="你在这段发言中回应了谁的观点。必须填写具体的角色名（如 '惠子', '卡尔'），可以多个。"
        "如果你在回应某人的具体论点，必须填写此项，否则留空。"
    )
    next_direction: str = Field(
        default="",
        description="你下一步最想推进的方向，一句话。如果不确定可以留空。"
    )
    understood_claims: list[str] = Field(
        default_factory=list,
        description="你对上一轮发言者核心论点的理解。用一句不包含隐喻的直白话概括，格式：'发言者名: 论点概括'。"
        "如果对方的发言你无法用直白语言复述（只能用比喻），说明你没有理解，留空并在 thought 中说明。"
    )



class ToolCallRequest(BaseModel):
    """Agent 请求的工具调用。"""
    tool: str = Field(description="要调用的工具名称，如 'search'")
    input: dict = Field(default_factory=dict, description="工具输入参数")


class IntermediateStep(BaseModel):
    """Agent 工作循环中的中间步骤——思考 + 可选的工具调用请求。"""
    thought: str = Field(description="你的思考过程：目前掌握了什么信息，还需要什么，打算如何发言")
    tool_call: ToolCallRequest | None = Field(
        default=None,
        description="如果你需要调用工具来获取更多信息，填写此项。"
        "如果已有足够信息可以直接发言，留空(null)。"
    )


class HandSignal(BaseModel):
    """轻量级举手信号——只表达方向，不预设论点。"""
    want_to_speak: bool = Field(default=True, description="Whether I want to speak this round")
    energy: str = Field(
        default="medium",
        description="How strongly I want to speak",
        json_schema_extra={"enum": ["high", "medium", "low"]},
    )
    target: str | None = Field(
        default=None,
        description="Role name I want to respond to (null if new angle or no specific target)"
    )
    direction: str = Field(
        default="extend",
        description="One word: what I intend to do",
        json_schema_extra={"enum": ["challenge", "extend", "new_angle", "clarify", "summarize", "pass"]},
    )
    search_queries: list[str] = Field(
        default_factory=list,
        description="如果你的发言需要引用具体的研究数据、统计数字、历史事件或当代案例，"
        "在这里填写搜索关键词。例如：['fMRI default mode network meditation study', '细胞更新周期 研究']。"
        "不要用模糊记忆代替真实引用——如果不确定具体来源，就搜索。不需要搜索时留空。"
    )

    @property
    def intent_type(self) -> str:
        """向后兼容旧代码：将 direction 映射回 intent_type 枚举值。"""
        _map = {
            "challenge": "Dissent",
            "extend": "Extend",
            "new_angle": "New_Angle",
            "clarify": "Clarify",
            "summarize": "Ask",
            "pass": "Pass",
        }
        return _map.get(self.direction, self.direction)

    @property
    def summary(self) -> str:
        """向后兼容旧代码：用 direction + target 代替 summary。"""
        target_str = f" → {self.target}" if self.target else ""
        return f"[{self.direction}]{target_str}"


# 保留旧名称的别名，便于渐进迁移
SpeakIntent = HandSignal


class DiscussionContext:
    def __init__(
        self,
        topic: str,
        recent_messages: list[Message],
        recent_messages_text: str,
        summarized_history: str,
        whiteboard_text: str,
        whiteboard_brief: str,
        archive_text: str,
        round_number: int,
        agent_memory_text: str = "",
    ):
        self.topic = topic
        self.recent_messages = recent_messages
        self.recent_messages_text = recent_messages_text
        self.summarized_history = summarized_history
        self.whiteboard_text = whiteboard_text
        self.whiteboard_brief = whiteboard_brief
        self.archive_text = archive_text
        self.round_number = round_number
        self.agent_memory_text = agent_memory_text


class BaseAgent:
    def __init__(self, agent_id: str, soul_path: str, config: SalonConfig):
        self.agent_id = agent_id
        if soul_path:
            self.soul = Soul.load(soul_path)
        else:
            self.soul = Soul(name=agent_id, role="participant", basic_profile="", personality_traits="", self_perception="", behavioral_principles="", raw_text="")
        self.name = self.soul.name
        self.role = "participant"
        self.config = config
        self._last_thinking: str = ""  # 最近一次发言的原生思维链（Mode A）

    def get_system_prompt(self) -> str:
        return self.soul.get_full_prompt()

    def generate_intent(self, context: DiscussionContext, llm: LLMClient, round_info: str = "") -> HandSignal:
        # 精简模式：intent context 中 summarized_history 存放上轮摘要
        # recent_messages 为空时，用 last_round_summary 替代
        last_summary = context.summarized_history if not context.recent_messages else ""
        messages = build_hand_signal_prompt(
            agent_name=self.name,
            topic=context.topic,
            whiteboard_brief=context.whiteboard_brief,
            recent_messages=context.recent_messages[-3:],
            round_info=round_info,
            language=self.config.discussion.language,
            last_round_summary=last_summary,
        )
        try:
            return llm.chat_structured(messages, HandSignal)
        except Exception as e:
            logger.warning(f"Failed to generate hand signal for {self.name}: {e}")
            return HandSignal(
                want_to_speak=False,
                energy="low",
                direction="pass",
                target=None,
            )

    def speak(self, context: DiscussionContext, llm: LLMClient, round_info: str = "", tools: ToolRegistry | None = None, emit_event: callable | None = None) -> SpeechOutput:
        """发言。如果传入了 tools，支持工作循环中的工具调用。

        Args:
            emit_event: 可选的事件回调，用于在工具调用过程中推送 SSE 事件到前端。
        """

        action = (
            f"现在是第 {context.round_number} 轮，轮到你发言了。"
            f"当前讨论主题：{context.topic}。"
            f"请围绕这个主题发言，回应其他参与者的观点。"
        )

        messages = build_speak_prompt(
            agent_name=self.name,
            soul_text=self.soul.get_full_prompt(),
            topic=context.topic,
            whiteboard=context.whiteboard_brief,
            archive=context.archive_text,
            summarized_history=context.summarized_history,
            recent_messages=context.recent_messages,
            action_instruction=action,
            round_info=round_info,
            language=self.config.discussion.language,
            agent_memory=context.agent_memory_text,
            use_native_thinking=self.config.llm.use_native_thinking,
            tool_descriptions=tools.get_tool_descriptions() if tools and tools.has_tools() else "",
        )

        # 无工具：单步调用，行为不变
        if not tools or not tools.has_tools():
            try:
                result = llm.chat_structured(messages, SpeechOutput)
                self._last_thinking = llm.last_structured_thinking
                return result
            except Exception as e:
                logger.error(f"Failed to generate speech for {self.name}: {e}")
                fallback_speech = self._extract_speech_from_error(str(e))
                return SpeechOutput(
                    review=None, thought=None,
                    speech=fallback_speech, speech_type="Extend", mentions=[],
                )

        # 有工具：工作循环
        return self._speak_with_tools(messages, llm, tools, emit_event)

    def _speak_with_tools(self, messages: list[dict], llm: LLMClient, tools: ToolRegistry, emit_event: callable | None = None) -> SpeechOutput:
        """带工具调用的发言工作循环。

        工具调用历史存储在 self._last_tool_history 中，供调用方读取。
        """
        max_steps = 3
        tool_history: list[dict] = []
        self._last_tool_history = []  # 重置

        for step in range(max_steps):
            try:
                result = llm.chat_structured(messages, IntermediateStep)
            except Exception as e:
                logger.warning(f"IntermediateStep parse failed (step {step}): {e}")
                break

            # Agent 不需要工具，跳出循环准备生成最终发言
            if not result.tool_call:
                logger.info(f"{self.name} tool loop: no tool requested at step {step}, proceeding to speech")
                break

            # 执行工具调用
            tool_name = result.tool_call.tool
            tool_input = result.tool_call.input

            # 推送 SSE 事件：工具调用开始
            if emit_event:
                emit_event("tool_call", {
                    "agent_id": self.agent_id,
                    "agent_name": self.name,
                    "tool": tool_name,
                    "input": tool_input,
                    "status": "calling",
                })

            tool_output = tools.execute(tool_name, tool_input)
            tool_history.append({"tool": tool_name, "input": tool_input, "output": tool_output})
            logger.info(f"{self.name} tool call: {tool_name}({str(tool_input)[:80]}) -> {len(tool_output)} chars")

            # 推送 SSE 事件：工具调用完成
            if emit_event:
                emit_event("tool_call", {
                    "agent_id": self.agent_id,
                    "agent_name": self.name,
                    "tool": tool_name,
                    "input": tool_input,
                    "output_preview": tool_output[:200],
                    "status": "done",
                })

            # 注入工具结果，继续循环
            messages = build_intermediate_step_prompt(
                messages=messages,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=tool_output,
                step=step + 1,
                max_steps=max_steps,
            )

        # 存储工具历史，供调用方读取
        self._last_tool_history = tool_history

        # 生成最终发言
        if tool_history:
            summary = "；".join(f"{h['tool']}({str(h['input'].get('queries', h['input']))[:30]})" for h in tool_history)
            final_note = f"\n\n【工具调用记录】你在本轮调用了以下工具：{summary}。请将获取的信息融入你的发言中。"
            messages = messages.copy()
            if messages and messages[-1]["role"] == "user":
                messages[-1] = {**messages[-1], "content": messages[-1]["content"] + final_note}
            else:
                messages.append({"role": "user", "content": final_note})

        try:
            result = llm.chat_structured(messages, SpeechOutput)
            self._last_thinking = llm.last_structured_thinking
            return result
        except Exception as e:
            logger.error(f"Failed to generate speech after tool loop for {self.name}: {e}")
            fallback_speech = self._extract_speech_from_error(str(e))
            return SpeechOutput(
                review=None, thought=None,
                speech=fallback_speech, speech_type="Extend", mentions=[],
            )

    def stream_speak(
        self,
        context: DiscussionContext,
        llm: LLMClient,
        round_info: str = "",
    ) -> Generator[str, None, None]:
        """流式发言：逐块 yield 纯文本发言内容。

        与 speak() 使用相同的上下文信息，但不要求 JSON 输出。
        适用于 SSE 流式传输场景，笔记本更新由调用方另行处理。
        """

        action = (
            f"现在是第 {context.round_number} 轮，轮到你发言了。"
            f"当前讨论主题：{context.topic}。"
            f"请围绕这个主题发言，回应其他参与者的观点。"
            f"自然、直接地表达，不要跑题。"
        )

        messages = build_stream_speak_prompt(
            agent_name=self.name,
            soul_text=self.soul.get_full_prompt(),
            topic=context.topic,
            whiteboard=context.whiteboard_brief,
            archive=context.archive_text,
            summarized_history=context.summarized_history,
            recent_messages=context.recent_messages,
            action_instruction=action,
            round_info=round_info,
            language=self.config.discussion.language,
            agent_memory=context.agent_memory_text,
            use_native_thinking=self.config.llm.use_native_thinking,
        )
        # 记录 prompt 长度（便于排查空响应问题）
        total_chars = sum(len(m.get("content", "")) for m in messages)
        logger.info(f"LLM call ({self.name}, round {context.round_number}): {len(messages)} messages, ~{total_chars} chars")
        try:
            yield from llm.chat_stream(messages)
        except Exception as e:
            logger.error(f"流式发言失败 ({self.name}): {e}")
            yield f"[{self.name}的发言生成遇到问题，请稍后重试]"

    def _extract_speech_from_error(self, error_text: str) -> str:
        """Try to extract speech content from a failed structured output."""
        # If error contains the raw response, try to extract speech from it
        if "Could not extract JSON" in error_text:
            # Get the raw response part after the colon
            parts = error_text.split("LLM response:", 1)
            if len(parts) > 1:
                raw = parts[1].strip().rstrip(".")
                # Try to find a "speech" field in the raw text
                import re
                speech_match = re.search(r'"speech"\s*:\s*"([^"]*)"', raw)
                if speech_match:
                    return speech_match.group(1)
                # If no speech field, use the raw text if it looks like content
                if len(raw) > 20 and not raw.startswith("{"):
                    return raw[:500]
        return f"[{self.name}的发言生成遇到问题，请稍后重试]"
