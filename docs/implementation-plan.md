# 实施计划：主持人重构工程

## 总体策略

按阶段顺序实施，每个阶段独立可验证。每完成一个阶段，跑一次会话验证效果。

**预计文件改动**：8 个文件修改 + 1 个新文件

---

## 阶段 1：记录员升级——每轮结构化分析

### 改动文件

**1.1 `src/agents/scribe.py` — 新增模型和方法**

在文件顶部（现有 `WhiteboardOperation` 之前）新增 Pydantic 模型：

```python
class ArgumentSummary(BaseModel):
    """单个发言者的核心论点"""
    agent_id: str
    core_claim: str          # 一句话核心主张
    key_metaphor: str | None = None  # 本轮引入的关键比喻
    responds_to: str | None = None   # 回应了谁的什么观点

class CoveredDimension(BaseModel):
    """维度覆盖记录（附证据）"""
    id: str                  # 维度 ID
    confidence: str          # "high" 或 "low"
    evidence: str            # 触发该维度的发言原句摘要

class RoundAnalysis(BaseModel):
    """记录员每轮输出的结构化分析"""
    arguments: list[ArgumentSummary]
    new_angles: list[str] = []
    covered_dimensions: list[CoveredDimension] = []
    convergence_hint: str = ""
```

在 `ScribeAgent` 类中新增方法：

```python
def analyze_round(
    self,
    context: DiscussionContext,
    llm: LLMClient,
    dimension_labels: list[str],  # 当前维度地图的 label 列表
    language: str = "zh"
) -> RoundAnalysis | None:
    """每轮发言结束后运行，提取结构化论点和维度覆盖信息"""
    # 构建 prompt
    action = self._build_analysis_action(dimension_labels)
    messages = build_speak_prompt(
        self.name, self.soul.get_full_prompt(), context.topic,
        context.whiteboard_text, context.archive_text,
        context.summarized_history, context.recent_messages,
        action, "", language
    )
    try:
        return llm.chat_structured(messages, RoundAnalysis)
    except Exception:
        return None

def _build_analysis_action(self, dimension_labels: list[str]) -> str:
    """构建记录员分析的 action instruction"""
    dim_list = "\n".join(f"  - {label}" for label in dimension_labels) if dimension_labels else "  （尚未初始化）"
    return f"""你是本轮的记录员。请阅读本轮所有发言，输出结构化分析。

你需要做：
1. 提取每个发言者的核心主张（一句话）
2. 标记本轮是否引入了新的讨论角度（不在以下已知维度列表中的）
3. 标记本轮触及了以下已知维度中的哪些（附证据）
4. 一句话判断：当前讨论是否有收敛到某个狭窄方向的趋势

已知维度列表：
{dim_list}

你不需要做：
- 判断讨论应该往哪个方向走
- 评判哪个观点更好
- 提出新的讨论问题

去重规则：
- 如果你发现的新角度与已知维度中的任何一个实质相同（只是措辞不同），
  不要标记为 new_angle，而是标记为对应维度的 covered。"""
```

**1.2 `src/llm/prompts.py` — 无需改动**

`speak.py` 中的 `analyze_round` 复用了 `build_speak_prompt`，不需要新的 prompt builder。这保持了与现有架构的一致性。

**1.3 `src/core/modes/salon.py` — 插入记录员分析步骤**

在 `execute_round` 方法中，Phase 6（`_serial_speak`）结束后的 `_scribe_sync` 之后，新增 `_scribe_analyze` 调用：

```python
def _scribe_analyze(self, ctx: ModeContext, round_num: int) -> RoundAnalysis | None:
    """记录员每轮结构化分析"""
    scribe_ctx = ctx.context_manager.build_context(
        ctx.scribe, ctx.memory, round_num, context_type="scribe"
    )
    # 获取当前维度标签列表
    dim_labels = self._get_dimension_labels(ctx)
    return ctx.scribe.analyze_round(scribe_ctx, ctx.llm, dim_labels, ctx.config.language)

def _get_dimension_labels(self, ctx: ModeContext) -> list[str]:
    """从白板 dimension_map section 提取维度标签"""
    entries = ctx.memory.whiteboard.sections.get("dimension_map", [])
    if not entries:
        return []
    # 解析 YAML 格式的 dimension_map
    try:
        import yaml
        data = yaml.safe_load(entries[-1].content)
        return [d["label"] for d in data.get("dimensions", [])]
    except Exception:
        return []
```

在 `execute_round` 末尾调用：

```python
# Phase 6 结束后
self._scribe_sync(ctx, round_num)
# 新增：记录员分析
round_analysis = self._scribe_analyze(ctx, round_num)
if round_analysis:
    ctx.last_round_analysis = round_analysis  # 存储在 ModeContext 中
```

**1.4 `src/core/modes/salon.py` — ModeContext 增加字段**

在 `ModeContext` 类中新增：

```python
last_round_analysis: RoundAnalysis | None = None
```

### 验证方法

跑一次完整会话，检查：
1. `RoundAnalysis.arguments` 中每个发言者的 `core_claim` 是否准确
2. `covered_dimensions` 是否有 evidence
3. `convergence_hint` 是否合理
4. 分析过程是否影响会话性能（额外 LLM 调用延迟）

---

## 阶段 2：维度地图——白板升级

### 改动文件

**2.1 `config/default.yaml` — 新增 section**

在 `memory.whiteboard.sections` 列表中新增 `dimension_map`：

```yaml
memory:
  whiteboard:
    sections:
      - current_focus
      - discussion_phase
      - current_topic
      - consensus
      - disagreements
      - backlog
      - surprises
      - agenda_trace
      - active_concepts
      - dimension_map    # 新增
```

**2.2 `src/config.py` — WhiteboardConfig 更新**

确认 `WhiteboardConfig.sections` 的默认列表中包含 `dimension_map`。如果 sections 是从 YAML 动态加载的，则无需改代码；如果是硬编码的默认值，需要新增。

**2.3 `src/memory/whiteboard.py` — to_prompt_text 中的标签映射**

在 `_SECTION_LABELS` 字典中新增：

```python
"dimension_map": "讨论维度地图",
```

**2.4 `src/agents/scribe.py` — sync_whiteboard 增加维度维护**

在 `sync_whiteboard` 的 action instruction 中新增维度地图维护指令：

```python
# 在现有 action instruction 末尾追加：
"""
维度地图维护（dimension_map section）：
- 如果本轮讨论明显触及了某个维度（即使没有完全覆盖），标记该维度的 depth +1
- 如果记录员分析发现了 new_angles，将它们作为 emergent 维度追加到地图中
- 维度地图使用 YAML 格式存储
- 维度总数不超过 9 个（含 placeholder）
"""
```

需要在 `WhiteboardOperation` 的 `section` 枚举中新增 `"dimension_map"`。

### 验证方法

手动构造一份维度地图写入白板，检查 `to_prompt_text` 是否正确渲染。

---

## 阶段 3：战略家——核心新组件

### 改动文件

**3.1 新建 `src/agents/strategist.py`**

```python
"""议题战略家——管理讨论的维度空间"""
from pydantic import BaseModel
from src.agents.base import BaseAgent, DiscussionContext
from src.llm.client import LLMClient
from src.llm.prompts import build_speak_prompt


class NewDimension(BaseModel):
    id: str
    label: str
    rationale: str


class MapUpdate(BaseModel):
    mark_covered: list[str] = []
    mark_active: list[str] = []
    add_dimension: list[NewDimension] = []
    depth_increment: list[str] = []


class DirectionGuidance(BaseModel):
    target_dimension: str
    reason: str
    anchor_question: str
    preferred_agents: list[str] = []


class StrategyOutput(BaseModel):
    map_update: MapUpdate
    direction: DirectionGuidance
    convergence_response: str | None = None


class TopicStrategist(BaseAgent):
    """议题战略家——只关心维度空间管理，不选人不发通知"""

    def __init__(self, agent_id: str, soul_path: str, config):
        super().__init__(agent_id, soul_path, config)
        self.role = "strategist"
        self._last_direction: DirectionGuidance | None = None

    def decide_strategy(
        self,
        context: DiscussionContext,
        llm: LLMClient,
        round_analysis_text: str,
        dimension_map_text: str,
        signal_summary: str,
        participants: list[str],
        rounds_left: int,
        language: str = "zh",
    ) -> StrategyOutput | None:
        action = self._build_strategy_action(
            round_analysis_text, dimension_map_text, signal_summary,
            participants, rounds_left
        )
        messages = build_speak_prompt(
            self.name, self.soul.get_full_prompt(), context.topic,
            context.whiteboard_text, context.archive_text,
            context.summarized_history, context.recent_messages,
            action, "", language
        )
        try:
            result = llm.chat_structured(messages, StrategyOutput)
            self._last_direction = result.direction
            return result
        except Exception:
            return None

    def _build_strategy_action(
        self, analysis_text, dim_map_text, signal_summary,
        participants, rounds_left
    ):
        last_dir = ""
        if self._last_direction:
            last_dir = f"""
上一轮的战略方向：
- 目标维度：{self._last_direction.target_dimension}
- 锚定问题：{self._last_direction.anchor_question}
- 原因：{self._last_direction.reason}
请评估这个方向是否被有效推进，是否需要调整。"""

        return f"""你是本次讨论的议题战略家。你的职责是管理讨论的维度空间，防止讨论过早收敛。

=== 记录员本轮分析 ===
{analysis_text}

=== 维度地图 ===
{dim_map_text}

=== 信号摘要 ===
{signal_summary}
{last_dir}

=== 参与者 ===
{', '.join(participants)}

=== 剩余轮次 ===
{rounds_left}

你需要做：
1. 更新维度地图（map_update）：标记本轮覆盖了什么、是否发现新维度
2. 判断下一步应该探索哪个维度（direction）
3. 如果发现讨论正在收敛到某个狭窄方向，提出维度切换（convergence_response）

维度切换的原则：
- 不要打断正在深入且有产出的讨论
- 当讨论在同一维度上连续多轮没有新的子问题或比喻时，考虑切换
- 切换时选择与当前维度正交的方向——即不会被角色的自然反应自动覆盖的维度
- 切换不是断裂，anchor_question 要让新旧维度产生连接

维度数量硬上限 9 个。如果需要新增且已达上限，将一个已覆盖的维度标记为 archived。

你不做：
- 选谁发言（这是战术层的事）
- 发通知或场控（这是战术层的事）
- 评判哪个观点对错"""
```

**3.2 `src/llm/prompts.py` — 无需新增 builder**

战略家复用 `build_speak_prompt`，action instruction 中包含所有战略指令。

**3.3 `src/core/modes/salon.py` — 插入战略家决策步骤**

在 `execute_round` 中，Phase 1（意图收集）之前，新增战略家调用：

```python
def _strategist_decide(self, ctx: ModeContext, round_num: int) -> StrategyOutput | None:
    """战略家决策——在意图收集之前运行"""
    if not ctx.strategist:
        return None

    # 构建战略家 context
    strat_ctx = ctx.context_manager.build_context(
        ctx.strategist, ctx.memory, round_num, context_type="scribe"  # 复用 scribe 的 token 预算
    )

    # 准备输入材料
    analysis_text = self._format_round_analysis(ctx.last_round_analysis)
    dim_map_text = self._format_dimension_map(ctx)
    signal_summary = self._format_signal_summary(ctx)
    participants = [a.agent_id for a in ctx.participants]
    rounds_left = ctx.config.discussion.max_rounds - round_num

    return ctx.strategist.decide_strategy(
        strat_ctx, ctx.llm, analysis_text, dim_map_text,
        signal_summary, participants, rounds_left, ctx.config.language
    )
```

在 `execute_round` 的调用顺序：

```python
def execute_round(self, ctx: ModeContext) -> int:
    round_num = ctx.memory.advance_round()

    # 新增：战略家决策（stride 机制：默认每 2 轮运行一次）
    strategy = None
    if round_num == 1 or round_num % 2 == 0 or self._should_force_strategy(ctx):
        strategy = self._strategist_decide(ctx, round_num)
    if strategy:
        ctx.last_strategy = strategy

    # Phase 1: 意图收集（现有逻辑）
    intents = self._collect_intents(ctx, round_num)

    # Phase 2-6: 现有逻辑...
```

**3.4 `src/core/modes/salon.py` — ModeContext 增加字段**

```python
strategist: TopicStrategist | None = None
last_strategy: StrategyOutput | None = None
```

**3.5 `src/core/modes/salon.py` — setup 中创建战略家**

在 `setup()` 方法中，创建战略家实例：

```python
# 创建战略家
soul_path = config.souls.get("strategist", config.souls.get("moderator", ""))
if soul_path:
    ctx.strategist = TopicStrategist("strategist", soul_path, config)
```

需要在 `config/souls/` 下创建一个 `strategist.md` soul 文件，或者复用 moderator 的 soul。

### 验证方法

手动喂几组维度地图 + 论点数据，检查战略家的 `StrategyOutput` 是否合理。

---

## 阶段 4：维度地图初始化

### 改动文件

**4.1 `src/agents/strategist.py` — 新增初始化方法**

```python
class DimensionMapInit(BaseModel):
    """维度地图初始化输出"""
    dimensions: list[InitDimension]

class InitDimension(BaseModel):
    id: str
    label: str
    rationale: str
    depends_on: list[str] = []
    type: str = "core"  # "core" | "placeholder"

class TopicStrategist(BaseAgent):
    # ... 现有代码 ...

    def initialize_dimension_map(
        self, topic: str, llm: LLMClient, language: str = "zh"
    ) -> DimensionMapInit | None:
        action = f"""给定讨论话题：{topic}

请将这个话题拆解为 3-4 个最核心的讨论维度。

每个维度应该是：
1. 不同思想传统在这个话题上必然会碰撞的角度
2. 与其他维度有实质区别（不是同一个问题的不同措辞）
3. 如果缺少这个维度，讨论就是不完整的

不要试图穷举所有可能的维度。只需给出最核心的 3-4 个。
其余的维度空间留给参与者在对话中碰撞出来。

同时，请预留 1-2 个 emergent_placeholder（标注为 "placeholder"），
表示你认为还有维度尚未出现但你不确定是什么。

维度的类型参考（不限于此）：
- 定义与概念分析：核心概念的歧义和澄清
- 因果/机制：涉及的因果链条或运作机制
- 现象学/体验：在第一人称体验中是什么样的
- 跨文化/跨传统：不同思想传统如何处理这个问题
- 伦理/规范：涉及什么价值判断
- 实践/应用：在具体情境中如何落地
- 边界/反例：在什么情况下失效
- 元层面：讨论这个问题的方式本身有什么问题"""

        # 用一个最小 context 调用 LLM
        messages = [
            {"role": "system", "content": f"你是议题战略家。你的职责是为讨论话题设计维度地图。语言：{language}"},
            {"role": "user", "content": action}
        ]
        try:
            return llm.chat_structured(messages, DimensionMapInit)
        except Exception:
            return None
```

**4.2 `src/core/modes/salon.py` — setup 中初始化维度地图**

在 `setup()` 中，创建战略家后立即初始化维度地图：

```python
if ctx.strategist:
    dim_init = ctx.strategist.initialize_dimension_map(
        ctx.config.discussion.topic, ctx.llm, ctx.config.language
    )
    if dim_init:
        # 将初始化结果写入白板 dimension_map section
        import yaml
        dim_data = {
            "dimensions": [
                {"id": d.id, "label": d.label, "status": "blank" if d.type == "placeholder" else "pending",
                 "depth": 0, "notes": d.rationale, "type": d.type}
                for d in dim_init.dimensions
            ],
            "emergent": []
        }
        ctx.memory.whiteboard.update(
            "dimension_map", "rewrite",
            yaml.dump(dim_data, allow_unicode=True, default_flow_style=False),
            round_num=0, added_by="strategist"
        )
```

### 验证方法

用 3-5 个不同话题测试初始化，检查维度质量。

---

## 阶段 5：收敛检测 + Stride 机制

### 改动文件

**5.1 `src/agents/strategist.py` — 收敛信号**

在 `StrategyOutput` 中利用已有的 `convergence_response` 字段。收敛信号由两部分组成：

1. **简单代码信号**（在 salon.py 中计算）：
   - 维度锁定轮次（active 维度的 depth）
   - 距离上次新增维度的轮次

2. **LLM 判断**（在战略家 prompt 中）：
   - 记录员的 `convergence_hint`

**5.2 `src/core/modes/salon.py` — 收敛信号注入**

在 `_strategist_decide` 中，计算简单收敛信号并注入到 signal_summary：

```python
def _build_convergence_signals(self, ctx: ModeContext) -> str:
    """计算简单收敛信号"""
    signals = []
    dim_map = self._parse_dimension_map(ctx)

    if dim_map:
        active_dims = [d for d in dim_map["dimensions"] if d.get("status") == "active"]
        if len(active_dims) == 1:
            depth = active_dims[0].get("depth", 0)
            threshold = max(6, int(len(ctx.participants) * 1.5))
            if depth >= threshold:
                signals.append(f"⚠️ 维度锁定：'{active_dims[0]['label']}' 已连续讨论 {depth} 轮（阈值 {threshold}）")

        # 距离上次新增维度
        # （需要在 dimension_map 中记录 last_new_dimension_round）

    return "\n".join(signals) if signals else ""
```

**5.3 Stride 机制**

在 `execute_round` 中已有的 stride 逻辑基础上，增加强制触发条件：

```python
def _should_force_strategy(self, ctx: ModeContext) -> bool:
    """当信号系统检测到收敛时，强制触发战略家"""
    if not ctx.last_strategy:
        return False
    # 如果上一轮战略家输出了 convergence_response，强制运行
    return ctx.last_strategy.convergence_response is not None
```

### 验证方法

在已有会话数据上回测，检查收敛信号触发时机是否与人工判断一致。

---

## 阶段 6：战术调度改造

### 改动文件

**6.1 `src/core/scheduling_state.py` — 新增战略约束接口**

在 `post_process` 方法之前，新增一个方法接受战略约束：

```python
def apply_strategy_constraint(
    self,
    decision: AgendaDecision,
    strategy: StrategyOutput | None,
    all_intents: dict,
    participants: list,
) -> tuple[list[str], set[str]]:
    """
    将战略约束融入选人逻辑。

    返回：(final_speakers, forced_callouts)
    - final_speakers: 最终发言人列表
    - forced_callouts: 被强制点名的 agent ID 集合
    """
    if not strategy or not strategy.direction.preferred_agents:
        return decision.speakers, set()

    preferred = set(strategy.direction.preferred_agents)

    # 红线保护：沉默太久的 agent
    red_line = set()
    threshold = self.silence_threshold(len(participants), len(decision.speakers))
    for agent_id, silence_count in self.consecutive_silence.items():
        if silence_count >= threshold:
            red_line.add(agent_id)

    # 强制点名：preferred 中 energy=0 的 agent
    forced_callouts = set()
    for agent_id in preferred:
        if agent_id in all_intents:
            intent = all_intents[agent_id]
            # HandSignal.energy 是 "high"/"medium"/"low"
            if intent.energy == "low" and agent_id not in red_line:
                forced_callouts.add(agent_id)

    # 重新排序：红线 > preferred > 其他
    def sort_key(agent_id):
        if agent_id in red_line:
            return 0  # 最高优先级
        if agent_id in preferred:
            return 1
        return 2

    all_candidates = set(decision.speakers) | preferred | red_line
    ranked = sorted(all_candidates, key=sort_key)

    return ranked[:len(decision.speakers)], forced_callouts
```

**6.2 `src/core/modes/salon.py` — 注入锚定问题到发言 prompt**

在 `_serial_speak` 中，如果战略家有方向建议，注入到发言人的 prompt 中：

```python
def _build_strategy_injection(self, ctx: ModeContext, agent_id: str) -> str:
    """构建战略方向注入文本"""
    strategy = ctx.last_strategy
    if not strategy:
        return ""

    direction = strategy.direction
    injection = f"""
⚠️ 本轮发言方向约束：
我们正在探索「{direction.target_dimension}」这个维度。
你独特的视角能为这个维度提供什么别人看不到的东西？
具体回答：{direction.anchor_question}
用你自己的方式解析这个新维度，而不是把它翻译回你熟悉的话题。"""

    # 如果是强制点名的 agent
    if agent_id in getattr(ctx, '_forced_callouts', set()):
        injection += f"""

主持人直接向你提问：{direction.anchor_question}
请你必须回应这个问题。即使你这一轮没有主动举手，
主持人认为你的视角对这个方向至关重要。"""

    return injection
```

在 `_serial_speak` 中，将 injection 传递给发言人的 context：

```python
# 在构建 speak context 时，将 strategy injection 注入到 action_instruction 中
strategy_text = self._build_strategy_injection(ctx, agent.agent_id)
if strategy_text:
    # 在 round_info 中追加
    round_info = strategy_text + "\n\n" + round_info
```

**6.3 `src/core/modes/salon.py` — 改造 _post_process**

在现有 `_post_process` 中，调用新的 `apply_strategy_constraint`：

```python
def _post_process(self, ctx, round_num, decision, intents, raw, control):
    # 现有的 SchedulingState 更新逻辑...
    ctx.scheduling_state.update(raw, control, round_num,
                                set(decision.speakers),
                                {a.agent_id for a in ctx.participants})

    # 新增：战略约束
    if ctx.last_strategy:
        final_speakers, forced = ctx.scheduling_state.apply_strategy_constraint(
            decision, ctx.last_strategy, intents, ctx.participants
        )
        decision.speakers = final_speakers
        ctx._forced_callouts = forced

    # 现有的 post_process 逻辑...
    decision = ctx.scheduling_state.post_process(
        decision, ctx.participants, intents,
        len(ctx.participants) // 2 + 1
    )
```

### 验证方法

对比有/无战略约束时的发言人选择分布。

---

## 阶段 7：主持人瘦身（可选，最后执行）

### 改动文件

**7.1 `src/agents/moderator.py` — AgendaDecision 精简**

移除字段：
- `speaker_focus` → 被 `RoundAnalysis.arguments` 替代
- `phase` → 被维度地图状态推导
- `agenda_note` → 被 `DirectionGuidance` 替代
- `perception_summary` → 被信号系统替代

保留字段：
- `speakers` — 战术层仍需
- `notice` — 战术层仍需
- `reject_intents` — 战术层仍需
- `pending_question` — 可由战略家的 anchor_question 填充
- `emotional_temperature` — 保留
- `perceived_tension` — 保留

**7.2 主持人 prompt 精简**

移除与 speaker_focus、phase、agenda_note 相关的 prompt 指令。主持人只做：选人、发通知、拒绝意图。

**注意**：这个阶段是可选的。如果前面的阶段效果好，主持人仍然可以保留这些字段作为冗余信息——多一点信息不坏事。只有当主持人的 prompt 过长导致质量下降时，才需要瘦身。

### 验证方法

完整跑一次会话，对比精简前后的发言质量。

---

## 文件改动总览

| 文件 | 阶段 | 改动类型 |
|------|------|---------|
| `src/agents/scribe.py` | 1, 2 | 新增模型 + 方法 + 维度维护 |
| `src/core/modes/salon.py` | 1, 3, 4, 5, 6 | 插入分析/战略/调度步骤 |
| `config/default.yaml` | 2 | 新增 dimension_map section |
| `src/memory/whiteboard.py` | 2 | 标签映射 |
| `src/agents/strategist.py` | 3, 4 | **新建文件** |
| `src/core/scheduling_state.py` | 6 | 新增战略约束接口 |
| `src/agents/moderator.py` | 7 | 精简（可选） |

## 依赖关系

```
阶段 1（记录员升级）──独立──
  │
  ▼
阶段 2（维度地图）──依赖阶段 1 的 RoundAnalysis──
  │
  ▼
阶段 3（战略家）──依赖阶段 2 的维度地图──
  │
  ├──▶ 阶段 4（维度初始化）──依赖阶段 3 的战略家──
  │
  ├──▶ 阶段 5（收敛检测）──依赖阶段 3 的战略家──
  │
  ▼
阶段 6（战术改造）──依赖阶段 3 的战略家输出──
  │
  ▼
阶段 7（主持人瘦身）──依赖前面所有阶段──
```

## 实施顺序建议

1. 先完成阶段 1（记录员升级），验证 RoundAnalysis 质量
2. 然后阶段 2（维度地图），验证白板渲染
3. 然后阶段 3（战略家），这是核心，需要重点验证
4. 阶段 4 和 5 可以并行
5. 阶段 6 在阶段 3 验证通过后再做
6. 阶段 7 是可选的优化
