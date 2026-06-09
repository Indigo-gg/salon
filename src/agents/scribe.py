from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent, DiscussionContext, SpeechOutput
from src.config import SalonConfig
from src.llm.prompts import build_speak_prompt

if TYPE_CHECKING:
    from src.llm.client import LLMClient

logger = logging.getLogger(__name__)


class WhiteboardOperation(BaseModel):
    action: str = Field(
        description="操作类型",
        json_schema_extra={"enum": ["rewrite", "add", "clear_section", "delete"]}
    )
    section: str = Field(
        description="要操作的板块（注意：agenda_trace 由主持人自动维护，不可操作）",
        json_schema_extra={"enum": ["current_focus", "discussion_phase", "current_topic", "consensus", "disagreements", "backlog", "surprises", "active_concepts", "search_materials"]}
    )
    content: str = Field(default="", description="操作内容。如果是rewrite，请提供凝练的总结覆盖旧内容；如果是delete，提供要删除的完整旧内容以便匹配。clear_section不需要此字段。")


class WhiteboardSync(BaseModel):
    operations: list[WhiteboardOperation] = Field(
        default_factory=list,
        description="需要对白板进行的操作，如果不需要更新则为空列表"
    )


class ScribeAgent(BaseAgent):
    def __init__(self, agent_id: str, soul_path: str, config: SalonConfig):
        super().__init__(agent_id, soul_path, config)
        self.role = "scribe"
    def generate_digest(
        self,
        topic: str,
        transcript_text: str,
        whiteboard_text: str,
        whiteboard_sections: dict,
        llm: LLMClient,
    ) -> str:
        """生成白板变更日志式的讨论纪要。"""
        # 构建每个板块的变更历史
        change_log_parts = []
        section_labels = {
            "current_focus": "当前焦点",
            "discussion_phase": "讨论阶段",
            "current_topic": "全局主题",
            "consensus": "共识",
            "disagreements": "分歧",
            "backlog": "议题积压区",
            "surprises": "意外发现",
            "agenda_trace": "议程轨迹",
        }

        for section_key, entries in whiteboard_sections.items():
            if not entries:
                continue
            label = section_labels.get(section_key, section_key)
            change_log_parts.append(f"### {label}")
            for entry in entries:
                change_log_parts.append(f"- [第{entry.round}轮, {entry.added_by}] {entry.content}")
            change_log_parts.append("")

        change_log = "\n".join(change_log_parts)

        system = "你是一位讨论纪要撰写者。请根据白板的变更记录，生成简洁的讨论纪要。"
        user = f"""讨论主题：{topic}

以下是白板各板块的完整变更记录（按时间顺序）：

{change_log}

请根据以上变更记录，生成一份简洁的讨论纪要，包含：
1. 讨论主线：议题如何从起点演进到终点（2-3句话）
2. 关键转折点：哪些轮次出现了重要的方向变化
3. 最终状态：讨论结束时的共识、分歧、搁置问题

不要重复白板的原始内容，而是提炼出叙事线索。控制在 300 字以内。"""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            return llm.chat(messages)
        except Exception as e:
            logger.warning(f"Digest generation failed: {e}")
            return f"Digest generation failed: {e}"

    def generate_overview(
        self,
        topic: str,
        transcript_text: str,
        whiteboard_sections: dict,
        round_count: int,
        participant_names: list[str],
        llm: LLMClient,
    ) -> str:
        """基于白板各板块的最终状态，生成一份结构化的讨论总览。"""
        # 提取白板关键板块的最终内容
        wb_parts = []
        section_labels = {
            "consensus": "已达成的共识",
            "disagreements": "未解决的分歧",
            "backlog": "搁置的议题",
            "surprises": "意外发现",
            "current_focus": "最终焦点",
        }
        for key, label in section_labels.items():
            entries = whiteboard_sections.get(key, [])
            active = [e for e in entries if not e.cold]
            if active:
                items = "\n".join(f"  - {e.content}" for e in active)
                wb_parts.append(f"**{label}**：\n{items}")

        whiteboard_summary = "\n\n".join(wb_parts) if wb_parts else "（白板无记录）"

        system = "你是一位讨论纪要撰写者。请根据白板最终状态和讨论记录，生成一份简洁的讨论总览。"
        user = f"""讨论主题：{topic}
参与人数：{len(participant_names)} 人（{', '.join(participant_names)}）
总轮次：{round_count} 轮

以下是白板各板块的最终状态：

{whiteboard_summary}

请生成一份结构化的讨论总览，严格按以下格式输出：

## 讨论总览

**主题**：{topic}

**核心成果**
- （2-5 条关键共识或结论，每条一行）

**遗留问题**
- （如果有未解决的分歧或搁置的议题，列出 1-3 条；如果没有则写"无"）

**亮点**
- （讨论中出现的 1-2 个精彩洞见或转折点；如果没有则写"无"）

要求：
1. 严格使用上述 Markdown 格式
2. 内容高度凝练，总计不超过 300 字
3. 只提取白板中已有的信息，不要凭空创造"""

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            return llm.chat(messages)
        except Exception as e:
            logger.warning(f"Overview generation failed: {e}")
            return f"## 讨论总览\n\n总览生成失败：{e}"

    def sync_whiteboard(self, context: DiscussionContext, llm: LLMClient, whiteboard_chars: int = 0, compression_threshold: int = 0) -> WhiteboardSync | None:
        action = (
            "你是沙龙的记录员（后台白板管理员）。你的绝对原则是：只更新白板，绝对不插话发言。\n"
            "回顾最近的讨论和当前白板状态。主动综合讨论的当前状态：\n"
            "1. current_focus（当前焦点）：大家这一秒正在围绕什么具体问题交锋？强制要求为【@某人，你的某观点如何解释XX？】这样的疑问句形式。\n"
            "   【待回答问题处理】如果 current_focus 中有标记为【待回答】的主持人问题，检查最近的发言是否有人直接回答了它。如果已有人回答，使用 rewrite 将其更新为新的焦点或删除【待回答】标记。如果仍无人直接回答，保留该标记，不要用其他焦点覆盖它。\n"
            "2. discussion_phase（讨论阶段）：讨论进行到了哪一步（如开场陈述、自由探索、深度交锋、收敛共识等）？\n"
            "3. 核心论点与分歧：是否有新共识形成？分歧点是否发生了转移？在添加任何新分歧之前，必须检查是否与已有焦点重合；如果重合，必须使用 `rewrite` 将其合并为一条最精准的描述，绝对禁止单纯追加（add）。\n"
            "【Diff & Merge 强制要求】：如果你发现白板中有任何过时的、已被解决的、或者冗长重复的内容，必须使用 `delete` 或 `rewrite` 操作将其清理。保持白板内容紧凑（子弹笔记风格）且具有高度的相关导向性。\n"
            "【注意】agenda_trace（议程轨迹）板块由主持人自动维护，请勿操作此板块。"
        )

        # 字数阈值压缩触发：注入压缩警告
        if compression_threshold > 0 and whiteboard_chars > compression_threshold:
            action += (
                f"\n⚠️ 【白板超载警告】当前白板活跃内容已达 {whiteboard_chars} 字，超过阈值 {compression_threshold} 字。"
                "请优先执行【压缩任务】：将冗长的学术描述压缩为精简的子弹笔记（Bullet Points），"
                "使用 `rewrite` 操作替换冗长条目，或使用 `delete` 删除已过时的内容。"
                "目标：将总字数压到阈值以下。"
            )

        # 概念账本维护指令
        action += (
            "\n\n【概念账本维护】\n"
            "检查最近3轮的发言，更新白板的 active_concepts 板块：\n"
            "- 如果有新的核心论点、主张或关键概念被明确提出，使用 add 添加。每条格式：`论点/概念名 | 引入者名 | 第N轮 | active`\n"
            "- 【表述原则】记录的是论点本身，不是修辞包装。如果一个观点只能用隐喻来表达而无法用直白语言概括，说明它还未被真正理解——不要将其记入概念清单。\n"
            "- 【定义追踪】当一个核心概念被多位发言者使用时，检查他们是否在说同一件事。如果定义不同，在概念条目中注明差异，格式：`概念名 | 定义A（发言者X, 第N轮）vs 定义B（发言者Y, 第M轮）| active`。如果定义存在实质性分歧（不同定义指向不同的主张或结论），必须同时在 disagreements 板块中添加一条记录，说明概念X在不同发言者那里含义不同。\n"
            "- 如果有概念已过时或被明确替代，使用 delete 移除\n"
            "- 如果某概念超过3轮未被任何人引用，在其状态中标记为 dormant\n"
            "- 保持清单精简，只保留当前讨论中仍然活跃或有参考价值的概念（最多10条）\n"
            "- 如果不需要更新，返回空操作列表即可"
        )

        # 证据提取指令
        action += (
            "\n\n【搜索证据提取】\n"
            "检查最近3轮的发言，如果有人引用了搜索结果中的具体数据、研究结论或事实（通常以括号标注出处域名为标志），"
            "将关键证据提取为精炼条目，使用 add 写入 search_materials 板块。每条格式：\n"
            "`[来源域名] 核心数据或结论（一句话，不超过50字）| 第N轮 引用者名`\n"
            "例如：`[jamanetwork.com] MBSR八周课程后焦虑量表得分下降30% | 第3轮 达文`\n"
            "只提取对后续讨论有引用价值的具体事实，不要提取通用知识或推理。"
            "如果 search_materials 中已有相同来源的条目，不要重复添加。"
            "如果不需要更新，返回空操作列表即可。"
        )

        messages = build_speak_prompt(
            agent_name=self.name,
            soul_text=self.soul.get_full_prompt(),
            topic=context.topic,
            whiteboard=context.whiteboard_text,
            archive=context.archive_text,
            summarized_history=context.summarized_history,
            recent_messages=context.recent_messages,
            action_instruction=action,
            language=self.config.discussion.language,
        )
        try:
            result = llm.chat_structured(messages, WhiteboardSync)
            if result is not None:
                ops = result.operations or []
                logger.info(f"[Scribe] LLM 返回 WhiteboardSync: {len(ops)} 个操作")
                for i, op in enumerate(ops):
                    logger.info(f"  [{i}] {op.action} → {op.section}: {op.content[:100]}...")
            else:
                logger.warning(f"[Scribe] chat_structured 返回 None")
            return result
        except Exception as e:
            logger.warning(f"Whiteboard sync failed: {e}")
            return None
