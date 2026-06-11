"""议题战略家——管理讨论的维度空间，守护初始主题不被偏离。

战略家的核心职责：
1. 开局生成 DiscussionRoadmap（从主题提取不可放弃的维度）
2. 每轮对照路线图检查进度，决定是否切换维度
3. 生成锚定问题 + CoT 模板，注入发言者的思考过程
4. 生成主持人场控通知（主持人只做传递，不做内容判断）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from src.agents.base import BaseAgent, DiscussionContext
from src.config import SalonConfig
from src.llm.prompts import build_speak_prompt
from src.models import AnchorCoverageCheck

if TYPE_CHECKING:
    from src.llm.client import LLMClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 路线图模型（开局一次性生成，整个会话期间不变）
# ---------------------------------------------------------------------------

class MandatoryDim(BaseModel):
    """必须覆盖的讨论维度"""
    id: str = Field(description="维度的简短标识，如 dim_a")
    label: str = Field(description="维度的一句话描述")
    core_question: str = Field(
        description="这个维度要回答的核心问题——具体、有争议、所有视角都能切入"
    )
    why_mandatory: str = Field(description="为什么这个维度不能跳过（与初始主题的关联）")
    escape_valves: list[str] = Field(
        default_factory=list,
        description="允许角色从哪些角度切入这个维度（给角色留灵活性）"
    )


class DiscussionRoadmap(BaseModel):
    """讨论路线图——开局一次性生成，锁定讨论必须覆盖的维度。"""
    topic: str = Field(description="讨论话题")
    core_question: str = Field(description="从主题中提取的核心追问（一句话）")
    mandatory_dimensions: list[MandatoryDim] = Field(
        description="3-4 个必须覆盖的维度"
    )
    dimension_sequence: list[str] = Field(
        description="建议的维度探索顺序（维度 ID 列表）"
    )


# ---------------------------------------------------------------------------
# 每轮输出模型
# ---------------------------------------------------------------------------


class StrategyOutput(BaseModel):
    """战略家每轮输出——仅内容生成，不做状态决策。

    维度切换（should_switch）和当前维度（current_dimension_id）由代码状态机决定，
    战略家只需为当前维度生成引导性内容。
    """

    # 锚定问题（纯内容生成）
    anchor_question: str = Field(
        description="本轮锚定问题——具体、有争议、与当前维度直接对齐"
    )

    # CoT 模板（纯内容生成）
    cot_template: str = Field(
        description="注入发言者思考过程的强制模板"
    )

    # 主持人通知（纯内容生成）
    moderator_notice: str | None = Field(
        default=None,
        description="战略家决定的场控通知（主持人只做传递）"
    )

    # 建议性字段（代码可覆盖）
    grounding_needed: bool = Field(
        default=False,
        description="建议：当前讨论是否需要用具体场景来推进"
    )
    preferred_agents: list[str] = Field(
        default_factory=list,
        description="建议：本轮最适合发言的参与者 agent ID"
    )

    # 评估字段（供代码交叉验证，不直接驱动状态转移）
    anchor_coverage: AnchorCoverageCheck | None = Field(
        default=None,
        description="上一轮锚定问题的回应评估（供代码交叉验证）"
    )


# ---------------------------------------------------------------------------
# 向后兼容的旧模型（逐步废弃）
# ---------------------------------------------------------------------------

class NewDimension(BaseModel):
    """战略家建议新增的维度（旧模型，保留兼容）"""
    id: str = Field(description="维度的简短标识")
    label: str = Field(description="维度的一句话描述")
    rationale: str = Field(description="为什么这个维度值得讨论")


class MapUpdate(BaseModel):
    """维度地图更新指令（旧模型，保留兼容）"""
    mark_covered: list[str] = Field(default_factory=list)
    mark_active: list[str] = Field(default_factory=list)
    add_dimension: list[NewDimension] = Field(default_factory=list)
    depth_increment: list[str] = Field(default_factory=list)
    archive_dimension: list[str] = Field(default_factory=list)


class DirectionGuidance(BaseModel):
    """本轮方向建议（旧模型，保留兼容）"""
    target_dimension: str = Field(description="下一步建议探索的维度 ID")
    reason: str = Field(description="为什么选这个维度")
    anchor_question: str = Field(description="锚定问题")
    preferred_agents: list[str] = Field(default_factory=list)


class DimensionMapInit(BaseModel):
    """维度地图初始化输出（旧模型，保留兼容）"""
    dimensions: list[InitDimension] = Field(description="初始化的维度列表")


class InitDimension(BaseModel):
    """初始化维度（旧模型，保留兼容）"""
    id: str
    label: str
    rationale: str
    depends_on: list[str] = Field(default_factory=list)
    type: str = Field(default="core", json_schema_extra={"enum": ["core", "placeholder"]})


# ---------------------------------------------------------------------------
# 战略家 Agent
# ---------------------------------------------------------------------------

class TopicStrategist(BaseAgent):
    """议题战略家——议程守护者，不是即兴配合者。"""

    def __init__(self, agent_id: str, soul_path: str, config: SalonConfig):
        super().__init__(agent_id, soul_path, config)
        self.role = "strategist"
        self._roadmap: DiscussionRoadmap | None = None
        self._last_anchor_question: str = ""
        self._last_dimension_id: str = ""

    @property
    def roadmap(self) -> DiscussionRoadmap | None:
        return self._roadmap

    # ------------------------------------------------------------------
    # 路线图初始化（开局一次性调用）
    # ------------------------------------------------------------------

    def initialize_roadmap(
        self,
        topic: str,
        llm: LLMClient,
        total_rounds: int,
        language: str = "zh",
    ) -> DiscussionRoadmap | None:
        """从主题中提取不可放弃的维度，生成讨论路线图。

        Args:
            topic: 讨论话题
            llm: LLM 客户端
            total_rounds: 总轮次（用于估算每维度轮次）
            language: 语言

        Returns:
            DiscussionRoadmap 或 None（解析失败时）
        """
        # 根据总轮次给出节奏建议
        if total_rounds <= 10:
            pacing_hint = "轮次紧张（≤10轮），建议只锁定 2-3 个最核心的维度，每个维度 2-3 轮。宁可少而深，不要浅而散。"
        elif total_rounds <= 20:
            pacing_hint = "轮次适中（10-20轮），建议 3-4 个维度，每个维度 3-5 轮。前半段探索，后半段收敛。"
        else:
            pacing_hint = "轮次充裕（>20轮），建议 3-4 个维度，每个维度可以深入 5-8 轮。有足够空间让不同视角充分碰撞。"

        action = f"""给定讨论话题：{topic}
总轮次：{total_rounds}

请将这个话题拆解为 3-4 个**不可放弃**的讨论维度。

每个维度必须满足：
1. 它回答了这个话题中一个不可回避的核心子问题
2. 如果跳过它，讨论就是不完整的
3. 不同思想传统在这个维度上必然会有碰撞

请先分析该话题的【核心属性】，它属于以下哪一类（或哪几类的结合）：
1. 社会/伦理类（探讨资源分配、人类命运、道德边界）
2. 技术/科学类（探讨实现路径、技术优劣、原理突破）
3. 商业/战略类（探讨商业模式、市场竞争、经济效益）
4. 哲学/人文类（探讨意义、历史演变、美学价值）

根据判断出的【核心属性】，设计维度。

【深度要求】不管是什么属性的话题，维度设计必须包含"底层张力"：
- 如果是技术/商业类：必须包含"Trade-off（核心代价与权衡）"维度
  （例："追求性能必定牺牲安全？""规模化会不会杀死差异化？"）
- 如果是社会/人文类：必须包含"隐性假设的刺破"维度
  （例："这个问题是不是由于我们默认了某种不合理的前提导致的？"）
- 如果是混合类：维度之间应该有张力，不同属性的维度应该互相构成挑战

为每个维度定义 core_question：
- 这个问题必须是具体的、有争议的
- 所有思想传统/技术流派都能从自己的角度切入
- 不要问"你怎么看"——要问"凭什么"、"代价是什么"、"如果前提崩溃了呢"

维度数量：3-4 个（不要贪多，锁定最核心的）。

节奏提示：{pacing_hint}

请给出建议的探索顺序（dimension_sequence），但讨论中可以根据实际情况调整。"""

        messages = [
            {
                "role": "system",
                "content": (
                    "你是议题战略家。你的职责是为讨论话题设计路线图。\n"
                    "路线图将锁定讨论必须覆盖的维度，防止讨论被角色的灵魂滤镜带偏。\n"
                    f"语言：{language}"
                ),
            },
            {"role": "user", "content": action},
        ]
        try:
            result = llm.chat_structured(messages, DiscussionRoadmap)
            if result:
                self._roadmap = result
                logger.info(
                    f"[Strategist] 路线图已生成: {len(result.mandatory_dimensions)} 个维度, "
                    f"核心追问: {result.core_question}"
                )
            return result
        except Exception as e:
            logger.warning(f"[Strategist] 路线图生成失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 每轮战略决策
    # ------------------------------------------------------------------

    def decide_strategy(
        self,
        context: DiscussionContext,
        llm: LLMClient,
        round_analysis_text: str,
        round_num: int,
        total_rounds: int,
        last_anchor_question: str = "",
        last_anchor_coverage: AnchorCoverageCheck | None = None,
        language: str = "zh",
    ) -> StrategyOutput | None:
        """每轮战略决策——对照路线图检查进度，决定下一步。

        Args:
            context: 战略家的讨论上下文
            llm: LLM 客户端
            round_analysis_text: 记录员本轮分析的格式化文本
            round_num: 当前轮次
            total_rounds: 总轮次
            last_anchor_question: 上一轮的锚定问题
            last_anchor_coverage: 上一轮锚定问题的回应检查
            language: 语言

        Returns:
            StrategyOutput 或 None（解析失败时）
        """
        if not self._roadmap:
            logger.warning("[Strategist] 路线图未初始化，无法决策")
            return None

        rounds_left = total_rounds - round_num
        roadmap_text = self._format_roadmap()

        # 节奏阶段判断
        progress = round_num / total_rounds
        if progress <= 0.3:
            phase_hint = (
                "当前处于讨论前段（≤30%）。可以花时间在当前维度上深入，"
                "让不同角色充分亮明立场。不要急于切换维度。"
            )
        elif progress <= 0.7:
            phase_hint = (
                "当前处于讨论中段（30%-70%）。这是核心探索期。"
                "如果当前维度已被多人从不同角度回应，应该切换到下一个维度。"
                "确保所有维度都有机会被讨论。"
            )
        else:
            phase_hint = (
                "当前处于讨论后段（>70%）。剩余轮次有限。"
                "如果还有未覆盖的维度，必须立即切换——即使当前维度讨论正酣。"
                "如果所有维度都已覆盖，可以进入收敛总结。"
            )

        # 每维度建议轮次
        dim_count = len(self._roadmap.mandatory_dimensions) if self._roadmap else 4
        rounds_per_dim = max(2, total_rounds // (dim_count + 1))  # +1 留给收尾

        coverage_text = ""
        if last_anchor_coverage:
            quality_map = {
                "deep": "深入回应",
                "surface": "表面回应",
                "token": "敷衍（只提了一句）",
                "ignored": "完全没回应",
                "unknown": "未知",
            }
            coverage_text = f"""
=== 上一轮锚定问题回应检查 ===
锚定问题：{last_anchor_question}
是否被回应：{"是" if last_anchor_coverage.was_addressed else "否"}
回应质量：{quality_map.get(last_anchor_coverage.quality, last_anchor_coverage.quality)}
谁回应了：{', '.join(last_anchor_coverage.who_addressed) if last_anchor_coverage.who_addressed else '无人'}
证据：{last_anchor_coverage.evidence or '无'}
需要升级约束：{"是" if last_anchor_coverage.needs_escalation else "否"}"""

        # 获取当前维度信息（由代码状态机决定，注入 prompt）
        current_dim = self._get_current_dimension_info()

        action = f"""你是本次讨论的议题战略家。你的职责是为当前讨论维度生成引导性内容。

=== 讨论路线图（开局锁定，不可修改）===
{roadmap_text}

=== 当前维度（由代码状态机决定，不可修改）===
{current_dim}

=== 记录员本轮分析 ===
{round_analysis_text}
{coverage_text}

=== 当前状态 ===
轮次：{round_num} / {total_rounds}（剩余 {rounds_left} 轮）
每维度建议轮次：{rounds_per_dim} 轮
上一轮锚定问题：{last_anchor_question or '（首轮）'}

=== 节奏提示 ===
{phase_hint}

## 重要：你不需要决定
- ❌ 是否切换维度（代码已决定）
- ❌ 当前是哪个维度（代码已告诉你）
- ❌ 讨论阶段（代码已决定）

你需要做：

1. **生成锚定问题**（核心职责——你不是记录员，你是挑事者）：
   - 必须与当前维度的 core_question 直接对齐
   - 【刺破框架】如果发言者都在同一个前提下打转，你的问题必须质疑该前提。
     （例："你们似乎都默认了系统必须是中心化的，如果去中心化才是唯一解呢？"）
   - 【逼问代价】任何方案都有代价。强制发言者直面最核心的权衡（Trade-off）。
     （例："方案A获得了效率但牺牲了隐私，方案B反之。在这个话题语境下，必须牺牲哪一个？"）
   - 【代入利益攸关方】无论话题多宏观，必须将其影响降维到该话题的"核心受影响实体"上。
     - 社会话题 → 落到最底层的从业者/受影响群体的处境
     - 技术话题 → 落到运维/使用该系统的工程师或用户的实际体验
     - 商业话题 → 落到具体公司/消费者/竞争者的利益
     - 人文话题 → 落到具体个体的存在体验和意义感
   - 不要问"你怎么看"——要问"凭什么"、"代价是什么"、"如果前提崩溃了呢"
   - 如果上一轮锚定问题被忽略或敷衍，换一种更尖锐的提问方式

3. **生成 CoT 模板**：
   - 这个模板会注入到发言者的思考过程中
   - 强制发言者在说话之前先思考当前维度的核心问题
   - 如果讨论正在滑向纯技术/政策分析，在 CoT 中加入"痛感链接"约束
   - 模板格式见下方

4. **决定主持人通知**：
   - 如果讨论充斥术语和政策黑话，grounding_needed = True
   - "具体化"的含义不是"给政策实施细节"，而是"用隐喻或一个具体个体的命运来展示理论"
   - 如果讨论正在深入且有产出，不要打断
   - moderator_notice 留空则主持人不发通知

5. **选人建议**（preferred_agents）：
   - 指出 1-2 个最适合展开当前维度的参与者
   - 不要总是选同一个人

CoT 模板格式（你生成的 cot_template 必须遵循这个结构）：

【必答题】当前维度：{{维度标签}}
核心问题：{{维度核心问题}}

从我的视角看，这个问题的关键是：____
我之前在这个维度上已经说过：____（避免重复）
本轮我可以推进的新方向（我必须点出当前方案的代价，或提出一个颠覆性视角）：____

（最后自我审查：我的发言是否只是正确的废话？如果我把这段话念给最关心这个话题的人听，他们会有所启发吗？）____

完成以上思考后，再生成正式发言。
发言风格要求：犀利、清晰。如果是人文社会话题，要有温度；如果是硬科技商业话题，要刀刀见血，禁止泛泛而谈。

你不做：
- 决定是否切换维度（代码状态机已决定）
- 选谁发言（你只提建议）
- 评判哪个观点对错
- 修改路线图（它是开局锁定的）"""

        messages = build_speak_prompt(
            agent_name=self.name,
            soul_text=self.soul.get_full_prompt(),
            topic=context.topic,
            whiteboard=context.whiteboard_text,
            archive=context.archive_text,
            summarized_history=context.summarized_history,
            recent_messages=context.recent_messages,
            action_instruction=action,
            language=language,
        )
        try:
            result = llm.chat_structured(messages, StrategyOutput)
            if result:
                self._last_anchor_question = result.anchor_question
                logger.info(
                    f"[Strategist] 战略决策: "
                    f"grounding={result.grounding_needed}, "
                    f"preferred={result.preferred_agents}"
                )
            return result
        except Exception as e:
            logger.warning(f"[Strategist] 战略决策失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _format_roadmap(self) -> str:
        """格式化路线图为可读文本。"""
        if not self._roadmap:
            return "（路线图未初始化）"

        parts = [f"核心追问：{self._roadmap.core_question}"]
        parts.append(f"探索顺序：{' → '.join(self._roadmap.dimension_sequence)}")
        parts.append("")
        for dim in self._roadmap.mandatory_dimensions:
            parts.append(f"【{dim.id}】{dim.label}")
            parts.append(f"  核心问题：{dim.core_question}")
            parts.append(f"  不可跳过原因：{dim.why_mandatory}")
            if dim.escape_valves:
                parts.append(f"  允许的切入角度：{', '.join(dim.escape_valves)}")
            parts.append("")

        return "\n".join(parts)

    def get_current_dimension(self) -> MandatoryDim | None:
        """获取当前正在探索的维度。"""
        if not self._roadmap:
            return None
        for dim in self._roadmap.mandatory_dimensions:
            if dim.id == self._last_dimension_id:
                return dim
        # 默认返回第一个
        return self._roadmap.mandatory_dimensions[0] if self._roadmap.mandatory_dimensions else None

    def _get_current_dimension_info(self) -> str:
        """获取当前维度的格式化信息（注入 prompt）。

        由 SessionController 的 DimensionState 驱动，
        如果无 SessionController 则回退到路线图第一个维度。
        """
        if not self._roadmap:
            return "（路线图未初始化）"
        # 优先使用 SessionController 的当前维度（如果有外部注入）
        # 否则默认使用路线图第一个维度
        dim = self._roadmap.mandatory_dimensions[0] if self._roadmap.mandatory_dimensions else None
        if not dim:
            return "（无维度信息）"
        return (
            f"维度 ID：{dim.id}\n"
            f"维度描述：{dim.label}\n"
            f"核心问题：{dim.core_question}\n"
            f"不可跳过原因：{dim.why_mandatory}"
        )

    def get_dimension_by_id(self, dim_id: str) -> MandatoryDim | None:
        """根据 ID 获取维度。"""
        if not self._roadmap:
            return None
        for dim in self._roadmap.mandatory_dimensions:
            if dim.id == dim_id:
                return dim
        return None

    # ------------------------------------------------------------------
    # 向后兼容：保留旧接口，内部委托到新实现
    # ------------------------------------------------------------------

    def initialize_dimension_map(
        self, topic: str, llm: LLMClient, language: str = "zh",
    ) -> DimensionMapInit | None:
        """旧接口：初始化维度地图。内部委托到 initialize_roadmap。"""
        logger.info("[Strategist] 调用了旧接口 initialize_dimension_map，建议改用 initialize_roadmap")
        roadmap = self.initialize_roadmap(topic, llm, total_rounds=15, language=language)
        if not roadmap:
            return None
        # 转换为旧格式
        return DimensionMapInit(
            dimensions=[
                InitDimension(
                    id=d.id, label=d.label, rationale=d.core_question,
                    depends_on=[], type="core",
                )
                for d in roadmap.mandatory_dimensions
            ]
        )
