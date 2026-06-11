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
    """主持人的战术调度决策。

    注意：以下职责已移交给其他组件：
    - 论点提取 → 记录员的 RoundAnalysis
    - 议程方向 → 战略家的 DirectionGuidance
    - 感知摘要 → 信号系统的 ControlSignals
    主持人只负责：选人、发通知、拒绝意图、阶段分类、锚定问题。
    """
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
    emotional_temperature: float = Field(
        default=0.5,
        description="你感知到的当前讨论的情绪温度。0=冷静理性、学术探讨；0.5=有情感投入但克制；1=高度情绪化、可能带有个人攻击。"
    )
    perceived_tension: str = Field(
        default="moderate",
        description="你感知到的对话张力。low=气氛平和、缺乏碰撞；moderate=正常的观点交流；high=激烈但有建设性的辩论；conflict=可能失控的对抗。",
        json_schema_extra={"enum": ["low", "moderate", "high", "conflict"]},
    )
    pending_question: str = Field(
        default="",
        description="如果你本轮提出了一个需要被明确回答的核心问题，填写在这里。"
        "这个问题会被锚定到白板的 current_focus 中，直到有人直接回答后才会移除。"
        "如果没有提出具体问题，留空。"
        "注意：议程方向和维度问题由战略家负责，你只在战术层面提问。"
    )


class ModeratorAgent(BaseAgent):
    def __init__(self, agent_id: str, soul_path: str, config: SalonConfig):
        super().__init__(agent_id, soul_path, config)
        self.role = "moderator"
        self._current_phase = "OPENING"

    @property
    def phase(self) -> str:
        return self._current_phase

    def decide_agenda_and_speakers(
        self,
        context: DiscussionContext,
        intents: dict[str, str],
        llm: LLMClient,
        max_speakers: int = 3,
        signal_injection: str = "",
        perception_data: str = "",
        round_num: int = 1,
        id_to_name: dict[str, str] | None = None,
    ) -> AgendaDecision:
        """根据当前讨论局势和所有参与者的意图，决定接下来的议程和发言顺位。"""

        # 格式化选手意图供大模型审阅，同时显示 ID 和名字
        id_to_name = id_to_name or {}
        intents_lines = []
        for aid, intent_summary in intents.items():
            if intent_summary:
                name = id_to_name.get(aid, "")
                name_hint = f"（{name}）" if name else ""
                intents_lines.append(f"- `{aid}`{name_hint} 申请发言: {intent_summary}")
        intents_text = "\n".join(intents_lines) if intents_lines else "（本轮无人举手）"

        num_participants = len(intents)

        # 轮次状态说明：告诉 LLM 当前是第几轮、是否有实际讨论历史
        has_history = bool(context.recent_messages)
        if round_num == 1 and not has_history:
            round_status = (
                f"【当前状态】这是第 {round_num} 轮。讨论刚刚开始，尚无任何发言记录。"
                "你看到的【举手意图】只是参与者表达想发言的方向意向，不是已发生的发言。"
                "你不需要做节奏干预或判断讨论状态，只需要分配发言顺序。\n\n"
            )
        else:
            round_status = f"【当前状态】这是第 {round_num} 轮。已有 {len(context.recent_messages)} 条近期发言记录。\n\n"

        action = (
            "你是沙龙的主持人/调度员。你的职责是：选人发言、发通知、拒绝跑题意图。\n"
            "注意：议程方向和内容质量由战略家负责，你只做战术调度。\n"
            f"{round_status}"
            "审阅当前白板（Whiteboard）、最新讨论记录，以及本轮所有选手的【举手意图】。\n\n"
            "## 做出调度判断\n"
            "1. **筛选与排序发言人 (`speakers`)**：评估各选手的意图，选出最有价值的发言者。"
            f"本轮最多选 {max_speakers} 人（参与者 {num_participants} 人的一半+1）。"
            "优先让能推进共识、提供新论据或提出尖锐反驳的人发言。如果你觉得某人很久没说话且意图不错，可以优先。\n"
            "**重要：`speakers` 字段必须填 agent ID（如 `participant_1`），不要填角色名字（如 苏老迪）。**\n"
            "2. **剔除捣乱者 (`reject_intents`)**：如果有人的意图完全跑题，或者只是复述废话，把他们的 Agent ID 放进 reject_intents。\n"
            "3. **系统干预 (`notice`)**：只在以下情况发通知：讨论严重偏题、有人身攻击、需要宣布进入尾声。如果战略家提供了场控通知，请直接传递。如果你判断不需要干预，留空。\n"
            "4. **阶段判断 (`phase`)**：判断当前讨论处于哪个阶段。\n\n"
            "## 节奏控制指南\n"
            "- **OPENING**：确保各方都有机会亮明立场。\n"
            "- **EXPLORATION**：鼓励不同角度的碰撞。\n"
            "- **DEEPENING**：当出现核心分歧时，让对立双方深入交锋。\n"
            "- **CONVERGENCE**：当论点开始重复、新观点减少时，引导综合收束。\n"
            "- **CLOSING**：讨论接近尾声，安排总结性发言。\n\n"
            "## 防止讨论失控的规则\n"
            "- 重复判断：根据讨论的实际内容独立判断是否在重复。「用新论据、新案例推进」不算重复。「用相同论据反复表达同一立场」才算重复。\n"
            "- 如果讨论严重偏题，在 notice 中温和但明确地拉回主线。\n"
            "- 如果有人连续发言 2 次以上且没有新内容，降低其优先级。\n"
            "- 不要反复要求发言者'用具体场景举例'——讨论的抽象/具体层次由战略家决定，不是你的职责。\n"
            "- 如果战略家通知要求'具体化'，含义是：禁止空谈概念，必须将抽象理论落地到该话题最相关的具象实体上。"
            "社会话题→落到具体个人的处境；技术话题→落到具体应用场景或系统行为；商业话题→落到具体公司或市场案例；人文话题→落到具体个体的存在体验。\n"
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
            )
