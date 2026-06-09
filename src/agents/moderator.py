from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent, DiscussionContext, SpeechOutput
from src.config import SalonConfig
from src.llm.prompts import build_moderator_prompt

if TYPE_CHECKING:
    from src.llm.client import LLMClient

logger = logging.getLogger(__name__)


class AgendaDecision(BaseModel):
    speaker_focus: dict[str, str] = Field(
        default_factory=dict,
        description="【先填这一步】本轮每位发言者的核心论点摘要。格式：{'角色名': '一句话概括其本轮核心论证', ...}。"
        "在做任何调度判断之前，先完成这一步。"
    )
    speakers: list[str] = Field(description="排序后的获准发言者 Agent ID 列表，最前面的人优先发言")
    notice: str = Field(default="", description="如果需要干预（如转移话题、警告、宣布进入尾声等），请填写通知内容。如果没有则为空。")
    reject_intents: list[str] = Field(default_factory=list, description="如果某人的意图完全跑题或严重破坏讨论规则，将其 Agent ID 填入此数组直接驳回")
    phase: str = Field(
        default="EXPLORATION",
        description="你判断当前讨论处于哪个阶段",
        json_schema_extra={"enum": [
            "OPENING",       # 开场陈述，各方亮明立场
            "EXPLORATION",   # 积极探索新角度和新视角
            "DEEPENING",     # 深入特定分歧或子话题
            "CONVERGENCE",   # 论点重复出现，共识形成，新观点减少
            "CLOSING",       # 最终总结陈词
        ]},
    )
    agenda_note: str = Field(
        default="",
        description="你对下一步讨论方向的判断。写一句简短的议程指引，例如："
        "'需要让惠子和卡尔正面交锋关于自由意志的定义分歧' 或 "
        "'该话题已充分探索，下轮引导收敛' 或 "
        "'达文的科学视角还没被充分挑战，优先安排反驳者'。"
        "这条记录会写入议程轨迹，下一轮你会看到它，用来保持讨论的连贯性。"
    )
    emotional_temperature: float = Field(
        default=0.5,
        description="你感知到的当前讨论的情绪温度。0=冷静理性、学术探讨；0.5=有情感投入但克制；1=高度情绪化、可能带有个人攻击。"
    )
    perceived_tension: str = Field(
        default="moderate",
        description="你感知到的对话张力。low=气氛平和、缺乏碰撞；moderate=正常的观点交流；high=激烈但有建设性的辩论；conflict=可能失控的对抗。",
        json_schema_extra={"enum": ["low", "moderate", "high", "conflict"]},
    )
    perception_summary: str = Field(
        default="",
        description="你对当前讨论状态的感知摘要。简要说明你在可进入性、接地性、呼吸感、诚实的未解决四个维度上的判断。"
        "例如：'概念负荷偏高，距上次具体场景已3轮，上一轮密集' 或 '各维度均衡，可继续推进'。"
    )
    pending_question: str = Field(
        default="",
        description="如果你本轮提出了一个需要被明确回答的核心问题（而不是一般性的建议或指令），填写在这里。"
        "这个问题会被锚定到白板的 current_focus 中，直到有人直接回答后才会移除。"
        "只填写真正需要回答的是非题或选择题，不要填写一般性建议如'请用具体例子'。"
        "如果没有提出具体问题，留空。"
    )


class ModeratorAgent(BaseAgent):
    def __init__(self, agent_id: str, soul_path: str, config: SalonConfig):
        super().__init__(agent_id, soul_path, config)
        self.role = "moderator"
        self._current_phase = "OPENING"
        self._last_agenda_note = ""

    @property
    def phase(self) -> str:
        return self._current_phase

    @property
    def last_agenda_note(self) -> str:
        return self._last_agenda_note

    def decide_agenda_and_speakers(
        self,
        context: DiscussionContext,
        intents: dict[str, str],
        llm: LLMClient,
        max_speakers: int = 3,
        signal_injection: str = "",
        perception_data: str = "",
    ) -> AgendaDecision:
        """根据当前讨论局势和所有参与者的意图，决定接下来的议程和发言顺位。"""

        # 格式化选手意图供大模型审阅
        intents_text = "\n".join([f"- [{aid}] 申请发言: {intent_summary}" for aid, intent_summary in intents.items() if intent_summary])
        if not intents_text:
            intents_text = "（本轮无人举手）"

        num_participants = len(intents)

        # 上一轮的议程指引（如果有），帮助主持人保持连贯性
        prev_agenda_section = ""
        if self._last_agenda_note:
            prev_agenda_section = f"\n【你上一轮的议程指引】{self._last_agenda_note}\n请检查这个指引是否已经完成，或者需要调整。\n"

        action = (
            "你是沙龙的首席主持人和调度大脑。\n"
            "审阅当前白板（Whiteboard）、议程轨迹（Agenda Trace）、最新讨论记录，以及本轮所有选手的【举手意图】。\n\n"
            "## 第一步：感知当前状态\n"
            "阅读感知数据摘要（如果提供），从可进入性、接地性、呼吸感、诚实的未解决四个维度评估当前讨论状态。\n"
            "将你的感知判断填入 perception_summary 字段。\n\n"
            "## 第二步：理解本轮发言（先填 speaker_focus）\n"
            "在做任何调度判断之前，先明确本轮每位发言者的核心论点，填入 speaker_focus。\n"
            "格式：{'角色名': '一句话概括其本轮核心论证', ...}\n\n"
            "## 第三步：基于上述理解做出调度判断\n"
            "1. **筛选与排序发言人 (`speakers`)**：评估各选手的意图，选出最有价值的发言者。"
            f"本轮最多选 {max_speakers} 人（参与者 {num_participants} 人的一半+1）。"
            "优先让能推进共识、提供新论据或提出尖锐反驳的人发言。如果你觉得某人很久没说话且意图不错，可以优先。\n"
            "2. **剔除捣乱者 (`reject_intents`)**：如果有人的意图完全跑题，或者只是复述废话，把他们的 Agent ID 放进 reject_intents。\n"
            "3. **系统干预 (`notice`)**：根据你感知到的原则违反情况，选择最合适的干预方式。干预方式由你推理决定，不是预设的。如果你判断不需要干预，留空。\n"
            "4. **阶段判断 (`phase`)**：判断当前讨论处于哪个阶段。\n"
            "5. **议程指引 (`agenda_note`)**：写下你对下一步讨论方向的判断。这会写入议程轨迹，下一轮你会看到它。\n"
            "6. **核心问题锚定 (`pending_question`)**：如果你本轮在 notice 中提出了一个需要被明确回答的核心问题（可以被回答的是非题或选择题），填写在 pending_question 中。这个问题会被锚定到白板上，直到有人直接回答。注意：一般性建议（如'请用具体例子'）不算核心问题，不要填写。只有真正需要被回答的具体问题才填写。\n\n"
            "## 节奏控制指南\n"
            "- **OPENING**：确保各方都有机会亮明立场。如果有人还没表达初始观点，优先安排。\n"
            "- **EXPLORATION**：鼓励不同角度的碰撞。如果某个方向已经充分探索，用 notice 引导向新方向。\n"
            "- **DEEPENING**：当出现核心分歧时，让对立双方深入交锋。用 notice 点明分歧焦点。\n"
            "- **CONVERGENCE**：当论点开始重复、新观点减少时，引导综合收束——梳理各方核心论据，标出已达成的共识和不可调和的分歧。如果已经历话题转移仍在重复，说明论点已穷尽，应准备收尾而非继续转移。\n"
            "- **CLOSING**：讨论接近尾声，安排总结性发言。用 notice 宣布进入最后几轮。\n\n"
            "## 防止讨论失控的规则\n"
            "- 重复判断：你需要根据讨论的实际内容独立判断是否在重复。「在同一话题下用新论据、新案例、新角度推进」是正常的深化，不算重复。「用相同的论据和角度反复表达同一立场」才算重复。不要仅因为信号系统提示就认定讨论在重复。\n"
            "- 如果讨论严重偏题，在 notice 中温和但明确地拉回主线。\n"
            "- 如果有人连续发言 2 次以上且没有新内容，降低其优先级。\n"
            f"{prev_agenda_section}"
            f"【当前选手的举手意图】\n{intents_text}"
        )

        # 外部注入的信号文本（由 orchestrator 通过 InjectionRouter 生成）
        if signal_injection:
            action += f"\n\n{signal_injection}"

        messages = build_moderator_prompt(
            agent_name=self.name,
            soul_text=self.soul.get_full_prompt(),
            topic=context.topic,
            whiteboard=context.whiteboard_text,
            archive=context.archive_text,
            summarized_history=context.summarized_history,
            recent_messages=context.recent_messages,
            action_instruction=action,
            language=self.config.discussion.language,
            perception_data=perception_data,
        )

        try:
            decision = llm.chat_structured(messages, AgendaDecision)
            # 更新内部状态
            self._current_phase = decision.phase
            self._last_agenda_note = decision.agenda_note
            # 裁剪 speakers 到 max_speakers
            if len(decision.speakers) > max_speakers:
                decision.speakers = decision.speakers[:max_speakers]
            return decision
        except Exception as e:
            logger.warning(f"Moderator decision failed: {e}, falling back to random selection")
            valid_aids = [aid for aid in intents.keys() if intents[aid]]
            random.shuffle(valid_aids)
            selected = valid_aids[:max_speakers]
            logger.info(f"Fallback: randomly selected {selected} from {valid_aids}")
            return AgendaDecision(
                notice="",
                reject_intents=[],
                speakers=selected,
                phase=self._current_phase,
                agenda_note=self._last_agenda_note,  # 保持上一轮的指引
            )
