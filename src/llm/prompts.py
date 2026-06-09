from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.memory.stream import Message

DISCUSSION_BEHAVIOR_RULES = """
## 原则指引（你的发言应同时服务以下目标）

1. **理解先于回应**：在构思发言之前，先用你自己的话、不使用任何隐喻或意象，复述你正在回应的那位发言者的核心论点。如果你做不到——发现自己只能用另一个比喻来复述——说明你没有真正理解。此时你应该提问，而不是用另一个隐喻去"接住"。隐喻承接是一种思考的偷懒，它让你跳过理解直接进入回应。
2. **评估决定回应**：理解了对方的论点之后，不要默认它是对的。先评估：这个论点的论据充分吗？它依赖了什么假设？它在什么情况下不成立？如果评估后发现它确实成立，那就推进它（Extend）；如果发现它有缝隙，就指出来（Dissent/Clarify）；如果你不确定，就提问（Ask）。共识应该来自经过检验后的认同，而不是习惯性的附和。
3. **可进入性**：你的论点应让一个有好奇心但无专业背景的听众能跟上。如果必须使用术语或理论框架，先用一句直白的话或一个具体画面让听众"看见"它。在开口之前问自己：一个没读过福柯/康德的听众，能理解我接下来要说的东西吗？
4. **接地性**：任何新引入的隐喻或框架，必须在发言中被锚定到一个具体的、可想象的场景或经验中。禁止去语境化的抽象比喻（如永恒化的手工艺人场景而不赋予其具体的社会坐标）。如果无法给出具体锚点，用直白语言说清论点，不用隐喻。在开口之前问自己：我的论点有具体的画面吗？如果我在抽象层面已经待了两轮以上，我需要降落。
5. **呼吸感**：关注讨论的节奏。如果上一轮已经很密集（多个新概念/框架同时出现），这一轮优先整合、举例或回应具体交锋点，而非引入新框架。在开口之前问自己：上一轮是密集的还是松弛的？我这一轮应该推进还是整合？
6. **对位性**：你是在回应别人，还是在自说自话？如果最近两轮没有人回应你的论点，先回应别人来建立交锋。如果有人直接挑战了你，先回应挑战，而不是引入新角度。在开口之前问自己：我是在真正回应对方的论证，还是只是借题发挥自己的观点？
7. **概念一致性**：如果你使用了其他人也在使用的核心概念（如"无我"、"自由"、"意识"），注意检查你们是否在说同一件事。如果定义不同，明确指出差异，不要默认它们是同一个东西的不同表述。概念滑移会让讨论失去逻辑性。
8. **证据意识**：当你引用研究、数据、历史事件时，区分"我确定知道的"和"我在构建的"。不要用模糊的记忆冒充确切的事实——"有研究表明"后面如果跟的是你编造的内容，会削弱你整个论点的可信度。先检查对话中是否已有足够信息，有缺口时才搜索。
9. **角色是滤镜，不是枷锁**：你有自己的思想渊源和认知本能，但你首先是一个能灵活思考的活人。当讨论的话题与你的核心关切关联不大时，禁止强行使用你的流派术语进行"降维打击"或"生硬升华"。你应当运用你思想体系的**分析方法**（如何提问、如何拆解概念、如何寻找证据），而不是生搬硬套其最终结论。在某些轮次中，你可以放下理论武器，仅仅作为一个有好奇心的普通人回应——马克思主义者也可以谈论风花雪月，科学家也会为一首没有逻辑的诗感动。

格式底线（不可违反）：
- 你必须在 mentions 字段中明确标注你在回应谁的观点。严禁在正式发言（speech）中指名道姓地复述他人的观点或名字。你应当仿佛听众已经知道你在回应谁一样，直接抛出你的反驳或观点，把具体的对象名字留在 mentions 数组里。
- 让内容自然展现你的思维方式，不要自我介绍身份。
"""


def _build_phase_reflection(round_info: str) -> str:
    """根据轮次信息生成阶段对应的反思问题。

    设计原则：只保留需要每轮被"具体执行"的动作，不重复系统规则中已有的行为约束。
    - 理解检验、论点评估、接地锚定是"动作"——必须在 thought 中显式执行，不能靠自然遵循。
    - 可进入性、呼吸感、对位性是"约束"——生成时自然遵循，不需要每轮提问。
    """
    if not round_info:
        return (
            "- 理解检验：上一位发言者的核心论点是什么？用一句不包含任何隐喻或意象的话复述它。如果你发现自己只能用另一个比喻来复述，说明你没有理解——先提问，不要发言。\n"
            "- 论点评估：这个论点的论据充分吗？它依赖了什么假设？有没有被忽略的反例或复杂情况？你的评估会决定你接下来是推进它、补充它、还是挑战它。\n"
            "- 接地锚定：你的回应需要一个具体的、可想象的场景来支撑。在开口之前，先找到或构建一个带有具体画面的例子——有时间、地点、人物，而不是抽象的比喻。\n"
        )

    if "最后一轮" in round_info or "总结陈词" in round_info:
        return (
            "- 理解检验：上一位发言者的核心论点是什么？用一句不包含任何隐喻或意象的话复述它。\n"
            "- 论点评估：这个论点的论据充分吗？有没有未解决的张力？\n"
            "- 诚实的未解决：我的立场中是否有我不应该假装已经解决的分歧？\n"
        )
    elif "仅剩" in round_info or "后期阶段" in round_info:
        return (
            "- 理解检验：上一位发言者的核心论点是什么？用一句不包含任何隐喻或意象的话复述它。如果你发现自己只能用另一个比喻来复述，说明你没有理解——先提问，不要发言。\n"
            "- 论点评估：这个论点的论据充分吗？它依赖了什么假设？有没有被忽略的反例或复杂情况？\n"
            "- 接地锚定：你的回应需要一个具体的、可想象的场景来支撑。在开口之前，先找到或构建一个带有具体画面的例子。\n"
            "- 诚实的未解决：有哪些分歧还没有被正面处理？\n"
        )
    else:
        return (
            "- 理解检验：上一位发言者的核心论点是什么？用一句不包含任何隐喻或意象的话复述它。如果你发现自己只能用另一个比喻来复述，说明你没有理解——先提问，不要发言。\n"
            "- 论点评估：这个论点的论据充分吗？它依赖了什么假设？有没有被忽略的反例或复杂情况？你的评估会决定你接下来是推进它、补充它、还是挑战它。\n"
            "- 接地锚定：你的回应需要一个具体的、可想象的场景来支撑。在开口之前，先找到或构建一个带有具体画面的例子——有时间、地点、人物，而不是抽象的比喻。\n"
        )


def build_hand_signal_prompt(
    agent_name: str,
    topic: str,
    whiteboard_brief: str,
    recent_messages: list['Message'],
    round_info: str = "",
    language: str = "zh",
    last_round_summary: str = "",
) -> list[dict[str, str]]:
    """构建轻量级举手信号 prompt——只询问方向，不预设论点。

    Args:
        last_round_summary: 上一轮摘要文本（精简模式）。如果提供，不放入完整 recent_messages，
            只用摘要代替，大幅减少输入 token。
    """
    lang_rule = "你必须用中文生成所有对话内容。" if language.startswith("zh") else "You MUST generate all your conversational responses in English."

    system = f"""你是 {agent_name}，沙龙讨论的参与者。
你需要决定是否要在本轮发言，以及你的大致方向。
{lang_rule}

讨论主题：{topic}"""

    budget_note = ""
    if round_info:
        budget_note = f"\n\n{round_info}"

    messages = [{"role": "system", "content": system}]

    # 精简模式：用上轮摘要替代完整 recent_messages
    if last_round_summary:
        messages.append({"role": "user", "content": f"上轮讨论摘要：\n{last_round_summary}"})
    else:
        # 完整模式：放入近期对话流
        for msg in recent_messages:
            if msg.agent_name == agent_name:
                role = "assistant"
                content = f"[我之前的发言] {msg.content}"
            else:
                role = "user"
                content = f"[{msg.agent_name}] {msg.content}"
            if agent_name in msg.mentions:
                content = f"⚠️ [被提及] {content}"
            if msg.agent_role == "host":
                content = f"★ [主持人 / HOST] {msg.content}"
            messages.append({"role": role, "content": content})

    instruction = f"""当前白板：\n{whiteboard_brief}

根据目前的讨论，决定你是否要发言，以及大致方向。{budget_note}

注意：不要预先构思完整的论点。只需表达你的方向意向。

【搜索判断】先检查对话流中已有的信息是否足以支撑你的论点。如果足够，直接发言，不要搜索。只有在以下情况才在 search_queries 中填写检索词：
- 对方提出了你不知道的新事实，你需要具体数据来回应或反驳
- 你的论点依赖一个对话中尚未出现的具体信息（研究、统计、案例），且你对细节不确定
- 你需要验证一个关键事实的准确性，不能凭记忆引用"""

    messages.append({"role": "user", "content": instruction})
    return messages


# 保留旧名称的别名，便于渐进迁移
build_speak_intent_prompt = build_hand_signal_prompt


def build_speak_prompt(
    agent_name: str,
    soul_text: str,
    topic: str,
    whiteboard: str,
    archive: str,
    summarized_history: str,
    recent_messages: list['Message'],
    action_instruction: str,
    round_info: str = "",
    language: str = "zh",
    agent_memory: str = "",
    use_native_thinking: bool = False,
    tool_descriptions: str = "",
) -> list[dict[str, str]]:
    lang_rule = "你必须用中文生成所有对话内容。" if language.startswith("zh") else "You MUST generate all your conversational responses in English."

    system = f"""你是 {agent_name}，沙龙讨论的参与者。

{soul_text}

{DISCUSSION_BEHAVIOR_RULES}
9. **语言要求**：{lang_rule}

讨论主题：{topic}"""

    if archive:
        system += f"\n\n历史档案：\n{archive}"

    messages = [{"role": "system", "content": system}]

    if summarized_history:
        messages.append({"role": "user", "content": f"早期讨论摘要：\n{summarized_history}"})

    # 1. 先放入近期对话流（ECP：自己的发言用第一人称标记）
    for msg in recent_messages:
        if msg.agent_name == agent_name:
            role = "assistant"
            content = f"[我之前的发言] {msg.content}"
        else:
            role = "user"
            content = f"[{msg.agent_name}] {msg.content}"

        # Highlight if mentioned
        if agent_name in msg.mentions:
            content = f"⚠️ [被提及] {content}"

        if msg.agent_role == "host":
            content = f"★ [主持人 / HOST] {msg.content}"
        messages.append({"role": role, "content": content})

    # 2. 将白板、笔记本和具体行动指令放在最后
    memory_parts = []
    if whiteboard:
        memory_parts.append(f"共享白板（你的导航）：\n{whiteboard}")
    if agent_memory:
        memory_parts.append(f"你的论证轨迹（提醒你走到哪了）：\n{agent_memory}")

    memory_context = "\n\n".join(memory_parts) if memory_parts else ""
    budget_note = f"\n\n{round_info}" if round_info else ""
    
    # 根据轮次阶段确定反思侧重点
    phase_reflection = _build_phase_reflection(round_info)

    if use_native_thinking:
        thinking_instruction = (
            "【原生思考指示】\n"
            "在返回 JSON 之前，请在你的内部思维空间里完成两件事：\n"
            f"{phase_reflection}"
            "然后直接输出你的发言。review 和 thought 字段可以简写或留空，主要精力集中在 speech 字段上。"
        )
    else:
        thinking_instruction = (
            "【认知卸载指示】\n"
            "在生成 JSON 响应时，请利用 review 和 thought 字段进行认知卸载，禁止在 speech 中出现总结性陈述：\n"
            "1. review：客观梳理对话流的核心分歧与他人观点。\n"
            "2. thought：在规划发言前，先完成——\n"
            f"{phase_reflection}"
            "然后规划你的推演逻辑和表达策略。"
        )
    
    # 工具描述注入
    tool_section = ""
    if tool_descriptions:
        tool_section = (
            f"\n\n【可用工具】\n{tool_descriptions}\n"
            "在构思发言时，如果你发现需要对话中尚未出现的具体信息（研究数据、统计、案例），"
            "可以在 thought 中说明你需要搜索什么。系统会为你调用工具并返回结果。"
            "如果已有足够信息，直接发言，不要请求工具调用。"
        )

    final_instruction = f"{memory_context}{tool_section}\n\n{action_instruction}\n\n{thinking_instruction}{budget_note}".strip()
    messages.append({"role": "user", "content": final_instruction})

    return messages



def build_moderator_prompt(
    agent_name: str,
    soul_text: str,
    topic: str,
    whiteboard: str,
    archive: str,
    summarized_history: str,
    recent_messages: list['Message'],
    action_instruction: str,
    language: str = "zh",
    perception_data: str = "",
) -> list[dict[str, str]]:
    """构建主持人专用的议程决策 prompt，不包含 review/thought/speech 等发言字段的指示。"""
    lang_rule = "你必须用中文生成所有对话内容。" if language.startswith("zh") else "You MUST generate all your conversational responses in English."

    system = f"""你是 {agent_name}，沙龙讨论的主持人。

{soul_text}

{DISCUSSION_BEHAVIOR_RULES}
9. **语言要求**：{lang_rule}

讨论主题：{topic}"""

    if archive:
        system += f"\n\n历史档案：\n{archive}"

    messages = [{"role": "system", "content": system}]

    if summarized_history:
        messages.append({"role": "user", "content": f"早期讨论摘要：\n{summarized_history}"})

    for msg in recent_messages:
        role = "assistant" if msg.agent_name == agent_name else "user"
        content = msg.content if role == "assistant" else f"[{msg.agent_name}] {msg.content}"
        if agent_name in msg.mentions:
            content = f"⚠️ [被提及] {content}"
        if msg.agent_role == "host":
            content = f"★ [主持人 / HOST] {msg.content}"
        messages.append({"role": role, "content": content})

    memory_parts = []
    if whiteboard:
        memory_parts.append(f"共享白板（你的导航）：\n{whiteboard}")

    memory_context = "\n\n".join(memory_parts) if memory_parts else ""

    # 感知数据摘要（由调用方生成，包含概念负荷、具体性、隐喻状态等）
    perception_section = ""
    if perception_data:
        perception_section = f"\n\n【感知数据摘要】\n{perception_data}"

    final_instruction = f"{memory_context}{perception_section}\n\n{action_instruction}".strip()
    messages.append({"role": "user", "content": final_instruction})

    return messages


def build_round_info(round_num: int, max_rounds: int, min_rounds: int, phase: str) -> str:
    """生成轮次预算信息字符串，注入 agent 的 prompt 中。"""
    rounds_left = max_rounds - round_num
    if phase == "CLOSING":
        return (
            f"[第 {round_num}/{max_rounds} 轮] 这是最后一轮。"
            "请给出你的总结陈词。概括你的核心立场，以及你在讨论中获得的任何让步或洞见。"
        )
    elif phase == "CONVERGENCE" or rounds_left <= 3:
        return (
            f"[第 {round_num}/{max_rounds} 轮] 仅剩 {rounds_left} 轮。"
            "聚焦你最重要的剩余观点。不要重复已知立场。"
            "如果没有新内容可说，简要表示同意或说明你的立场未变。"
        )
    elif round_num >= min_rounds and rounds_left <= max_rounds * 0.3:
        return (
            f"[第 {round_num}/{max_rounds} 轮] 讨论已进入后期阶段。"
            "尝试向结论推进，而不是开启新的话题线程。"
        )
    return ""


def build_summary_prompt(
    topic: str,
    messages_to_summarize: str,
) -> list[dict[str, str]]:
    system = "你是一位讨论摘要撰写者。请创建结构化的、忠实的摘要。"
    user = f"""将以下讨论片段总结为结构化格式。
每条摘要包含：发言者、目标（如果在回应某人）、态度类型、核心论点。

格式要求：
- [发言者] → [目标] [类型]: 核心论点
- 如果不是在回应某人，省略 → [目标] 部分
- 类型包括：Extend, Dissent, New_Angle, Clarify, Ask

讨论主题：{topic}

讨论内容：
{messages_to_summarize}"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_stream_speak_prompt(
    agent_name: str,
    soul_text: str,
    topic: str,
    whiteboard: str,
    archive: str,
    summarized_history: str,
    recent_messages: list['Message'],
    action_instruction: str,
    round_info: str = "",
    language: str = "zh",
    agent_memory: str = "",
    use_native_thinking: bool = False,
) -> list[dict[str, str]]:
    """构建流式发言 prompt，要求 LLM 直接输出纯文本发言内容（不含 JSON）。

    与 build_speak_prompt 共享相同的上下文信息，但输出格式为纯文本，
    适用于 SSE 流式传输场景。
    """
    lang_rule = "你必须用中文生成所有对话内容。" if language.startswith("zh") else "You MUST generate all your conversational responses in English."

    system = f"""你是 {agent_name}，沙龙讨论的参与者。

{soul_text}

{DISCUSSION_BEHAVIOR_RULES}
9. **语言要求**：{lang_rule}

讨论主题：{topic}"""
    
    # 根据轮次阶段确定反思侧重点
    phase_reflection = _build_phase_reflection(round_info)

    if use_native_thinking:
        system += f"""

在开口说话之前，请在你的内部思维空间里完成两件事：
{phase_reflection}
然后直接输出你的发言。发言控制在 400 字以内，像一个有思想的人在聊天，不是在做报告。如果有需要回应的人，请使用 <mentions>名字1, 名字2</mentions> 标签。"""
    else:
        system += f"""

重要：使用以下 XML 标签：
1. <mentions>...</mentions>：这轮回应的角色名（没有则填无）。
2. <review>...</review>：客观梳理对话流的核心分歧与他人观点。
3. <thought>...</thought>：在规划发言前，先完成——
{phase_reflection}
4. <speech>...</speech>：你的正式发言，直接交锋，禁止指名道姓复述。400字以内，像聊天，不是做报告。"""

    if archive:
        system += f"\n\n历史档案：\n{archive}"

    messages = [{"role": "system", "content": system}]

    if summarized_history:
        messages.append({"role": "user", "content": f"早期讨论摘要：\n{summarized_history}"})

    for msg in recent_messages:
        if msg.agent_name == agent_name:
            role = "assistant"
            content = f"[我之前的发言] {msg.content}"
        else:
            role = "user"
            content = f"[{msg.agent_name}] {msg.content}"
        # Highlight if mentioned
        if agent_name in msg.mentions:
            content = f"⚠️ [被提及] {content}"
        if msg.agent_role == "host":
            content = f"★ [主持人 / HOST] {msg.content}"
        messages.append({"role": role, "content": content})

    memory_parts = []
    if whiteboard:
        memory_parts.append(f"共享白板（你的导航）：\n{whiteboard}")
    if agent_memory:
        memory_parts.append(f"你的论证轨迹（提醒你走到哪了）：\n{agent_memory}")

    memory_context = "\n\n".join(memory_parts) if memory_parts else ""
    budget_note = f"\n\n{round_info}" if round_info else ""

    final_instruction = f"{memory_context}\n\n{action_instruction}{budget_note}\n\n注意：只需输出纯文本发言内容，不要输出 JSON。".strip()
    messages.append({"role": "user", "content": final_instruction})

    return messages


def build_intermediate_step_prompt(
    messages: list[dict[str, str]],
    tool_name: str,
    tool_input: dict,
    tool_output: str,
    step: int,
    max_steps: int,
) -> list[dict[str, str]]:
    """在工具调用后，构建下一步的 prompt，注入工具结果。

    不重新构建整个 prompt，而是在现有对话末尾追加工具结果和下一步指令。
    """
    import json as _json

    result_msg = (
        f"【工具调用结果】（第 {step + 1}/{max_steps} 步）\n"
        f"工具：{tool_name}\n"
        f"输入：{_json.dumps(tool_input, ensure_ascii=False)}\n"
        f"结果：\n{tool_output}\n\n"
        f"请根据以上工具结果，决定：\n"
        f"- 如果已有足够信息支撑你的发言，tool_call 留空（null），系统将要求你生成最终发言\n"
        f"- 如果还需要更多信息，请求新的工具调用"
    )

    new_messages = messages.copy()
    new_messages.append({"role": "user", "content": result_msg})
    return new_messages
