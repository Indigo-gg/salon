# 战略家升级方案：反坍缩与反滥调

## 问题诊断

### 两大核心病理

**1. 上下文重力坍缩（Contextual Gravity Collapse）**

大模型本质上是"预测下一个 Token"，注意力极易被最近几轮的高频词汇劫持。一旦讨论滑入微观层面（如"行政效率"），战略家的视野会被拽入微观旋涡，忘记初始的宏大主题。现有代码中，`decide_strategy()` 把 roadmap 放在 prompt 中间位置，但大模型对 prompt 开头的注意力权重远高于中间——锚点被淹没。

**2. 意识形态黑洞（Ideological Attractor）**

每个参与者有固定的认知滤镜（soul）。如果不施加干预，马克思主义者永远走向"阶级与资本"，存在主义者永远走向"虚无与选择"。现有的 `cot_template` 是统一的泛泛结构（"我之前说过...本轮我要推进新方向..."），无法阻止角色滑向各自的意识形态最低点。

### 现有机制的覆盖情况

| 问题 | 现有机制 | 差距 |
|------|---------|------|
| 战略家被带偏 | roadmap 在 prompt 中，phase hints | 无位置强化，无原初锚点 |
| 维度卡死 | `rounds_per_dim` 仅作为 LLM 提示 | 无代码级硬截断 |
| 角色废话循环 | 统一 `cot_template` | 无 per-agent 干预，无反滥调机制 |
| 锚定问题被敷衍 | `anchor_coverage` 检测 | 检测后无强制升级手段 |

---

## 目标架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    跨轮数据流                                     │
│                                                                 │
│  轮次 N 结束后:                                                  │
│                                                                 │
│  ① Scribe.analyze_round()                                       │
│     输出: RoundAnalysis                                          │
│          ├── arguments[] (per-agent 核心论点)                     │
│          ├── anchor_coverage (锚定问题回应质量)                    │
│          └── agent_profiles[] (新增: per-agent 概念使用画像)       │
│                                                                 │
│  ② Strategist.decide_strategy()                                 │
│     输入: agent_profiles[] (结构化 per-agent 数据)                │
│          + roadmap + round_analysis + anchor_coverage            │
│     输出: StrategyOutput                                         │
│          ├── 维度/锚点/CoT (现有)                                 │
│          ├── concept_bans[] (新增: 精准概念禁令)                   │
│          └── dimension_discipline (新增: 代码级维度纪律信号)        │
│                                                                 │
│  轮次 N+1 执行:                                                  │
│                                                                 │
│  ③ Salon._enforce_dimension_discipline()                        │
│     代码级硬规则: 轮次超时 → 强制切换维度                           │
│                                                                 │
│  ④ Salon._build_cot_for_speaker()                               │
│     per-agent CoT 组装: 统一战略信息 + 个性化 ban 指令             │
│                                                                 │
│  ⑤ Scribe 违禁词检测 (下一轮)                                    │
│     闭环: 检测违规 → 注入惩罚信号                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 升级一：原初锚点（Genesis Anchor）

### 问题

`strategist.py:350` 的 `decide_strategy()` prompt 中，roadmap 放在中间位置，容易被最近几轮的讨论内容淹没。

### 方案

调整 prompt 结构，将原初使命提到最前面，用强制格式包裹：

```python
# strategist.py decide_strategy() 中的 action 构建
action = f"""你是本次讨论的议题战略家。

【原初使命·不可偏离】：{self._roadmap.core_question}
【原始议题】：{self._roadmap.topic}

=== 当前状态 ===
轮次：{round_num} / {total_rounds}（剩余 {rounds_left} 轮）
当前维度：{current_dim_label}（已进行 {current_dim_rounds} 轮）

=== 记录员本轮分析 ===
{round_analysis_text}
{coverage_text}

...（后续策略决策指令不变）"""
```

### 改动范围

- `src/agents/strategist.py` — `decide_strategy()` 方法，调整 prompt 结构顺序

### 成本

零。仅调整 prompt 文本顺序，无新增逻辑。

---

## 升级二：代码级维度纪律（Dimension Discipline）

### 问题

战略家的 `should_switch` 完全由 LLM 判断，缺乏硬保障。`rounds_per_dim` 仅作为提示词，无代码强制执行。

### 方案

在 `salon.py` 中新增 `_enforce_dimension_discipline()` 方法，在战略家决策之后、意图收集之前运行。**意图层（战略家）只输出意图，执行层（salon mode）用代码兜底。**

```python
# salon.py 新增

class DimensionDiscipline:
    """维度纪律状态追踪"""
    def __init__(self, max_rounds_per_dim: int = 5):
        self.current_dim_id: str = ""
        self.dim_start_round: int = 0
        self.consecutive_ignore_count: int = 0
        self.max_rounds_per_dim: int = max_rounds_per_dim

    def check(self, strategy: StrategyOutput, round_num: int) -> tuple[bool, str]:
        """
        检查是否需要强制切换维度。

        Returns:
            (should_force_switch, reason)
        """
        dim_id = strategy.current_dimension_id

        # 维度变更：重置计数
        if dim_id != self.current_dim_id:
            self.current_dim_id = dim_id
            self.dim_start_round = round_num
            self.consecutive_ignore_count = 0

        dim_rounds = round_num - self.dim_start_round

        # 硬规则1：轮次超时
        if dim_rounds >= self.max_rounds_per_dim:
            return True, f"维度 '{strategy.current_dimension_label}' 已讨论 {dim_rounds} 轮，达到上限 {self.max_rounds_per_dim}"

        # 硬规则2：连续逃避
        coverage = strategy.anchor_coverage
        if coverage and coverage.quality in ("ignored", "token"):
            self.consecutive_ignore_count += 1
            if self.consecutive_ignore_count >= 2:
                return True, f"参与者连续 {self.consecutive_ignore_count} 轮无法实质性回应当前维度核心问题"
        else:
            self.consecutive_ignore_count = 0

        return False, ""

    def next_dimension(self, roadmap: DiscussionRoadmap) -> str | None:
        """从路线图中获取下一个未完成的维度 ID。"""
        if not roadmap:
            return None
        seq = roadmap.dimension_sequence
        try:
            idx = seq.index(self.current_dim_id)
            if idx + 1 < len(seq):
                return seq[idx + 1]
        except ValueError:
            pass
        return None
```

在 `salon.py` 的 `execute_round()` 中，战略家决策之后插入纪律检查：

```python
# execute_round() 中，strategy 决策之后
if strategy:
    ctx.last_strategy = strategy

# 新增：维度纪律检查（代码级兜底）
force_switch, switch_reason = self._dimension_discipline.check(strategy, round_num)
if force_switch:
    next_dim = self._dimension_discipline.next_dimension(ctx.strategist.roadmap)
    if next_dim:
        # 覆盖战略家的维度决策
        strategy.should_switch = True
        strategy.switch_reason = f"[代码强制] {switch_reason}"
        # 注意：不修改 strategy.current_dimension_id，由战略家在下一轮执行切换
        # 但通过 should_switch=True + switch_reason 强制提示
        logger.warning(f"[DimensionDiscipline] 强制切换: {switch_reason}")
```

### 配置

在 `config/default.yaml` 中新增：

```yaml
discussion:
  max_rounds_per_dimension: 5  # 每维度最大轮次，超过强制切换
```

### 改动范围

- `src/core/modes/salon.py` — 新增 `DimensionDiscipline` 类 + `execute_round()` 中插入检查
- `config/default.yaml` — 新增 `max_rounds_per_dimension` 配置项

### 成本

零 LLM 调用。纯代码逻辑，效果 100% 确定。

---

## 升级三：Per-Agent 概念追踪（Scribe 负责）

### 问题

战略家要做出精准的 per-agent ban 决策，需要知道"谁用了什么词，有没有新意"。当前 `RoundAnalysis` 只有 per-agent 的 `core_claim`，没有概念级别的追踪。

### 方案

在 `RoundAnalysis` 中新增 `AgentConceptProfile`，由 Scribe 在 `analyze_round()` 中一并生成。

#### 新增数据模型

```python
# scribe.py

class AgentConceptProfile(BaseModel):
    """某个 agent 在本轮的概念使用画像"""
    agent_id: str
    core_claim: str                          # 本轮核心论点（一句话）
    key_concepts_used: list[str]             # 使用的关键概念/词汇（2-3个）
    concept_novelty: dict[str, str]          # concept -> "new"|"refined"|"repeated"

class RoundAnalysis(BaseModel):
    # ... 现有字段不变
    agent_profiles: list[AgentConceptProfile] = Field(
        default_factory=list,
        description="各参与者本轮的概念使用画像，供战略家做 per-agent 决策"
    )
```

#### Scribe prompt 增量

在 `_build_analysis_action()` 中追加：

```
5. 对每个发言者，提取他们本轮使用的关键概念（2-3个具体词汇），
   并与前几轮对比判断新旧程度：
   - "new"：首次在讨论中使用
   - "refined"：之前用过，但本轮有新角度
   - "repeated"：之前用过，且论点高度相似
```

### 改动范围

- `src/agents/scribe.py` — 新增 `AgentConceptProfile` 模型，`RoundAnalysis` 新增字段，`_build_analysis_action()` 增量 prompt
- `src/core/modes/salon.py` — `_format_round_analysis()` 增加 agent_profiles 格式化

### 成本

Scribe 的 LLM 调用输出 schema 略微膨胀（每多一个 agent 增加约 50 tokens 输出）。无额外 LLM 调用。

---

## 升级四：精准概念禁令（Anti-Cliché）

### 核心设计原则

**禁止的不是"词"，而是"偷懒的表达路径"。**

| 场景 | 是否该禁 | 原因 |
|------|---------|------|
| 马克思用"阶级"第1次 | ❌ | 建立立场的必要表达 |
| 马克思用"阶级"第3次，但角度全新 | ❌ | 词汇重复但思想在推进 |
| 马克思用"阶级"第3次，论点和第1次几乎一样 | ✅ | 偷懒，需要逼他换路径 |
| 存在主义用"虚无"回应具体政策问题 | ✅ | 概念与场景不匹配 |

判断标准不是"用没用这个词"，而是**"用这个词有没有产生新洞见"**。这个判断基于 Scribe 的 `concept_novelty` 数据，由战略家决策。

### 新增数据模型

```python
# strategist.py

class ConceptBan(BaseModel):
    """一个精准的、有期限的概念禁令"""
    agent_id: str = Field(description="针对哪个参与者")
    banned_concepts: list[str] = Field(description="禁止使用的概念/词汇")
    reason: str = Field(description="为什么禁——注入给 agent 看，让他知道为什么被逼换路")
    ttl_rounds: int = Field(
        default=1,
        description="持续几轮（默认1轮，最多2轮）"
    )
    suggested_replacement: str = Field(
        description="建议的探索方向——不是禁完就完了，给一个指引"
    )

class StrategyOutput(BaseModel):
    # ... 现有字段不变
    concept_bans: list[ConceptBan] = Field(
        default_factory=list,
        description=(
            "针对特定参与者的概念禁令。仅在检测到重复偷懒时发出，讨论健康时留空。"
            "每轮最多发出 2 条禁令。ban 是手术刀，不是电锯。"
        )
    )
```

### 战略家 prompt 增量

在 `decide_strategy()` 的 action 中追加：

```
6. **概念禁令**（可选，仅在检测到偷懒时发出）：

   你将收到各角色上轮的概念使用画像（agent_profiles）。
   决策规则：
   - 如果某角色连续2轮使用同一关键词且 concept_novelty 为 "repeated"，
     你应该对它发出 ban
   - 如果某角色的关键词明显不适配当前讨论场景，
     你可以发出 ban
   - 如果讨论正在深化且各角色表达有新意，
     你不应发出任何 ban
   - 每次 ban 必须附带 suggested_replacement，指引探索方向
   - ban 的 ttl_rounds 默认为1，最多不超过2
   - 每轮最多发出 2 条 ban（宁可少发，不可乱发）

   ban 的目的不是惩罚，而是进化压力——逼迫角色用全新的路径表达灵魂。
```

### 输入格式化

将 Scribe 的 `agent_profiles` 以结构化表格呈现给战略家（而非让 LLM 从大段文本中提取）：

```python
# salon.py _strategist_decide() 中新增

def _format_agent_profiles(self, round_analysis) -> str:
    """将 agent_profiles 格式化为战略家可读的表格。"""
    if not round_analysis or not round_analysis.agent_profiles:
        return ""

    parts = ["=== 各参与者概念使用画像 ==="]
    parts.append("| 角色 | 核心论点 | 使用概念 | 新旧程度 |")
    parts.append("|------|----------|----------|----------|")

    for profile in round_analysis.agent_profiles:
        concepts_str = ", ".join(profile.key_concepts_used)
        novelty_parts = []
        for concept, novelty in profile.concept_novelty.items():
            label = {"new": "新", "refined": "深化", "repeated": "重复"}.get(novelty, novelty)
            novelty_parts.append(f"{concept}({label})")
        novelty_str = ", ".join(novelty_parts)
        parts.append(f"| {profile.agent_id} | {profile.core_claim[:30]}... | {concepts_str} | {novelty_str} |")

    return "\n".join(parts)
```

### 改动范围

- `src/agents/strategist.py` — 新增 `ConceptBan` 模型，`StrategyOutput` 新增字段，`decide_strategy()` prompt 增量
- `src/core/modes/salon.py` — `_strategist_decide()` 中新增 agent_profiles 传入，`_format_agent_profiles()` 新增

### 成本

战略家 LLM 调用的输出 schema 增加约 100-200 tokens（通常 0-2 条 ban）。输入增加约 200 tokens（agent_profiles 表格）。无额外 LLM 调用。

---

## 升级五：Per-Agent CoT 组装（代码层，非 LLM）

### 问题

当前 `_build_strategy_injection()` 对所有 speaker 注入相同的 `cot_template`。需要改为 per-agent 组装，将 ban 指令个性化注入。

### 方案

在 `salon.py` 中新增 `_build_cot_for_speaker()` 方法，由代码完成组装（不依赖 LLM）：

```python
def _build_cot_for_speaker(
    self,
    agent_id: str,
    strategy: StrategyOutput,
    agent_profile: AgentConceptProfile | None,
    is_forced: bool,
) -> str:
    """为特定 speaker 组装个性化的 CoT 注入。纯代码逻辑，无 LLM 调用。"""

    parts = []

    # 1. 统一的战略信息（所有人共享）
    parts.append(f"【当前维度】{strategy.current_dimension_label}")
    parts.append(f"【核心问题】{strategy.dimension_core_question}")
    parts.append(f"【锚定问题】{strategy.anchor_question}")

    # 2. 个性化的 ban 指令（仅对该 agent）
    agent_bans = [b for b in strategy.concept_bans if b.agent_id == agent_id]
    if agent_bans:
        ban = agent_bans[0]  # 一个 agent 同时最多一个活跃 ban
        parts.append(f"\n【概念限制】")
        parts.append(f"你过去几轮反复使用：{', '.join(ban.banned_concepts)}，论证已出现重复。")
        parts.append(f"本轮禁止使用上述概念。")
        parts.append(f"原因：{ban.reason}")
        parts.append(f"建议探索方向：{ban.suggested_replacement}")
        parts.append(f"""
如果你不能用那些词，思考：
- 我的核心观点用大白话怎么说？
- 我看到的具体场景中，最刺痛我的细节是什么？
- 上一位发言者的论点，我不能用老路子反驳，新的攻击角度是什么？""")

    # 3. 统一的 CoT 框架
    parts.append(f"\n{strategy.cot_template}")

    # 4. 强制点名注入
    if is_forced:
        parts.append(f"""
⚠️ 主持人直接向你提问：{strategy.anchor_question}
请你必须回应这个问题。即使你这一轮没有主动举手，
主持人认为你的视角对这个方向至关重要。""")

    return "\n".join(parts)
```

在 `_serial_speak()` 中调用：

```python
# _serial_speak() 中，构建 dynamic_round_info 时替换原有逻辑

for speaker in speakers:
    # ... 现有的暂停/终止检查 ...

    # 获取该 agent 的概念画像
    profile = None
    if ctx.last_round_analysis and ctx.last_round_analysis.agent_profiles:
        profile = next(
            (p for p in ctx.last_round_analysis.agent_profiles if p.agent_id == speaker.agent_id),
            None
        )

    # 个性化 CoT 组装
    is_forced = speaker.agent_id in getattr(ctx, '_forced_callouts', set())
    cot = self._build_cot_for_speaker(speaker.agent_id, ctx.last_strategy, profile, is_forced)

    # 组装最终 round_info
    dynamic_round_info = round_info
    if breathing_hints:
        dynamic_round_info = f"{dynamic_round_info}\n\n{breathing_hints}"
    if cot:
        dynamic_round_info = f"{cot}\n\n{dynamic_round_info}"

    # ... 现有的 speak 调用 ...
```

### 改动范围

- `src/core/modes/salon.py` — 新增 `_build_cot_for_speaker()`，修改 `_serial_speak()` 中的 CoT 注入逻辑，修改 `_build_strategy_injection()` 为委托调用

### 成本

零 LLM 调用。纯字符串拼接。

---

## 升级六：违禁词检测闭环（Scribe 负责）

### 问题

ban 只是"建议"，LLM 可能不遵守。需要检测违规并形成惩罚闭环。

### 方案

在 Scribe 的 `analyze_round()` 中增加违禁词检测，在下一轮注入惩罚信号。

#### RoundAnalysis 新增字段

```python
# scribe.py

class RoundAnalysis(BaseModel):
    # ... 现有字段
    ban_violations: list[str] = Field(
        default_factory=list,
        description="检测到的违禁词使用实例，格式: 'agent_id: concept'"
    )
```

#### Scribe prompt 增量

在 `_build_analysis_action()` 中追加：

```
6. 如果上一轮有概念禁令（concept_bans），检查本轮发言是否有人违反。
   如果违反，记录到 ban_violations 中，格式为 "agent_id: 违禁概念"。
```

#### 惩罚信号注入

在 `_serial_speak()` 的 CoT 组装中，如果上一轮有违禁词记录，追加惩罚提示：

```python
def _build_cot_for_speaker(self, agent_id, strategy, agent_profile, is_forced, ban_violations=None):
    # ... 现有逻辑 ...

    # 违禁词惩罚（仅对该 agent）
    if ban_violations:
        agent_violations = [v.split(": ")[1] for v in ban_violations if v.startswith(agent_id)]
        if agent_violations:
            parts.append(f"""
⚠️ 违禁警告：上轮检测到你使用了被限制的概念：{', '.join(agent_violations)}。
本轮必须用完全不同的表述路径，否则你的发言将被认为缺乏新意。""")

    return "\n".join(parts)
```

### 改动范围

- `src/agents/scribe.py` — `RoundAnalysis` 新增 `ban_violations` 字段，`_build_analysis_action()` 增量 prompt
- `src/core/modes/salon.py` — `_build_cot_for_speaker()` 增加违禁词惩罚注入

### 成本

Scribe 输出增加约 50 tokens。无额外 LLM 调用。

---

## 升级七：Ban 生命周期管理

### 问题

Ban 需要自动过期，不能永久生效。

### 方案

在 `salon.py` 的 `DimensionDiscipline` 中增加 ban 生命周期追踪：

```python
class DimensionDiscipline:
    def __init__(self, max_rounds_per_dim: int = 5):
        # ... 现有字段 ...
        self.active_bans: dict[str, ConceptBan] = {}  # agent_id -> ban
        self.ban_history: list[dict] = []  # 历史记录，供分析

    def register_bans(self, bans: list[ConceptBan], round_num: int) -> None:
        """注册新的 ban，覆盖该 agent 的旧 ban。"""
        for ban in bans:
            self.active_bans[ban.agent_id] = ban
            self.ban_history.append({
                "agent_id": ban.agent_id,
                "concepts": ban.banned_concepts,
                "round": round_num,
                "ttl": ban.ttl_rounds,
            })

    def tick_bans(self) -> None:
        """每轮结束时调用，将所有 active ban 的 ttl 减 1，过期的移除。"""
        expired = []
        for agent_id, ban in self.active_bans.items():
            ban.ttl_rounds -= 1
            if ban.ttl_rounds <= 0:
                expired.append(agent_id)
        for agent_id in expired:
            del self.active_bans[agent_id]

    def get_active_bans(self) -> list[ConceptBan]:
        """获取当前所有活跃的 ban。"""
        return list(self.active_bans.values())
```

在 `execute_round()` 的末尾（发言结束后）调用 `tick_bans()`。

### 改动范围

- `src/core/modes/salon.py` — `DimensionDiscipline` 新增 ban 管理方法，`execute_round()` 末尾调用 `tick_bans()`

### 成本

零。纯状态管理。

---

## 完整的 execute_round 流程（升级后）

```python
def execute_round(self, ctx: ModeContext) -> int:
    round_num = ctx.round_num + 1
    ctx.round_num = round_num
    ctx.session_manager.increment_round()

    round_info = self._get_round_info(ctx, round_num)

    # --- Phase 0: 战略家决策 ---
    strategy = None
    if ctx.strategist and (round_num == 1 or round_num % 2 == 0 or self._should_force_strategy(ctx)):
        strategy = self._strategist_decide(ctx, round_num)  # 增量: 传入 agent_profiles
    if strategy:
        ctx.last_strategy = strategy

    # --- Phase 0.5: 维度纪律检查（新增） ---
    force_switch, switch_reason = self._dimension_discipline.check(strategy, round_num)
    if force_switch:
        strategy.should_switch = True
        strategy.switch_reason = f"[代码强制] {switch_reason}"
        logger.warning(f"[DimensionDiscipline] 强制切换: {switch_reason}")

    # --- Phase 0.6: 注册 ban（新增） ---
    if strategy and strategy.concept_bans:
        self._dimension_discipline.register_bans(strategy.concept_bans, round_num)

    # --- Phase 1: 并发收集意图 ---
    intents = self._collect_intents(ctx, round_num, round_info)

    # --- Phase 2: 信号计算 ---
    signals, raw_signals, control = self._compute_signals(ctx, round_num, intents)

    # --- Phase 3: 主持人决策 ---
    decision = self._moderator_decide(ctx, round_num, intents, signals=signals)

    # --- Phase 4: 调度防线后处理 ---
    decision = self._post_process(ctx, round_num, decision, raw_signals, control, signals, intents=intents)

    # --- Phase 5: 记录决策 + emit ---
    self._emit_decision(ctx, round_num, decision, intents, signals)

    # --- Phase 6: 串行发言（per-agent CoT） ---
    self._serial_speak(ctx, round_num, round_info, decision, intents)

    # --- Phase 6.5: ban 生命周期 tick（新增） ---
    self._dimension_discipline.tick_bans()

    return round_num
```

---

## 文件改动总览

| 文件 | 改动 | 升级项 | 类型 |
|------|------|--------|------|
| `src/agents/strategist.py` | prompt 结构调整 + `ConceptBan` 模型 + prompt 增量 | 一、四 | 模型 + prompt |
| `src/agents/scribe.py` | `AgentConceptProfile` 模型 + `ban_violations` 字段 + prompt 增量 | 三、六 | 模型 + prompt |
| `src/core/modes/salon.py` | `DimensionDiscipline` 类 + `_build_cot_for_speaker()` + `_format_agent_profiles()` + 流程改造 | 二、五、七 | 新增方法 + 流程 |
| `config/default.yaml` | `max_rounds_per_dimension` 配置项 | 二 | 配置 |

## 改动分层

```
纯代码层（零 LLM 成本，100% 确定）:
  ├── 升级二: 维度纪律硬规则
  ├── 升级五: per-agent CoT 组装
  └── 升级七: ban 生命周期管理

LLM 增量层（低成本，schema 微调）:
  ├── 升级一: prompt 结构调整（零成本）
  ├── 升级三: Scribe 概念追踪（+50 tokens 输出/agent）
  ├── 升级四: 战略家 concept_bans（+100-200 tokens 输出）
  └── 升级六: 违禁词检测（+50 tokens 输出）
```

## 依赖关系

```
升级一（原初锚点）──独立，可立即实施──

升级二（维度纪律）──独立，可立即实施──

升级三（概念追踪）──独立，可立即实施──
  │
  ▼
升级四（概念禁令）──依赖升级三的 agent_profiles 数据──
  │
  ├──▶ 升级五（per-agent CoT）──依赖升级四的 concept_bans──
  │
  └──▶ 升级六（违禁词检测）──依赖升级四的 concept_bans──
         │
         ▼
       升级七（ban 生命周期）──依赖升级四的 ConceptBan 模型──
```

## 实施顺序建议

1. **第一批（可并行）**：升级一 + 升级二 + 升级三 → 三个独立改动，无依赖
2. **第二批**：升级四 → 依赖升级三的 agent_profiles
3. **第三批（可并行）**：升级五 + 升级六 + 升级七 → 依赖升级四

## 验证方法

| 升级项 | 验证方式 | 成功标准 |
|--------|---------|---------|
| 一：原初锚点 | 对比 prompt 结构调整前后的战略家维度偏离率 | 维度偏离率下降 > 30% |
| 二：维度纪律 | 检查日志中 [DimensionDiscipline] 标记 | 超时强制切换 100% 生效 |
| 三：概念追踪 | 人工抽检 agent_profiles 的 concept_novelty 准确率 | 准确率 > 70% |
| 四：概念禁令 | 检查 concept_bans 发出频率和合理性 | 讨论健康时不发，偷懒时发出率 > 80% |
| 五：per-agent CoT | 对比统一 CoT vs 个性化 CoT 的发言多样性 | 概念重复率下降 > 20% |
| 六：违禁词检测 | 人工验证 ban_violations 的准确性 | 误报率 < 20% |
| 七：ban 生命周期 | 检查 ban 是否在 ttl 到期后自动移除 | 100% 自动过期 |

## 风险与降级方案

| 风险 | 影响 | 应对 | 降级 |
|------|------|------|------|
| 战略家 ban 决策不稳定 | 误 ban 导致 agent 无法表达核心观点 | ttl 最多 2 轮自动过期 + 每轮最多 2 条 ban | 回退到统一 CoT，无 ban |
| agent_profiles 概念追踪不准 | 战略家基于错误数据做 ban 决策 | Scribe prompt 中增加 few-shot 示例 | 降级为仅追踪 core_claim，不做概念级追踪 |
| 违禁词误报 | agent 被错误惩罚 | ban_violations 需要人工抽检 | 移除惩罚注入，仅保留 ban 指令 |
| 维度过早强制切换 | 打断深入讨论 | `max_rounds_per_dimension` 默认值设为 5（较宽松） | 调大阈值或禁用硬规则 |
| per-agent CoT 过长 | 超出 token 预算 | ban 指令控制在 100 字以内 | 移除 ban 相关的额外思考步骤 |
