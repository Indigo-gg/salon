# 主持人重构方案：从全栈调度到议题战略

## 问题诊断

### 当前架构的核心问题

主持人（ModeratorAgent）每轮在一个 LLM 调用中同时承担四层职责：

```
诊断（理解论点）→ 策略（决定方向）→ 战术（发通知）→ 调度（选人发言）
```

这导致**宏观视野被微观决策淹没**。主持人把注意力花在"谁发言比较平衡"、"要不要发个通知"上，真正重要的"讨论还剩哪些维度没覆盖"只体现为一句话的 `agenda_note`。

### 角色引力场问题

每个参与者有固定的认知滤镜（soul），导致不管讨论什么话题，对话都会沿着角色之间的固定矛盾轴滑落，最终收敛到相似的结论（如"集体行动是最终解法"）。这不是 bug——角色滤镜是张力的来源——但需要外力引导张力在更多维度上展开，防止过早收敛。

### 设计原则

1. **LLM 做语义判断，代码做机械操作**——不硬编码矛盾轴映射、比喻饱和度等语义计算
2. **分步验证**——每个阶段独立可测试，不依赖后续阶段
3. **渐进式重构**——不推翻现有架构，在现有管道上叠加新层
4. **记录员升级为分析引擎**——利用已有的白板维护能力，扩展为结构化论点提取

---

## 目标架构

```
┌──────────────────────────────────────────────────────────┐
│                    跨轮执行流程                             │
│                                                          │
│  轮次 N 结束后（或轮次 N+1 开始前）：                        │
│                                                          │
│  ① 记录员分析（新增）                                      │
│     输入：轮次 N 的已完成发言                               │
│     输出：RoundAnalysis（结构化论点 + 收敛提示）             │
│                                                          │
│  ② 战略家决策（新增）                                      │
│     输入：RoundAnalysis + 维度地图 + 防御性信号             │
│     输出：StrategyOutput（维度方向 + 锚定问题 + 选人建议）   │
│                                                          │
│  轮次 N+1 执行：                                          │
│                                                          │
│  ③ 意图收集（已有，参与者看到锚定问题后生成意图）             │
│     所有参与者并发提交 HandSignal                           │
│                                                          │
│  ④ 信号计算（已有，不变）                                   │
│     信号系统计算 RawSignals → ControlSignals               │
│                                                          │
│  ⑤ 战术调度（改造，融合战略约束）                            │
│     硬规则 + Shortlist 候选池过滤 → 选人 + prompt 注入      │
│                                                          │
│  ⑥ 发言执行（已有，不变）                                   │
│     选中的参与者逐个发言                                    │
│                                                          │
│  ⑦ 白板更新（已有，不变）                                   │
│     记录员同步白板（已有机制）                               │
└──────────────────────────────────────────────────────────┘

时序要点：
- 记录员分析的是轮次 N 的**已完成发言**，不是意图信号
- 战略家的锚定问题在轮次 N+1 意图收集**之前**就已确定
- 参与者在生成意图时就能看到锚定问题，影响他们的举手方向
- 记录员分析和战略家决策可以合并为一次 LLM 调用（见 stride 机制）

Stride 机制（成本优化）：
- 默认 stride=2：每 2 轮才运行一次记录员+战略家
- 但当信号系统检测到收敛信号（novelty_score 持续走低）时，强制触发额外运行
- 在 stride 跳过的轮次中，沿用上一轮的战略家输出（anchor_question 和 shortlist 不变）
- **上下文对齐**：当 stride > 1 时，记录员读取过去 stride 轮的所有发言（而非只读最近 1 轮），避免遗漏

Token 预算控制：
- 维度地图硬上限 9 个维度（YAML，约 500-800 tokens）
- RoundAnalysis 每轮只保留最新一份（约 300-500 tokens），不累积
- 历史论点已被白板的 consensus/disagreements 概括，不需要保留原始 RoundAnalysis
- 总增量约 1000-1300 tokens，在 12K context budget 中占比约 10%

### 职责拆分

| 层 | 角色 | 做什么 | 不做什么 |
|---|------|-------|---------|
| 记录员 | 分析器 | 每轮提取论点、标记维度、检测简单收敛信号 | 不做方向决策 |
| 战略家 | 地图操作者 | 维度覆盖率管理、方向决策、维度切换指令 | 不选人、不发通知 |
| 信号系统 | 防御检测 | 可读性、能量、新颖性等信号（已有） | 不做战略判断 |
| 硬规则 | 安全网 | 沉默保护、强制收尾（已有） | 不理解语义 |
| 战术调度 | 执行层 | 融合战略约束后选人、注入 prompt | 不做宏观判断 |

---

## 实施阶段

### 阶段 0：准备工作（无代码改动）

**目标**：确认当前系统可运行，建立基线。

- [ ] 运行一次完整会话，记录：轮次数、发言分布、白板最终状态、讨论是否落入"集体行动"轨道
- [ ] 保存会话数据作为 baseline 对照

**验收**：有一份可复现的 baseline 会话记录。

---

### 阶段 1：记录员升级——每轮结构化分析

**目标**：记录员从"低频白板维护者"升级为"每轮论点分析器"。

**改动范围**：
- `src/agents/scribe.py` — 新增 `analyze_round()` 方法
- `src/core/modes/salon.py` — 在 Phase 2（信号计算）和 Phase 3（主持人决策）之间插入记录员分析步骤
- `src/llm/prompts.py` — 新增 `build_round_analysis_prompt()`

**数据结构**：

```python
class RoundAnalysis(BaseModel):
    """记录员每轮输出的结构化分析"""
    arguments: list[ArgumentSummary]         # 每个发言者的核心论点
    new_angles: list[str]                    # 本轮出现的新讨论角度（不在已知维度中的）
    covered_dimensions: list[CoveredDimension]  # 本轮触及了已知维度中的哪些（附证据）
    convergence_hint: str                    # 一句话：当前讨论是否有收敛趋势，为什么

class ArgumentSummary(BaseModel):
    agent_id: str
    core_claim: str          # 一句话核心主张
    key_metaphor: str | None # 本轮引入的关键比喻（如有）
    responds_to: str | None  # 回应了谁的什么观点

class CoveredDimension(BaseModel):
    id: str                  # 维度 ID
    confidence: str          # "high" 或 "low"
    evidence: str            # 触发该维度的发言原句摘要或关键词
```

**关键设计**：

1. `RoundAnalysis` 不做方向决策，只做事实提取。收敛判断是"提示"（hint），不是指令。
2. 记录员每轮都运行分析，但白板同步仍按原有频率（每 N 轮或超长时触发）。分析和白板同步解耦。
3. `new_angles` 字段是"涌现维度"的捕获点——如果记录员发现某个发言引入了全新的讨论角度，标记在这里。后续阶段由战略家决定是否纳入维度地图。
4. **去重约束**：记录员的 prompt 中明确要求——"如果你发现的新角度与已知维度中的任何一个实质相同（只是措辞不同），不要标记为 new_angle，而是标记为对应维度的 covered"。

**prompt 设计要点**：

```
你是本轮的记录员。请阅读本轮所有发言，输出结构化分析。

你需要做：
1. 提取每个发言者的核心主张（一句话）
2. 标记本轮是否引入了新的讨论角度（不在以下已知维度列表中的）
3. 标记本轮触及了以下已知维度中的哪些
4. 一句话判断：当前讨论是否有收敛到某个狭窄方向的趋势

你不需要做：
- 判断讨论应该往哪个方向走
- 评判哪个观点更好
- 提出新的讨论问题
```

**验证方法**：
- 跑 2-3 次会话，检查 `RoundAnalysis` 的质量
- 重点验证：`core_claim` 是否准确？`new_angles` 是否能捕获到涌现的维度？`convergence_hint` 是否与人工判断一致？

**验收**：记录员的 `RoundAnalysis` 输出稳定可用，`core_claim` 准确率 > 80%（人工抽检）。

---

### 阶段 2：维度地图——白板升级

**目标**：在白板中增加 `dimension_map` 区域，作为讨论的"空间结构"视图。

**改动范围**：
- `src/memory/whiteboard.py` — 新增 `dimension_map` section
- `src/agents/scribe.py` — `sync_whiteboard` 增加维度地图维护逻辑
- `src/core/context_manager.py` — 确保战略家能看到完整的维度地图

**数据结构**：

```python
# 白板中的 dimension_map section 内容格式（YAML 字符串，由记录员维护）
"""
dimensions:
  - id: definition
    label: "无我的定义与概念分析"
    status: covered        # covered / active / pending / blank / archived
    depth: 3               # 被讨论的轮次数
    last_round: 4
    notes: "无我是否定实体还是否定主体——已达成基本共识"

  - id: mechanism
    label: "执着自我为什么产生痛苦"
    status: covered
    depth: 2
    last_round: 6
    notes: "达文的增益调节模型提供了神经科学解释"

  - id: boundary
    label: "无我的实践边界"
    status: active
    depth: 4
    last_round: 10
    notes: "止痛药vs治病、清醒接受vs有效反抗"

  - id: cross_cultural
    label: "跨文化比较"
    status: blank           # 完全没有讨论
    depth: 0

  - id: phenomenology
    label: "无我体验的现象学"
    status: blank
    depth: 0

emergent: []               # 记录员发现的新角度，等待战略家评估
"""
```

**维度从哪来？**

不是每轮重新生成。维度列表在讨论开始时由战略家初始化（见阶段 3，留白机制：3-4 核心 + 2-3 placeholder），之后由记录员在 `sync_whiteboard` 时维护状态更新（标记哪些被覆盖了、深度多少）。如果记录员发现了新角度，写入 `emergent` 列表，战略家在下一轮决定是否纳入。

**维度数量硬上限**：维度地图中的维度总数不超过 9 个（含 placeholder）。如果需要新增维度且已达到上限，必须先将一个已标记为 `covered` 的维度归档为 `archived`。这迫使战略家做取舍，防止维度膨胀。

**维度地图 vs 现有白板概念的关系**：

| 现有概念 | 在新架构中的角色 |
|---------|---------------|
| `current_focus` | 保留，标记当前轮的焦点问题 |
| `consensus` | 保留，是维度覆盖的"成果" |
| `disagreements` | 保留，是维度内部的"张力" |
| `backlog` | 被 `dimension_map.status=blank` 替代 |
| `surprises` | 保留，是涌现信号的另一种形式 |
| `agenda_trace` | 被战略家的决策记录替代 |
| `active_concepts` | 保留，服务于信号系统的新颖性检测 |

维度地图不是替换白板，而是**给白板加一个空间视图**。现有概念继续为信号系统和发言人的 prompt 服务。

**验证方法**：
- 手动构造几份维度地图（基于之前的会话数据），检查它是否能清晰反映讨论的覆盖情况
- 检查记录员能否在 `sync_whiteboard` 时正确更新维度状态

**验收**：维度地图能准确反映讨论的空间覆盖率，记录员能正确维护状态。

---

### 阶段 3：战略家——核心新组件

**目标**：引入议题战略家，替代当前主持人的策略职责。

**改动范围**：
- `src/agents/moderator.py` — 新增 `TopicStrategist` 类（或重命名/拆分现有 `ModeratorAgent`）
- `src/core/modes/salon.py` — 在记录员分析之后、战术调度之前插入战略家决策步骤
- `src/llm/prompts.py` — 新增 `build_strategist_prompt()`

**数据结构**：

```python
class StrategyOutput(BaseModel):
    """战略家每轮输出"""
    map_update: MapUpdate              # 维度地图更新指令
    direction: DirectionGuidance       # 本轮方向建议
    convergence_response: str | None   # 如果检测到收敛，如何应对

class MapUpdate(BaseModel):
    """维度地图更新"""
    mark_covered: list[str]            # 标记哪些维度本轮被覆盖了
    mark_active: list[str]             # 标记哪些维度正在被讨论
    add_dimension: list[NewDimension]  # 纳入新维度（来自记录员的 emergent 或战略家自己发现）
    depth_increment: list[str]         # 哪些维度的深度 +1

class NewDimension(BaseModel):
    id: str
    label: str
    rationale: str  # 为什么这个维度值得讨论

class DirectionGuidance(BaseModel):
    target_dimension: str              # 下一步建议探索的维度 ID
    reason: str                        # 为什么选这个维度
    anchor_question: str               # 锚定问题，注入到发言人的 prompt 中
    preferred_agents: list[str]        # 最适合展开这个维度的参与者（软引导，非硬限制）
```

**战略家看到什么？**

```
输入材料：
1. 话题定义
2. 记录员的 RoundAnalysis（本轮结构化论点）
3. 维度地图（完整状态）
4. 防御性信号摘要（从信号系统，简化为文字：可读性、能量、新颖性）
5. 战略家上一轮的 direction（反馈循环）
6. 讨论剩余轮次

不看什么：
- 原始发言全文（太长，由记录员压缩）
- 参与者的意图信号（这是战术层的事）
- 每个参与者的 soul 细节（战略家关注维度，不关注角色性格）
```

**战略家的 prompt 设计要点**：

```
你是本次讨论的议题战略家。你的职责是管理讨论的维度空间，防止讨论过早收敛。

你将收到：
- 当前的维度地图（哪些维度已覆盖、哪些空白、哪些正在讨论）
- 记录员本轮的结构化分析（核心论点、新角度、收敛提示）
- 防御性信号（可读性、能量、新颖性）

你需要做：
1. 更新维度地图（标记本轮覆盖了什么、是否发现新维度）
2. 判断下一步应该探索哪个维度
3. 如果发现讨论正在收敛到某个狭窄方向，提出维度切换

维度切换的原则：
- 不要打断正在深入且有产出的讨论
- 当讨论在同一维度上连续 3 轮以上没有新的子问题或比喻时，考虑切换
- 切换时选择与当前维度"正交"的方向——即不会被角色的自然反应自动覆盖的维度
- 切换不是断裂，要给出桥接问题，让新旧维度产生连接

你不做：
- 选谁发言（这是战术层的事）
- 发通知或场控（这是战术层的事）
- 评判哪个观点对错
```

**战略约束如何注入战术层？**

使用 **Shortlist 候选池过滤**机制（详见风险 D 的说明），而非加减分：

```python
def apply_strategy_shortlist(strategy, all_intents, hard_rules):
    """
    战略约束通过优先级排序实现（非硬删除）。

    流程：
    1. 硬规则检查红线（沉默保护等），生成 red_line_agents
    2. 全员进入候选池（无人被排除）
    3. preferred_agents 获得优先级提升
    4. 在候选池内用"信号评分 + 战略优先级"排序选人
    5. 如果 preferred_agents 中有人 energy=0，强制点名

    设计原则：没有 avoid_agents。战略家只指定"谁更适合"，
    不指定"谁不适合"。不在 preferred_agents 里的人不被删除，
    只是优先级较低。如果全场没人想说话，他们仍然会被选中。
    """
    red_line_agents = hard_rules.get_red_line_agents()

    # 全员进入候选池（无人被硬删除）
    all_candidates = set(all_intents.keys())

    # 有意图的候选人
    candidates_with_intent = set(
        aid for aid, signal in all_intents.items()
        if signal.energy > 0
    )

    # 强制点名：preferred_agents 中 energy=0 的人
    preferred = set(strategy.direction.preferred_agents) if strategy.direction.preferred_agents else set()
    forced_callouts = preferred - candidates_with_intent

    # 最终候选池 = 全员（红线保护的优先级最高）
    final_pool = all_candidates

    # 计算综合评分：信号评分 + 战略优先级加成
    scores = {}
    for aid in final_pool:
        base_score = compute_signal_score(aid)
        # preferred_agents 获得优先级提升（乘数而非加数）
        if aid in preferred:
            base_score *= STRATEGY_MULTIPLIER  # 如 1.5x
        # 红线保护的 agent 获得最高优先级
        if aid in red_line_agents:
            base_score = float('inf')  # 永远排在最前
        scores[aid] = base_score

    ranked = sorted(scores, key=scores.get, reverse=True)

    return ranked, forced_callouts
```

强制点名的 prompt 注入：
```
对被强制点名的 agent，在其 speak prompt 中加入：
主持人直接向你提问：{anchor_question}
请你必须回应这个问题。即使你这一轮没有主动举手，
主持人认为你的视角对这个方向至关重要。
```

**锚定问题如何注入发言人的 prompt？**

锚定问题不放在 `round_info` 末尾，而是作为 speak prompt 中的**独立高优先级段落**，紧接在 soul 之后、发言指令之前。同时附带维度约束：

```
在 speak prompt 中的位置：

[System: agent soul + behavior rules]
[User: ...]
  ← 锚定问题和维度约束放在这里，在 soul 之后、发言指令之前
  ⚠️ 本轮发言方向约束：
  我们正在探索「{target_dimension}」这个维度。
  你独特的视角能为这个维度提供什么别人看不到的东西？
  具体回答：{anchor_question}
  注意：请不要重复你之前关于「{avoid_dimension}」的论述。
  用你自己的方式解析这个新维度，而不是把它翻译回你熟悉的话题。
  ← 以下是正常的发言指令和上下文
```

位置决定注意力权重——放在 soul 之后意味着 LLM 在生成发言时会先读到 soul（建立角色），然后立刻读到维度约束（建立方向），最后才是发言指令。这比放在末尾的 round_info 中被忽略的概率低得多。

**验证方法**：
- 手动给战略家喂几组不同的维度地图 + 论点数据，检查它的方向决策是否合理
- 特别验证：当讨论收敛时，战略家是否能识别并提出有效的维度切换
- 对比：有战略家 vs 无战略家的会话，讨论的维度覆盖率是否显著不同

**验收**：战略家的方向决策在 10 组测试场景中，7 组以上与人工判断一致（人工判断"这个方向比继续当前方向更好"）。

---

### 阶段 4：维度地图初始化

**目标**：给定一个话题，自动生成初始维度地图。

**改动范围**：
- `src/agents/moderator.py` — 新增 `initialize_dimension_map()` 方法
- `src/core/modes/salon.py` — 在 `setup()` 中调用初始化

**初始化 prompt**：

```
给定讨论话题：{topic}

请将这个话题拆解为 3-4 个最核心的讨论维度。

每个维度应该是：
1. 不同思想传统在这个话题上必然会碰撞的角度
2. 与其他维度有实质区别（不是同一个问题的不同措辞）
3. 如果缺少这个维度，讨论就是不完整的

不要试图穷举所有可能的维度。只需给出最核心的 3-4 个。
其余的维度空间留给参与者在对话中碰撞出来。

维度的类型参考（不限于此）：
- 定义与概念分析：核心概念的歧义和澄清
- 因果/机制：涉及的因果链条或运作机制
- 现象学/体验：在第一人称体验中是什么样的
- 跨文化/跨传统：不同思想传统如何处理这个问题
- 伦理/规范：涉及什么价值判断
- 实践/应用：在具体情境中如何落地
- 边界/反例：在什么情况下失效
- 元层面：讨论这个问题的方式本身有什么问题

同时，请预留 2-3 个 emergent_placeholder，标注为"待涌现"，
表示你认为还有维度尚未出现但你不确定是什么。
在 rationale 中说明为什么你认为还有未预见的维度。

输出格式：
- id: 简短标识
- label: 一句话描述这个维度
- rationale: 为什么这个维度值得讨论（与话题核心的关联）
- depends_on: 这个维度的有效讨论需要先覆盖哪些其他维度（可为空）
- type: "core" | "placeholder"
```

**验证方法**：
- 用 3-5 个不同话题测试初始化，检查维度质量
- 重点：维度之间是否有足够的区分度？是否覆盖了话题的主要面向？

**验收**：生成的维度地图在人工评审中被认为"合理且有区分度"的比例 > 70%。

---

### 阶段 5：收敛检测——简化方案

**目标**：当讨论陷入维度低谷时，给战略家一个明确的提示。

**设计原则**：不用复杂的硬编码信号，用简单的计数 + LLM 判断。

**改动范围**：
- `src/agents/scribe.py` — `RoundAnalysis` 的 `convergence_hint` 已有，强化其内容
- `src/agents/moderator.py` — 战略家的 prompt 中增加收敛检测指令

**简单的代码信号**（不涉及语义计算）：

```python
def simple_convergence_signals(dimension_map, recent_rounds):
    """只做最简单的计数，不做语义判断"""
    signals = {}

    # 信号 1：维度锁定轮次
    # 阈值与参与者数量挂钩：确保每个参与者至少有机会在该维度上发言 1-1.5 次
    # 4 人时为 6，5 人时为 8，6 人时为 9
    lock_threshold = max(6, int(len(participants) * 1.5))
    active_dims = [d for d in dimension_map.dimensions if d.status == "active"]
    if len(active_dims) == 1 and active_dims[0].depth >= lock_threshold:
        signals["dimension_lock"] = active_dims[0].id
        signals["lock_depth"] = active_dims[0].depth

    # 信号 2：最近 N 轮没有新增维度
    if dimension_map.last_new_dimension_round is not None:
        rounds_since_new = current_round - dimension_map.last_new_dimension_round
        if rounds_since_new >= 4:
            signals["stale_map"] = rounds_since_new

    # 信号 3：记录员的 convergence_hint（由 LLM 生成，不是硬编码）
    # 这个在 RoundAnalysis 中已经存在

    return signals
```

**关键**：这些信号只是**提示**，不是决策。决策完全由战略家的 LLM 判断。

```
战略家 prompt 中增加：

⚠️ 收敛检测提示：
- 当前活跃维度 "{active_dim}" 已连续讨论 {lock_depth} 轮
- 距离上次新增维度已过 {stale_map} 轮
- 记录员判断：{convergence_hint}

如果你认为讨论仍在产出新的子问题和洞见，可以继续深入。
如果你认为讨论已陷入重复，建议切换维度。
```

**验证方法**：
- 在已有会话数据上回测：这些简单信号是否能在"讨论明显陷入重复"时触发？
- 对比信号触发时机与人工判断的"应该切换了"时刻

**验收**：信号触发时机与人工判断的偏差不超过 2 轮。

---

### 阶段 6：战术调度改造

**目标**：将战略约束融入现有的战术调度管道。

**改动范围**：
- `src/core/modes/salon.py` — `_post_process` 方法中增加战略约束叠加
- `src/llm/prompts.py` — `build_speak_prompt` 中增加战略方向注入

**改动内容**：

1. 将 `SchedulingState.post_process()` 的选人逻辑改为优先级排序模式：全员进入候选池（无人被硬删除），preferred_agents 获得乘数优先级提升（如 1.5x），红线保护的 agent 永远排最前
2. 增加强制点名机制：如果 preferred_agents 中有人 energy=0，仍然选中该 agent，但给其 prompt 中加入"主持人直接点名问你"
3. 将 `anchor_question` + `dimension_constraint` 注入到选中发言人的 speak prompt 中（高优先级段落，soul 之后）

这是对现有调度管道的改造——不改变信号系统本身，改变的是选人管道的最后一步。

**验证方法**：
- 对比有/无战略约束时的发言人选择分布
- 检查 anchor_question 是否被发言人在发言中回应

**验收**：战略约束能影响发言人选择（preferred_agents 被选中的概率提升 > 30%），且 anchor_question 被回应率 > 60%（人工抽检发言内容中是否实质性回应了锚定问题，而非只提了一句）。

---

### 阶段 7：主持人瘦身——职责剥离

**目标**：将现有的 `ModeratorAgent` 中的策略职责移交给战略家，只保留战术职责。

**改动范围**：
- `src/agents/moderator.py` — `AgendaDecision` 精简，移除 `phase`、`agenda_note`、`speaker_focus`、`perception_summary`
- `src/core/modes/salon.py` — Phase 3 改为调用战略家而非主持人做策略决策

**精简后的 AgendaDecision**（或重命名为 TacticalDecision）：

```python
class TacticalDecision(BaseModel):
    """战术调度决策——由主持人/调度层输出"""
    speakers: list[str]           # 最终发言人列表（可能被硬规则覆盖）
    notice: str                   # 场控通知
    reject_intents: list[str]     # 拒绝的意图
    pending_question: str         # 锚定问题（可由战略家的 anchor_question 填充）
```

**移除的字段去哪了**：
- `phase` → 由维度地图的状态自动推导（`active` 维度数量 + 覆盖率）
- `agenda_note` → 被战略家的 `DirectionGuidance` 替代
- `speaker_focus` → 被记录员的 `RoundAnalysis.arguments` 替代
- `perception_summary` → 被信号系统的 ControlSignals 替代（已有更精确的数据）
- `emotional_temperature` / `perceived_tension` → 保留，仍由主持人/战术层感知

**验证方法**：
- 完整跑一次会话，检查精简后的主持人是否能正常工作
- 对比精简前后的发言质量、白板质量

**验收**：精简后的主持人不丢失任何关键功能，讨论质量不低于 baseline。

---

## 依赖关系

```
阶段 0（基线）
  │
  ▼
阶段 1（记录员升级）
  │
  ├──▶ 阶段 2（维度地图）────┐
  │                          │
  ▼                          ▼
阶段 3（战略家）◀────────────┘
  │
  ├──▶ 阶段 4（维度初始化）
  │
  ├──▶ 阶段 5（收敛检测）
  │
  ▼
阶段 6（战术调度改造）
  │
  ▼
阶段 7（主持人瘦身）
```

- 阶段 1 是独立的前置，不依赖其他改动
- 阶段 2 和阶段 3 可以并行开发，但在阶段 3 集成时需要阶段 2 的维度地图
- 阶段 4 和 5 依赖阶段 3（需要战略家来使用初始化的地图和收敛信号）
- 阶段 6 依赖阶段 3（需要战略家的输出作为输入）
- 阶段 7 是最后的清理，依赖前面所有阶段

## 每阶段的验证检查点

| 阶段 | 验证方式 | 成功标准 | 失败时的调整 |
|------|---------|---------|------------|
| 0 | 跑会话 | 可复现 | 修复环境问题 |
| 1 | 人工抽检 RoundAnalysis | core_claim 准确率 > 80% | 调整 prompt，简化输出字段 |
| 2 | 人工评审维度地图 | 维度有区分度，状态正确 | 调整维度数量和粒度 |
| 3 | 10 组场景测试方向决策 | 7 组以上与人工一致 | 简化 prompt，减少输出字段 |
| 4 | 3-5 个话题测试初始化 | 70% 维度合理 | 增加 prompt 中的示例 |
| 5 | 回测已有会话 | 偏差 ≤ 2 轮 | 调整阈值或简化信号 |
| 6 | 对比有/无约束 | preferred_agents 选中率提升 | 调整 BOOST/PENALTY 权重 |
| 7 | 完整会话对比 | 质量不低于 baseline | 回退某个被移除的字段 |

## 风险与降级方案

### 已识别的关键风险

#### 风险 A：灵魂滤镜碾压锚定问题（阶段 3 & 6）

**问题**：即使战略家给出了 `anchor_question` 注入到发言人的 prompt 中，角色的 System Prompt（soul 滤镜）通常非常强大。锚定问题在 speak prompt 中只是一句话，而 soul 是整个 system prompt 的核心。LLM 的注意力分配会让 soul 的权重远大于锚定问题。发言人可能在开头敷衍一句锚定问题，然后迅速"滑回"自己熟悉的矛盾轴。

**应对措施**：

1. **锚定问题提升优先级**：不放在 `round_info` 的末尾，而是作为 speak prompt 中的**独立高优先级段落**，紧接在 soul 之后、发言指令之前。位置决定注意力权重。

2. **维度约束注入**：战略家不仅输出 `anchor_question`，还输出 `dimension_constraint`——一句明确的约束指令。核心措辞原则是**"用你的滤镜解析新维度"，而非"离开你的舒适区"**。不强迫角色放弃自己的视角，而是要求角色的视角在新维度上折射出不同的光谱。这个约束以**加粗指令**的形式出现在 prompt 中。

   ```
   ⚠️ 本轮发言方向约束：
   我们正在探索「{target_dimension}」这个维度。
   你独特的视角能为这个维度提供什么别人看不到的东西？
   具体回答：{anchor_question}

   注意：请不要重复你之前关于「{avoid_dimension}」的论述。
   用你自己的方式解析这个新维度，而不是把它翻译回你熟悉的话题。
   ```

3. **接受部分滑落**：即使有约束，角色仍然会部分滑回自己的滤镜——这是不可避免的，也是可以接受的。只要锚定问题能在发言中产生**一个段落**的有效回应（而不是一句话的敷衍），就达到了目的。完全压制灵魂滤镜既不可能也不可取——滤镜是张力的来源。

**降级方案**：如果锚定问题的回应率低于 30%，将约束从"建议"升级为"硬性要求"——在 prompt 中明确告诉 LLM "如果你无法从这个角度发言，这一轮不要发言"。

#### 风险 B：维度膨胀——LLM 误判"新维度"（阶段 1 & 3）

**问题**：LLM 倾向于把同一个概念的不同表述误认为"新维度"，导致 `emergent` 列表迅速膨胀。比如"无我与自由意志的对比"和"无我的决定论含义"可能被标为两个不同的维度。

**应对措施**：

1. **记录员去重指令**：在记录员的 prompt 中明确要求去重——"如果你发现的新角度与已知维度中的任何一个实质相同（只是措辞不同），不要将其标记为 new_angle，而是标记为对应维度的 covered"。

2. **战略家审核门**：记录员输出的 `new_angles` 不会自动进入维度地图。战略家在每轮的 `MapUpdate` 中显式决定哪些 `new_angles` 值得纳入（`add_dimension`）。战略家的 prompt 中包含去重指令——"在纳入新维度前，检查它是否与现有维度实质相同"。

3. **维度数量硬上限**：维度地图中的维度总数不超过 9 个。如果需要新增，必须先将一个已覆盖的维度标记为 `archived`。这迫使战略家做取舍，而不是无限制地积累。

**降级方案**：如果维度膨胀仍然严重，将 `new_angles` 的检测从记录员移到战略家——记录员只做论点提取，维度的发现和去重全部由战略家负责。

#### 风险 C：初始化维度平庸（阶段 4）

**问题**：用 LLM 一次性生成 5-7 个维度。如果遇到极具争议或非常生僻的话题，LLM 生成的维度可能会非常平庸（cliché），反而限制了讨论的深度。

**应对措施：留白机制**。

在初始化 prompt 中明确要求只生成 3-4 个核心维度，保留 2-3 个 placeholder：

```
给定讨论话题：{topic}

请将这个话题拆解为 3-4 个**最核心的必然维度**。

每个维度应该是：
1. 不同思想传统在这个话题上必然会碰撞的角度
2. 与其他维度有实质区别（不是同一个问题的不同措辞）
3. 如果缺少这个维度，讨论就是不完整的

不要试图穷举所有可能的维度。只需给出最核心的 3-4 个。
其余的维度空间留给参与者在对话中碰撞出来。

同时，请预留 2-3 个 emergent_placeholder（标注为"待涌现"），
表示你认为还有维度尚未出现，但你不确定是什么。
```

这样既有保底（3-4 个核心维度确保讨论不会在空白中开始），又鼓励涌现（placeholder 标记了"还有空间"的信号）。

#### 风险 D：常数加减被信号淹没（阶段 6）

**问题**：`signal_scores[agent_id] += STRATEGY_BOOST`（如 +0.2）的做法在后期极难调参。其他基线分数（如某人连续三轮没说话的饥渴度可能是 +0.8）会轻松淹没战略约束。

**应对措施：Shortlist 机制**。

不使用加减分，而是使用**候选池过滤**：

```python
def apply_strategy_shortlist(strategy, all_intents, hard_rules):
    """
    战略约束通过候选池过滤实现，而非加减分。

    流程：
    1. 硬规则先检查红线（沉默保护等），生成 red_line_agents
    2. 如果战略家给出了 preferred_agents，生成 shortlist
    3. 最终候选池 = red_line_agents ∪ (shortlist ∩ 有意图的agents)
    4. 在候选池内用信号评分排序选人
    """
    # 红线：沉默保护等硬规则强制插入的 agent，不受战略约束影响
    red_line_agents = hard_rules.get_red_line_agents()

    # 短名单：战略家指定的 preferred_agents
    if strategy.direction.preferred_agents:
        shortlist = set(strategy.direction.preferred_agents)
    else:
        shortlist = set(all_intents.keys())  # 无战略约束时，所有人进入候选

    # 最终候选池：红线保护的 + 短名单中有意图的
    candidates_with_intent = set(
        aid for aid, signal in all_intents.items()
        if signal.energy > 0  # 有发言意图
    )
    final_pool = red_line_agents | (shortlist & candidates_with_intent)

    # 在候选池内用信号评分排序
    scores = {aid: compute_signal_score(aid) for aid in final_pool}
    return sorted(scores, key=scores.get, reverse=True)
```

**关键设计**：
- 红线保护（沉默保护、强制收尾）**永远优先于**战略约束。如果一个 agent 沉默了 3 轮，即使他不在 preferred_agents 中，硬规则也会把他塞进候选池最前面。
- 战略约束是**过滤**而非**评分**。不在 shortlist 里的 agent 直接不进入候选（除非触发红线），而不是被减分后与其他信号竞争。
- 如果 preferred_agents 中没有任何人有发言意图（所有人都不想说话），则回退到全量候选池。

### 完整风险清单

| 风险 | 影响 | 应对 | 降级方案 |
|------|------|------|---------|
| A: 灵魂滤镜碾压锚定问题 | 发言人滑回固定矛盾轴 | 锚定问题高优先级 + "用你的滤镜解析新维度"措辞 + 接受部分滑落 | 升级为硬性要求 |
| B: 维度膨胀 | emergent 列表失控 | 记录员去重 + 战略家审核门 + 硬上限 9 个 | 维度发现全部交给战略家 |
| C: 初始化维度平庸 | 限制讨论深度 | 留白：3-4 核心 + 2-3 placeholder | 改为半自动：LLM 生成 + 人工审核 |
| D: Shortlist 真空 | 战略约束因 energy=0 失效 | 强制点名机制：preferred_agents 即使 energy=0 也纳入候选池并优先选中 | 回退到全量池 |
| E: 维度覆盖误判 | 记录员过度匹配或匹配不到 | CoveredDimension 要求 evidence + confidence | 由战略家直接判断覆盖情况 |
| F: 收敛检测太灵敏 | 讨论蜻蜓点水，无法深入 | 阈值与参与者数量挂钩：lock_depth >= max(6, participants*1.5) | 增加"连续深入奖励"机制 |
| G: 时序错位 | 记录员读不到本轮发言 | 记录员分析上一轮已完成发言，战略家为下一轮生成锚点 | 修正流程图 |
| H: 角色崩塌(OOC) | 强制离开舒适区导致角色失去特色 | 用"你的视角能为新维度提供什么"替代"即使不熟悉也要聊" | 接受角色在新维度上表现较弱 |
| 记录员 RoundAnalysis 质量不稳定 | 战略家输入垃圾 → 输出垃圾 | 简化为只提取 core_claim | 战略家自己读原始发言 |
| 战略家方向决策不靠谱 | 把讨论引向无关方向 | 10 组场景测试 | 降级为建议模式，主持人保留决策权 |
| LLM 调用延迟增加 | 每轮多一次 LLM 调用 | stride=2 + 收敛时强制触发 | 合并记录员+战略家为一次调用 |
| 维度切换太频繁 | 讨论无法深入 | 最小深度阈值 + stride 机制自然降频 | 增加"连续深入奖励"机制 |

## 文件改动清单

| 文件 | 改动类型 | 阶段 |
|------|---------|------|
| `src/agents/scribe.py` | 新增 `analyze_round()` + `RoundAnalysis` 模型 | 1 |
| `src/llm/prompts.py` | 新增 `build_round_analysis_prompt()` | 1 |
| `src/core/modes/salon.py` | 插入记录员分析步骤 | 1 |
| `src/memory/whiteboard.py` | 新增 `dimension_map` section | 2 |
| `src/agents/scribe.py` | `sync_whiteboard` 增加维度维护 | 2 |
| `src/agents/moderator.py` | 新增 `TopicStrategist` + `StrategyOutput` 模型 | 3 |
| `src/llm/prompts.py` | 新增 `build_strategist_prompt()` | 3 |
| `src/core/modes/salon.py` | 插入战略家决策步骤 | 3 |
| `src/agents/moderator.py` | 新增 `initialize_dimension_map()` | 4 |
| `src/llm/prompts.py` | 新增 `build_dimension_init_prompt()` | 4 |
| `src/agents/scribe.py` | `RoundAnalysis.convergence_hint` 强化 | 5 |
| `src/core/modes/salon.py` | `_post_process` 增加战略约束叠加 | 6 |
| `src/llm/prompts.py` | `build_speak_prompt` 增加战略方向注入 | 6 |
| `src/agents/moderator.py` | `AgendaDecision` 精简为 `TacticalDecision` | 7 |
| `src/core/modes/salon.py` | Phase 3 重构 | 7 |
