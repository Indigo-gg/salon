# 重构规划：代码控制状态转移，LLM 负责内容生成

> **修订记录（v3）**：Phase 1-4 已实施完成。Phase 5（反滥调机制）待后续迭代。
>
> **实施状态**：
> - ✅ Phase 1：基础设施（DimensionState / PhaseState / QualityGate / SessionController / AnchorCoverageCheck 提取）
> - ✅ Phase 2：接入状态机（DimensionState + PhaseState 接入 salon.py、StrategyOutput 精简 5 字段、prompt 重设计、_StrategyCompat 适配、closing_window 统一）
> - ✅ Phase 3：质量门验证（锚点交叉验证接入 _scribe_analyze、白板 allowlist 接入 _scribe_sync）
> - ✅ Phase 4：信号系统修复（tension_level 代码主导 ±1 级、emotional_temperature EMA 平滑）
> - ⬜ Phase 5：反滥调机制（5A AgentConceptProfile / 5B ConceptBan / 5C per-agent CoT / 5D 违禁词检测）——详见 `docs/strategist-upgrade.md` 升级三至七
>
> **v2 修订**：基于代码验证评审修订。主要变更：① 补充消费者影响矩阵；② 解决 PhaseState 与现有 phase 控制的三路冲突；③ DimensionState 接入 SchedulingState 信号；④ 新增 SessionController 聚合类；⑤ 支持非线性维度导航；⑥ 统一 closing_window 计算；⑦ 提取 AnchorCoverageCheck 到公共模块；⑧ 新增信号系统迁移计划；⑨ 新增 prompt 重设计节；⑩ 新增跨模式兼容性说明。

## 一、核心反模式诊断

### 反模式：LLM 既当裁判又当球员

当前架构的根本问题不是某个具体机制设计不好，而是一个架构层面的反模式：**让 LLM 同时承担"状态决策"和"内容生成"两种职责**。

```
当前架构（反模式）:
  LLM 输出 = 状态决策 + 内容生成（混在一起）
  ↓
  代码直接消费 LLM 输出的 should_switch / phase / needs_escalation
  ↓
  大模型的"球员本能"（续写精彩上下文）压倒"裁判本能"（执行强制切换）
  ↓
  节奏完全失控
```

```
目标架构（范式转换）:
  代码层 = 状态机（决定"做什么"）
  ↓
  LLM层 = 内容工厂（生成"怎么做"的具体内容）
  ↓
  代码层 = 质量门（验证 LLM 输出是否合规）
```

### 反模式的具体表现

| 决策类型 | 当前由谁做 | 应该由谁做 | 风险等级 |
|----------|-----------|-----------|---------|
| 维度是否该切换 | LLM (`should_switch`) | 代码（轮次+覆盖率） | 🔴 高 |
| 讨论阶段转移 | LLM (`phase`) | 代码（状态机） | 🔴 高 |
| 是否强制触发战略家 | LLM (`needs_escalation`) | 代码（轮次+新颖度） | 🔴 高 |
| 紧张度判断 | LLM (`perceived_tension`) | 代码（信号规则） | 🔴 高 |
| 情绪温度 | LLM (`emotional_temperature`) | 代码（EMA 平滑） | 🟡 中 |
| 发言人选择 | LLM (`speakers`) | 代码排序 + LLM 建议 | 🟡 中 |
| 白板写入 | LLM (`operations`) | 代码 allowlist + LLM 内容 | 🟡 中 |
| 锚定问题生成 | LLM (`anchor_question`) | LLM（但需代码验证关联性） | 🟢 低 |
| CoT 模板生成 | LLM (`cot_template`) | LLM（但需代码验证格式） | 🟢 低 |
| 发言内容 | LLM (`speech`) | LLM（纯内容生成） | 🟢 低 |

---

## 二、现状全景图：所有 LLM 决策点

### 2.1 战略家（strategist.py）—— 11 个 LLM 决策字段

```
StrategyOutput:
├── current_dimension_id      ← LLM 选维度      → 应由代码状态机驱动
├── current_dimension_label   ← LLM 生成标签     → 纯内容，保留
├── dimension_core_question   ← LLM 生成问题     → 纯内容，保留
├── should_switch             ← LLM 决定是否切换  → 应由代码强制覆盖
├── switch_reason             ← LLM 解释原因     → 纯内容，保留
├── anchor_question           ← LLM 生成锚点     → 纯内容，保留
├── cot_template              ← LLM 生成模板     → 纯内容，保留
├── moderator_notice          ← LLM 生成通知     → 纯内容，保留
├── grounding_needed          ← LLM 判断是否需具象化 → 应由代码信号辅助
├── preferred_agents          ← LLM 选人建议     → 保留，代码可覆盖
└── anchor_coverage           ← LLM 评估锚点回应  → 应由代码信号交叉验证
```

### 2.2 主持人（moderator.py）—— 7 个 LLM 决策字段

```
AgendaDecision:
├── speakers                  ← LLM 选人         → 代码排序+兜底
├── notice                    ← LLM 生成通知     → 纯内容，保留
├── reject_intents            ← LLM 拒绝意图     → 代码可覆盖
├── phase                     ← LLM 判定阶段     → 应由代码状态机控制
├── emotional_temperature     ← LLM 感知温度     → 应由代码 EMA 平滑
├── perceived_tension         ← LLM 感知紧张度   → 应由代码规则主导
└── pending_question          ← LLM 锚定问题     → 与战略家锚点合并
```

### 2.3 记录员（scribe.py）—— 5 个 LLM 决策字段

```
RoundAnalysis:
├── arguments[]               ← LLM 提取论点     → 纯内容，保留
├── new_angles[]              ← LLM 发现新角度   → 代码去重后保留
├── covered_dimensions[]      ← LLM 判断覆盖     → 代码可交叉验证
├── convergence_hint          ← LLM 判断收敛     → 应由代码信号主导
└── anchor_coverage           ← LLM 评估锚点回应  → 应由代码信号交叉验证
```

### 2.4 信号系统（observer.py）—— 2 个 LLM 反馈字段

```
ControlSignals:
├── llm_emotional_temperature ← LLM 直传         → 应由代码 EMA 平滑
└── llm_perceived_tension     ← LLM 覆盖代码规则  → 应由代码规则主导
```

---

## 三、重构方案：四层架构

### 新架构原则

```
┌─────────────────────────────────────────────────────┐
│  Layer 0: SessionController（聚合调度器）              │
│  职责：持有所有状态机，统一调度 update() 顺序           │
│  输入：轮次开始信号                                    │
│  输出：当前维度 / 阶段 / 信号 / 质量门结果              │
├─────────────────────────────────────────────────────┤
│  Layer 1: 代码状态机（DimensionState / PhaseState）   │
│  职责：决定"现在该做什么"                              │
│  输入：轮次、维度轮次计数、新颖度分数、锚点回应率        │
│  输出：状态转移指令（switch_dimension / advance等）     │
├─────────────────────────────────────────────────────┤
│  Layer 2: LLM 内容工厂（Strategist / Scribe）        │
│  职责：生成"怎么做"的具体内容                          │
│  输入：代码状态机的指令 + 上下文                        │
│  输出：anchor_question / cot_template / arguments     │
├─────────────────────────────────────────────────────┤
│  Layer 3: 代码质量门（QualityGate）                   │
│  职责：验证 LLM 输出是否合规                          │
│  检查：维度关联性、格式合规、Ban 生命周期、数值范围      │
├─────────────────────────────────────────────────────┤
│  Layer 4: 代码执行层（Salon execute_round）           │
│  职责：组装 per-agent prompt、执行发言、写入记忆        │
└─────────────────────────────────────────────────────┘
```

### 3.1 SessionController（新增聚合调度器）

**问题**：`salon.py` 的 `execute_round()` 当前已超过 1000 行，手动编排各状态机之间的信号传递会导致进一步膨胀。

**方案**：引入 `SessionController` 聚合 `DimensionState`、`PhaseState`、`SchedulingState`、`QualityGate`，统一调度它们的 `update()` 顺序和信号传递。

```python
# 新增：src/core/session_controller.py

class SessionController:
    """聚合所有状态机，统一调度轮次推进。"""

    def __init__(self, roadmap, config, scheduling_state):
        self.dimension = DimensionState(roadmap, config)
        self.phase = PhaseState(config)
        self.scheduling = scheduling_state
        self.quality_gate = QualityGate(config)

    def advance_round(self, round_num: int, anchor_quality: str) -> RoundDirective:
        """
        每轮开始时调用，返回本轮的完整指令集。

        调度顺序（顺序敏感）：
        1. DimensionState.advance_round() — 更新维度轮次计数
        2. DimensionState.check_switch_needed() — 检查维度切换
        3. PhaseState.update() — 更新阶段（感知维度状态变化）
        4. 组装 RoundDirective — 供 execute_round() 使用
        """
        # 1. 维度推进
        self.dimension.advance_round(round_num)

        # 2. 维度切换检查
        novelty = self.scheduling.get_latest_novelty()
        speeches_since_novel = self.scheduling.speeches_since_novel
        switch, reason = self.dimension.check_switch_needed(
            round_num, anchor_quality, novelty, speeches_since_novel
        )
        if switch:
            self.dimension.switch_to_next(round_num)

        # 3. 阶段推进
        uncovered = self.dimension.get_uncovered_dimensions()
        dim_covered = self.dimension.is_current_covered()
        new_phase = self.phase.update(
            round_num=round_num,
            dimension_fully_covered=dim_covered,
            uncovered_dims=len(uncovered),
        )

        # 4. 组装指令
        return RoundDirective(
            dimension_id=self.dimension.current_dimension_id,
            dimension_label=self.dimension.current_dimension.label,
            phase=new_phase,
            should_switch_dim=switch,
            switch_reason=reason,
            uncovered_dims=uncovered,
        )

    def validate_strategy(self, output: 'StrategyOutput') -> 'StrategyOutput':
        """战略家输出后，运行质量门验证。"""
        return self.quality_gate.validate_strategy_output(
            output, self.dimension, self.scheduling
        )


class RoundDirective:
    """SessionController 输出的本轮指令集——execute_round() 的唯一输入。"""

    def __init__(self, dimension_id, dimension_label, phase,
                 should_switch_dim, switch_reason, uncovered_dims):
        self.dimension_id = dimension_id
        self.dimension_label = dimension_label
        self.phase = phase
        self.should_switch_dim = should_switch_dim
        self.switch_reason = switch_reason
        self.uncovered_dims = uncovered_dims
```

**关键设计**：`salon.py` 的 `execute_round()` 不再直接操作各状态机，而是通过 `SessionController.advance_round()` 获取 `RoundDirective`。这将 `execute_round()` 中的状态编排逻辑从 ~200 行缩减到 ~20 行。

---

## 四、逐决策点的重构方案

### 4.1 维度切换决策（🔴 最高优先级）

**现状：**
- `StrategyOutput.should_switch`：LLM 布尔值，代码直接信任
- `StrategyOutput.current_dimension_id`：LLM 选择，代码直接采纳
- `rounds_per_dim`：仅作为 prompt 文本注入，无强制执行

**问题：** LLM 看到精彩讨论时，"球员本能"压倒"裁判本能"，拒绝切换。

**重构方案：代码状态机驱动，LLM 只做内容填充**

```python
# 新增：src/core/dimension_state.py

class DimensionState:
    """维度状态机——代码控制维度生命周期。

    支持非线性导航：跳过已自然覆盖的维度，回溯覆盖不足的维度。
    不再假设严格线性序列，而是基于 coverage 质量选择下一个维度。
    """

    def __init__(self, roadmap: DiscussionRoadmap, config):
        self.roadmap = roadmap
        self.dimension_sequence = roadmap.dimension_sequence
        self.current_index = 0
        self.dim_start_round = 0
        self.dim_round_count = 0
        self.consecutive_low_coverage = 0
        self.max_rounds_per_dim = config.discussion.max_rounds_per_dimension
        self.coverage_history: dict[str, list[str]] = {}  # dim_id -> [quality]

    @property
    def current_dimension_id(self) -> str:
        return self.dimension_sequence[self.current_index]

    @property
    def current_dimension(self) -> MandatoryDim:
        dim_id = self.current_dimension_id
        return next(d for d in self.roadmap.mandatory_dimensions if d.id == dim_id)

    def advance_round(self, round_num: int) -> None:
        """每轮开始时调用，更新轮次计数"""
        self.dim_round_count = round_num - self.dim_start_round

    def check_switch_needed(
        self,
        round_num: int,
        anchor_quality: str = "unknown",
        novelty_score: float = 0.5,
        speeches_since_novel: int = 0,
    ) -> tuple[bool, str]:
        """
        代码级维度切换判断。不依赖 LLM。

        信号来源：
        1. 轮次超时（硬截断）
        2. 连续低质量回应（锚点被敷衍）
        3. 连续低新颖度发言（话题枯竭，复用 SchedulingState 信号）
        """
        # 规则1：轮次超时（硬截断）
        if self.dim_round_count >= self.max_rounds_per_dim:
            return True, f"维度已讨论 {self.dim_round_count} 轮，达到上限 {self.max_rounds_per_dim}"

        # 规则2：连续低质量回应（锚点被敷衍）
        if anchor_quality in ("ignored", "token"):
            self.consecutive_low_coverage += 1
            if self.consecutive_low_coverage >= 2:
                return True, f"参与者连续 {self.consecutive_low_coverage} 轮无法实质性回应"
        else:
            self.consecutive_low_coverage = 0

        # 规则3：连续低新颖度——话题在当前维度上已枯竭
        # 复用 SchedulingState 的 speeches_since_novel 信号
        if speeches_since_novel >= 3 and self.dim_round_count >= 2:
            return True, f"连续 {speeches_since_novel} 轮无新观点，当前维度话题枯竭"

        return False, ""

    def switch_to_next(self, round_num: int) -> str | None:
        """
        执行维度切换。支持非线性导航：

        优先级：
        1. 选择 coverage 最低的未充分覆盖维度（而非简单 +1）
        2. 如果所有维度都已充分覆盖，按原始序列推进
        3. 如果所有维度都已覆盖，返回 None
        """
        uncovered = self.get_uncovered_dimensions()
        if uncovered:
            # 选择第一个未充分覆盖的维度（可扩展为优先级排序）
            next_dim = uncovered[0]
            if next_dim in self.dimension_sequence:
                self.current_index = self.dimension_sequence.index(next_dim)
        elif self.current_index + 1 < len(self.dimension_sequence):
            # 所有维度都有覆盖，按序列推进
            self.current_index += 1
        else:
            return None  # 所有维度已覆盖

        self.dim_start_round = round_num
        self.dim_round_count = 0
        self.consecutive_low_coverage = 0
        return self.current_dimension_id

    def record_coverage(self, dim_id: str, quality: str) -> None:
        """记录维度覆盖质量"""
        if dim_id not in self.coverage_history:
            self.coverage_history[dim_id] = []
        self.coverage_history[dim_id].append(quality)

    def get_uncovered_dimensions(self) -> list[str]:
        """获取未充分覆盖的维度"""
        uncovered = []
        for dim_id in self.dimension_sequence:
            qualities = self.coverage_history.get(dim_id, [])
            if not qualities or all(q in ("ignored", "token") for q in qualities[-2:]):
                uncovered.append(dim_id)
        return uncovered

    def is_current_covered(self) -> bool:
        """当前维度是否已充分覆盖"""
        dim_id = self.current_dimension_id
        qualities = self.coverage_history.get(dim_id, [])
        return bool(qualities) and any(q in ("deep", "surface") for q in qualities[-2:])
```

**战略家的职责变化：**

```
之前：战略家决定 should_switch + current_dimension_id（状态决策 + 内容生成）
之后：代码状态机决定是否切换 + 切到哪个维度（状态决策）
      战略家只生成该维度下的 anchor_question + cot_template（内容生成）
```

---

### 4.2 讨论阶段转移（🔴 高优先级）

**现状：三套并行的 Phase 管控机制（冲突源）**

| # | 机制 | 位置 | 行为 |
|---|------|------|------|
| 1 | `AgendaDecision.phase` | moderator.py L31-41 | LLM 自由选择阶段 |
| 2 | `SchedulingState.post_process()` | scheduling_state.py L403 | 代码直接修改 `decision.phase = "DEEPENING"` |
| 3 | `SchedulingState.should_force_closing()` | scheduling_state.py L240-247 | 仅最后 1 轮触发，salon.py L454 设为 CLOSING |

**问题**：三套机制各自修改 `decision.phase`，LLM 下一轮可以立刻改回来，形成控制权拉锯。

**重构方案：PhaseState 成为 phase 的唯一权威数据源（SSOT）**

```python
# 新增：src/core/phase_state.py

class PhaseState:
    """讨论阶段状态机——代码控制阶段转移。

    PhaseState 是 phase 的唯一权威数据源。
    - SchedulingState 不再直接修改 decision.phase，改为发送信号
    - AgendaDecision.phase 字段被移除，LLM 不再决定阶段
    - salon.py 和 moderator.py 统一从 PhaseState 读取当前阶段
    """

    # 合法的状态转移图
    VALID_TRANSITIONS = {
        "OPENING":     {"EXPLORATION"},
        "EXPLORATION": {"DEEPENING", "CONVERGENCE"},
        "DEEPENING":   {"EXPLORATION", "CONVERGENCE"},
        "CONVERGENCE": {"DEEPENING", "CLOSING"},
        "CLOSING":     set(),  # 终态，不可逆
    }

    def __init__(self, config):
        self.phase = "OPENING"
        self.max_rounds = config.discussion.max_rounds
        self.participants_count = len(config.agents) if hasattr(config, 'agents') else 3
        self.phase_start_round = 0
        # 从配置读取收尾窗口参数（复用 SchedulingState 的配置）
        monitor_cfg = config.monitor if hasattr(config, 'monitor') else None
        self.closing_window_min = getattr(monitor_cfg, 'closing_window_min', 2)
        self.closing_window_max = getattr(monitor_cfg, 'closing_window_max', 5)

    def get_closing_window(self) -> int:
        """收尾窗口：最后 N 轮自动进入 CONVERGENCE。

        使用配置中的 closing_window_min / closing_window_max，
        与 SchedulingState 共用同一套配置值，避免两套不一致的实现。
        """
        import math
        raw = math.ceil(math.sqrt(self.max_rounds))
        return max(self.closing_window_min, min(self.closing_window_max, raw))

    def update(self, round_num: int, dimension_fully_covered: bool,
               uncovered_dims: int, exhaustion_signal: bool = False) -> str:
        """
        代码级阶段转移。

        信号来源：
        - round_num：轮次推进
        - dimension_fully_covered：DimensionState 提供
        - uncovered_dims：DimensionState 提供
        - exhaustion_signal：SchedulingState 提供（替代直接修改 decision.phase）
        """
        rounds_left = self.max_rounds - round_num
        closing_window = self.get_closing_window()

        # 规则1：CLOSING 是终态，不可逆
        if self.phase == "CLOSING":
            return "CLOSING"

        # 规则2：最后 1 轮强制 CLOSING
        if rounds_left <= 1:
            return self._try_transition("CLOSING")

        # 规则3：收尾窗口内，无未覆盖维度 → CONVERGENCE
        if rounds_left <= closing_window and uncovered_dims == 0:
            return self._try_transition("CONVERGENCE")

        # 规则4：收尾窗口内，有未覆盖维度 → 保持当前阶段（优先切维度）
        if rounds_left <= closing_window:
            pass  # 不切阶段，让维度状态机处理

        # 规则5：OPENING → EXPLORATION（至少 2 轮后）
        if self.phase == "OPENING" and round_num >= 2:
            return self._try_transition("EXPLORATION")

        # 规则6：EXPLORATION ↔ DEEPENING（基于维度覆盖深度）
        if self.phase == "EXPLORATION" and dimension_fully_covered:
            return self._try_transition("DEEPENING")
        if self.phase == "DEEPENING" and not dimension_fully_covered:
            return self._try_transition("EXPLORATION")

        # 规则7：SchedulingState 的枯竭信号 → DEEPENING
        # （替代原 SchedulingState.post_process() 直接修改 decision.phase 的做法）
        if exhaustion_signal and self.phase in ("EXPLORATION", "DEEPENING"):
            return self._try_transition("DEEPENING")

        # 规则8：CONVERGENCE → DEEPENING（如果发现新维度需要探索）
        if self.phase == "CONVERGENCE" and uncovered_dims > 0 and rounds_left > closing_window:
            return self._try_transition("DEEPENING")

        # 默认：保持当前阶段
        return self.phase

    def _try_transition(self, new_phase: str) -> str:
        """尝试状态转移，验证合法性"""
        if new_phase in self.VALID_TRANSITIONS.get(self.phase, set()):
            self.phase = new_phase
            self.phase_start_round = 0
        return self.phase
```

**关键变更：SchedulingState.post_process() 的改造**

```python
# scheduling_state.py post_process() 改造：

# 改造前（L403）：
#   decision.phase = "DEEPENING"   ← 直接修改，与 PhaseState 冲突

# 改造后：
#   返回 exhaustion_signal = True
#   由 SessionController 传给 PhaseState.update(exhaustion_signal=True)
#   PhaseState 决定是否转移阶段
```

`SchedulingState.post_process()` 不再直接修改 `decision.phase`，而是返回一个 `exhaustion_signal` 布尔值。`SessionController` 将这个信号传给 `PhaseState.update()`，由 `PhaseState` 统一决定是否转移阶段。

**关键变更：salon.py 中 should_force_closing 的合并**

```python
# salon.py 改造：

# 改造前（L451-456）：
#   if ctx.scheduling_state.should_force_closing(round_num, max_rounds):
#       decision.phase = "CLOSING"

# 改造后：
#   PhaseState.update() 的规则 2 已覆盖此逻辑（rounds_left <= 1 → CLOSING）
#   删除 salon.py 中的 should_force_closing 覆盖代码
```

---

### 4.3 强制触发战略家（🔴 高优先级）

**现状：**
- `_should_force_strategy()` 依赖 `anchor_coverage.needs_escalation`（LLM 布尔值）
- 战略家 stride=2 是硬编码

**问题：** LLM 可以错误地设置 `needs_escalation=True` 导致战略家被过度触发，或者 `needs_escalation=False` 导致维度卡死未被发现。

**重构方案：代码信号驱动触发**

```python
def _should_force_strategy(self, ctx: ModeContext) -> bool:
    """代码级强制触发判断——不依赖 LLM 布尔值"""
    if not ctx.last_strategy:
        return False

    # 信号1：维度轮次接近上限
    if self._session_ctrl.dimension.dim_round_count >= self._session_ctrl.dimension.max_rounds_per_dim - 1:
        return True

    # 信号2：连续低质量锚点回应（基于代码追踪，非 LLM 判断）
    if self._session_ctrl.dimension.consecutive_low_coverage >= 1:
        return True

    # 信号3：新颖度分数持续走低
    novelty = self._session_ctrl.scheduling.get_latest_novelty()
    if novelty < self._session_ctrl.scheduling.novelty_low_threshold:
        return True

    return False
```

---

### 4.4 紧张度和情绪温度（🟡 中优先级）

**现状：**
- `observer.py:297-299`：`llm_perceived_tension` 直接覆盖代码规则引擎
- `emotional_temperature` 无 EMA 平滑，LLM 可以在 0.0 和 1.0 之间剧烈跳动

**问题：** LLM 的感知形成了一个无约束的反馈循环。

**重构方案：代码规则主导 + LLM 反馈仅作微调**

```python
# observer.py 中 tension_level 的计算改为：

def _compute_tension_level(self) -> str:
    """代码规则主导的紧张度计算"""
    formation = self._state_vector.formation
    gini = self._state_vector.gini_coefficient
    speaker_count = self._state_vector.speaker_count

    # 代码规则（已有）
    if formation < 0.3:
        base_tension = "monologue"
    elif formation < 0.5:
        base_tension = "parallel"
    elif formation > 0.7 and self._state_vector.speed > 0.5:
        base_tension = "heated"
    else:
        base_tension = "debate"

    # LLM 反馈仅作微调（±1 级），不能跳级
    llm_tension = self._llm_perceived_tension
    tension_order = ["monologue", "parallel", "moderate", "debate", "heated", "conflict"]

    if llm_tension and llm_tension in tension_order:
        base_idx = tension_order.index(base_tension) if base_tension in tension_order else 2
        llm_idx = tension_order.index(llm_tension)
        clamped_idx = max(base_idx - 1, min(base_idx + 1, llm_idx))
        return tension_order[clamped_idx]

    return base_tension


def _smooth_emotional_temperature(self, raw_temp: float) -> float:
    """对 LLM 的情绪温度做 EMA 平滑。

    复用 observer.py 已有的 EMA 类（L62-85），支持首值直通逻辑，
    避免首轮平滑后值严重偏低的问题。
    """
    if not hasattr(self, '_temp_ema'):
        self._temp_ema = EMA(half_life=3.0, initial_value=raw_temp)
    return self._temp_ema.update(raw_temp)
```

---

### 4.5 白板写入控制（🟡 中优先级）

**现状：**
- Scribe 的 `WhiteboardSync.operations` 可以写入任何 section
- 仅靠 prompt 指令约束，无代码 allowlist

**重构方案：代码 allowlist + section 级别权限**

```python
# scribe.py 中白板操作的代码级验证

SCRIBE_ALLOWED_SECTIONS = {
    "current_focus", "consensus", "disagreements", "backlog",
    "surprises", "active_concepts", "dimension_map", "search_materials",
}

SCRIBE_FORBIDDEN_SECTIONS = {
    "agenda_trace",  # 仅 moderator 可写
}

def validate_whiteboard_operations(ops: list[WhiteboardOperation]) -> list[WhiteboardOperation]:
    """代码级白板操作验证"""
    validated = []
    for op in ops:
        if op.section in SCRIBE_FORBIDDEN_SECTIONS:
            logger.warning(f"[Scribe] 拒绝写入禁止区域: {op.section}")
            continue
        if op.section not in SCRIBE_ALLOWED_SECTIONS:
            logger.warning(f"[Scribe] 拒绝写入未知区域: {op.section}")
            continue
        validated.append(op)
    return validated
```

---

### 4.6 锚点回应质量验证（🟡 中优先级）

**现状：**
- `anchor_coverage.quality` 完全由 Scribe LLM 判断
- `needs_escalation` 是 LLM 布尔值，直接触发 `_should_force_strategy`

**重构方案：代码信号交叉验证**

```python
def validate_anchor_coverage(
    coverage: AnchorCoverageCheck,
    novelty_score: float,
    dim_round_count: int,
    novelty_low_threshold: float,  # 从配置读取，不再硬编码
) -> AnchorCoverageCheck:
    """代码级锚点回应质量验证——交叉检查 LLM 判断"""
    # 如果 LLM 说"深入回应"但新颖度很低，可能判断有误
    # 使用配置中的 novelty_low_threshold（默认 0.2），不再硬编码 0.15
    if coverage.quality == "deep" and novelty_score < novelty_low_threshold:
        logger.warning("[QualityGate] LLM 判断 deep 但 novelty 极低，降级为 surface")
        coverage.quality = "surface"

    # 如果 LLM 说"忽略"但维度才刚开始（第1轮），可能是误判
    if coverage.quality == "ignored" and dim_round_count <= 1:
        logger.warning("[QualityGate] 维度第1轮就被判 ignored，标记为 unknown")
        coverage.quality = "unknown"

    # 重新计算 needs_escalation
    coverage.needs_escalation = (
        coverage.quality in ("ignored", "token")
        or (coverage.quality == "surface" and dim_round_count >= 3)
    )

    return coverage
```

---

### 4.7 路线图初始化验证（🟢 低优先级）

**现状：**
- `DiscussionRoadmap.mandatory_dimensions` 数量由 LLM 自由决定
- prompt 说"3-4 个"但代码不验证

**重构方案：代码验证 + 自动修正**

```python
def validate_roadmap(roadmap: DiscussionRoadmap, total_rounds: int) -> DiscussionRoadmap:
    """代码级路线图验证"""
    dims = roadmap.mandatory_dimensions

    if len(dims) < 2:
        logger.warning(f"[QualityGate] 维度数量过少({len(dims)})，可能讨论不完整")
    if len(dims) > 5:
        logger.warning(f"[QualityGate] 维度数量过多({len(dims)})，截断为5个")
        roadmap.mandatory_dimensions = dims[:5]
        roadmap.dimension_sequence = roadmap.dimension_sequence[:5]

    dim_ids = {d.id for d in roadmap.mandatory_dimensions}
    seq_ids = set(roadmap.dimension_sequence)
    if dim_ids != seq_ids:
        logger.warning("[QualityGate] dimension_sequence 与 mandatory_dimensions 不一致，自动修正")
        roadmap.dimension_sequence = [d.id for d in roadmap.mandatory_dimensions]

    dim_count = len(roadmap.mandatory_dimensions)
    rounds_per_dim = max(2, total_rounds // (dim_count + 1))
    if rounds_per_dim < 2:
        logger.warning(f"[QualityGate] 每维度仅 {rounds_per_dim} 轮，建议减少维度数量")

    return roadmap
```

---

## 五、新增数据结构

### 5.0 SessionController（聚合调度器）

```python
# 新文件：src/core/session_controller.py

class SessionController:
    """聚合所有状态机，统一调度轮次推进。"""
    def __init__(self, roadmap, config, scheduling_state): ...
    def advance_round(self, round_num, anchor_quality) -> RoundDirective: ...
    def validate_strategy(self, output) -> StrategyOutput: ...

class RoundDirective:
    """SessionController 输出的本轮指令集。"""
    dimension_id: str
    dimension_label: str
    phase: str
    should_switch_dim: bool
    switch_reason: str
    uncovered_dims: list[str]
```

### 5.1 DimensionState（维度状态机）

```python
# 新文件：src/core/dimension_state.py

class DimensionState:
    """维度状态机——代码控制维度生命周期，支持非线性导航。"""
    def __init__(self, roadmap, config): ...
    def advance_round(self, round_num: int) -> None: ...
    def check_switch_needed(self, round_num, anchor_quality,
                            novelty_score, speeches_since_novel) -> tuple[bool, str]: ...
    def switch_to_next(self, round_num) -> str | None: ...  # 基于 coverage 选择，非线性
    def record_coverage(self, dim_id, quality) -> None: ...
    def get_uncovered_dimensions(self) -> list[str]: ...
    def is_current_covered(self) -> bool: ...
    def get_pacing_info(self) -> dict: ...
```

### 5.2 PhaseState（阶段状态机）

```python
# 新文件：src/core/phase_state.py

class PhaseState:
    """讨论阶段状态机——代码控制阶段转移（phase 唯一权威数据源）。"""
    VALID_TRANSITIONS = { ... }
    def __init__(self, config): ...
    def update(self, round_num, dimension_fully_covered,
               uncovered_dims, exhaustion_signal=False) -> str: ...
    def get_closing_window(self) -> int: ...  # 复用配置中的 closing_window_min/max
```

### 5.3 QualityGate（质量门）

```python
# 新文件：src/core/quality_gate.py

class QualityGate:
    """代码级质量验证——验证 LLM 输出是否合规。"""
    def __init__(self, config): ...

    @staticmethod
    def validate_roadmap(roadmap, total_rounds) -> DiscussionRoadmap: ...

    @staticmethod
    def validate_anchor_coverage(coverage, novelty_score, dim_round_count,
                                 novelty_low_threshold) -> AnchorCoverageCheck: ...

    def validate_strategy_output(self, output, dimension_state,
                                 scheduling_state) -> StrategyOutput: ...

    @staticmethod
    def validate_whiteboard_operations(ops) -> list[WhiteboardOperation]: ...
```

### 5.4 AnchorCoverageCheck（公共模型——消除重复定义）

```python
# 新文件：src/models.py（或 src/core/models.py）

class AnchorCoverageCheck(BaseModel):
    """锚点回应质量检查——战略家和记录员共用。

    当前在 strategist.py:61-76 和 scribe.py:33-48 重复定义，
    提取到公共模块消除重复。
    """
    was_addressed: bool
    quality: Literal["deep", "surface", "token", "ignored", "unknown"]
    who_addressed: list[str] = []
    evidence: str = ""
    needs_escalation: bool = False
```

---

## 六、精简后的 LLM 输出 Schema

### 6.1 StrategyOutput（精简后）

```python
class StrategyOutput(BaseModel):
    """战略家每轮输出——仅内容生成，不做状态决策"""

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
        description="场控通知内容"
    )

    # 建议性字段（代码可覆盖）
    grounding_needed: bool = Field(
        default=False,
        description="建议：当前讨论是否需要用具体场景推进"
    )
    preferred_agents: list[str] = Field(
        default_factory=list,
        description="建议：本轮最适合发言的参与者"
    )
    concept_bans: list[ConceptBan] = Field(
        default_factory=list,
        description="建议：针对特定参与者的概念禁令"
    )

    # 评估字段（供代码交叉验证，不直接驱动状态转移）
    anchor_coverage: AnchorCoverageCheck | None = Field(
        default=None,
        description="上一轮锚定问题的回应评估（供代码交叉验证）"
    )
```

**移除的字段（由代码状态机接管）：**
- `current_dimension_id` → `DimensionState.current_dimension_id`
- `current_dimension_label` → 从 `roadmap.mandatory_dimensions` 读取
- `dimension_core_question` → 从 `roadmap.mandatory_dimensions` 读取
- `should_switch` → `DimensionState.check_switch_needed()`
- `switch_reason` → `DimensionState.check_switch_needed()` 返回

**消费者影响矩阵**（字段移除后需要适配的所有位置）：

| 消费位置 | 使用的字段 | 适配方案 |
|---------|-----------|---------|
| salon.py L519-523 `_emit_decision` | `current_dimension_id`, `should_switch`, `switch_reason` | 改为读取 `RoundDirective` |
| salon.py L534-536 `decision_history` 事件 | `current_dimension_id`, `anchor_question`, `should_switch` | `dimension_id` 改为从 `RoundDirective` 读取，`should_switch` 改为从 `RoundDirective.should_switch_dim` 读取 |
| salon.py L425-437 `_StrategyCompat` 适配器 | `preferred_agents`, `anchor_question`, `current_dimension_id` | `target_dimension` 改为从 `DimensionState.current_dimension_id` 读取；**长期应消除此适配器，让 `apply_strategy_constraint` 直接接受新接口** |
| salon.py L374-375 `moderator_notice` | `moderator_notice` | 保留，无需适配 |
| salon.py L399 `grounding_needed` | `grounding_needed` | 保留，无需适配 |
| salon.py L692-693 `_scribe_analyze` | `anchor_question` | 保留，无需适配 |
| salon.py L781-782 `_strategist_decide` | `anchor_question` | 保留，无需适配 |
| salon.py L922-926 `_build_strategy_injection` | `cot_template`, `anchor_question` | 保留，无需适配 |

**_StrategyCompat 适配器处理计划**：

```python
# 短期（Phase 2C）：适配器改为从 DimensionState 读取 target_dimension
class _StrategyCompat:
    def __init__(self, strategy, dimension_state):
        self.direction = type('Dir', (), {
            'preferred_agents': strategy.preferred_agents,
            'anchor_question': strategy.anchor_question,
            'target_dimension': dimension_state.current_dimension_id,  # 改为从状态机读取
        })()
        self.convergence_response = None

# 长期（Phase 3+）：重构 apply_strategy_constraint 接口，消除适配器
```

### 6.2 AgendaDecision（精简后）

```python
class AgendaDecision(BaseModel):
    """主持人每轮输出——仅战术调度，不做阶段判断"""

    speakers: list[str] = Field(description="推荐的发言人列表")
    notice: str | None = Field(default=None, description="场控通知")
    reject_intents: list[str] = Field(default_factory=list, description="拒绝的意图")

    # 保留：感知字段（代码 EMA 平滑后使用）
    emotional_temperature: float = Field(default=0.5, ge=0.0, le=1.0)
    perceived_tension: str = Field(default="moderate")

    # 保留：锚定问题（可由战略家的 anchor_question 填充）
    pending_question: str | None = Field(default=None)

    # 移除：phase → PhaseState.update()（唯一权威源）
```

**决策历史事件结构变化**：

`decision_history` 事件中的 `phase` 字段改为从 `PhaseState.phase` 读取（而非 `decision.phase`）。Web API 的 `/monitor` replay 和前端需要适配此变化。

---

### 6.3 战略家 Prompt 重设计（新增）

**背景**：移除 `should_switch`、`current_dimension_id` 等字段后，战略家的角色从「状态决策者 + 内容生成者」变为纯「内容生成者」。Prompt 需要同步重写。

**核心变更原则**：
1. 告诉 LLM「你不需要决定是否切换维度，代码已经决定了」
2. 告诉 LLM「你的当前维度是 X」（由代码注入，而非 LLM 自己选）
3. LLM 的任务聚焦于「为当前维度生成锚定问题和 CoT 模板」

**新 Prompt 关键段落设计**：

```
## 你的角色
你是讨论的战略家，负责为当前讨论维度生成引导性内容。

## 当前状态（由代码提供，不可修改）
- 当前维度：{dimension_label}（ID: {dimension_id}）
- 维度核心问题：{dimension_core_question}
- 已讨论轮次：{dim_round_count} / {max_rounds_per_dim}
- 上一轮锚点回应质量：{anchor_quality}

## 你的任务
基于当前维度和讨论上下文，生成：
1. anchor_question：一个具体、有争议、直接对齐当前维度的锚定问题
2. cot_template：注入发言者思考过程的强制模板
3. moderator_notice（可选）：场控通知
4. grounding_needed：是否需要用具体场景推进讨论
5. preferred_agents：本轮最适合发言的参与者
6. concept_bans：针对特定参与者的概念禁令
7. anchor_coverage：评估上一轮锚定问题的回应质量

## 重要：你不需要决定
- ❌ 是否切换维度（代码已决定）
- ❌ 当前是哪个维度（代码已告诉你）
- ❌ 讨论阶段（代码已决定）
```

**Prompt 重设计的实施时机**：Phase 2C（与 StrategyOutput 精简同步）。需要实际测试验证新 prompt 的内容生成质量不下降。

---

## 七、信号系统迁移计划（新增）

### 现状：两套信号系统并行运行

| 系统 | 位置 | 状态 |
|------|------|------|
| `RoundMonitor`（旧） | `src/core/round_monitor.py` | 仍在运行 |
| `ModeratorSignalSystem`（新） | `src/core/moderator_signal/__init__.py` | 仍在运行 |

两者在 `salon.py` 中同时初始化（L63-66），同时产出信号。

### 迁移策略

```
Phase 2（本重构）：
  - ModeratorSignalSystem 的信号（novelty_score, speeches_since_novel 等）
    接入 DimensionState 和 PhaseState
  - RoundMonitor 保留但不再作为状态决策的信号源

Phase 3+（后续）：
  - 验证 ModeratorSignalSystem 的信号覆盖 RoundMonitor 的所有功能
  - 废弃 RoundMonitor，将剩余有用信号迁移到 ModeratorSignalSystem
  - 删除 round_monitor.py
```

---

## 八、跨模式兼容性（新增）

项目有三种模式：`salon`、`debate`、`interview`。

### 组件归属

| 组件 | salon 专用 | 跨模式通用 | 说明 |
|------|-----------|-----------|------|
| SessionController | ✅ | | salon 模式的聚合调度器 |
| DimensionState | ✅ | | 维度概念是 salon 专有 |
| PhaseState | | ✅ | debate 模式也有阶段转移，可复用 |
| QualityGate | | ✅ | 白板验证、路线图验证可复用 |
| AnchorCoverageCheck | | ✅ | 公共模型 |
| RoundDirective | ✅ | | salon 模式的指令集 |

### debate 模式的兼容性

debate 模式已有独立的 `DebatePhase` 枚举（`debate_state.py:14-18`）和 `DebateState` 状态管理。它**不使用** `AgendaDecision.phase`，`ModeratorAgent` 仅用于发言人选择。

**结论**：`PhaseState` 可以作为 debate 模式的阶段管理基础设施（替换其自定义的 `DebateState.phase`），但这不是本次重构的范围。本次重构仅影响 salon 模式。

---

## 九、依赖关系与实施顺序（修订）

### 依赖图

```
Phase 1: 基础设施（无外部依赖，可并行）
├── 1A: DimensionState（维度状态机）
├── 1B: PhaseState（阶段状态机）
├── 1C: QualityGate（质量门骨架）
├── 1D: SessionController 骨架 + RoundDirective    ← 新增
└── 1E: 提取 AnchorCoverageCheck 到公共模块        ← 新增

Phase 2: 接入状态机（依赖 Phase 1）
├── 2A: 接入 DimensionState → SessionController → salon.py
├── 2B: 接入 PhaseState → SessionController → salon.py
│         同时改造 SchedulingState.post_process()（不再直接修改 phase）
│         同时删除 salon.py 中的 should_force_closing 覆盖
├── 2C: StrategyOutput 精简 + Prompt 重设计         ← 扩展范围
│         + 消费者适配（_emit_decision, decision_history, _StrategyCompat）
└── 2D: 统一 closing_window 配置                    ← 新增

Phase 3: 质量门验证（依赖 Phase 2）
├── 3A: 锚点回应质量交叉验证（使用配置阈值，非硬编码）
├── 3B: 白板写入 allowlist
├── 3C: 路线图初始化验证
└── 3D: 废弃 _StrategyCompat 适配器                 ← 新增

Phase 4: 信号系统修复（依赖 Phase 2）
├── 4A: tension_level 代码规则主导
├── 4B: emotional_temperature EMA 平滑（复用已有 EMA 类）
└── 4C: RoundMonitor 信号迁移评估                    ← 新增

Phase 5: 反滥调机制（依赖 Phase 2 + Phase 3A）
├── 5A: AgentConceptProfile（Scribe 概念追踪）
├── 5B: ConceptBan（战略家精准禁令）
├── 5C: per-agent CoT 组装
└── 5D: 违禁词检测闭环
```

**Phase 5 依赖说明**：5A 的 `AgentConceptProfile` 需要 Scribe 的 `RoundAnalysis` 数据，而 `RoundAnalysis` 的 `anchor_coverage` 字段经过 Phase 3A 的质量门验证后才可靠。因此 Phase 5 隐含依赖 Phase 3A。

### 复杂度评估（修订）

| 任务 | 新增代码量 | 修改文件数 | LLM 成本影响 | 风险 |
|------|-----------|-----------|-------------|------|
| 1A: DimensionState | ~130 行 | 1 新文件 | 零 | 低 |
| 1B: PhaseState | ~90 行 | 1 新文件 | 零 | 低 |
| 1C: QualityGate | ~100 行 | 1 新文件 | 零 | 低 |
| 1D: SessionController | ~80 行 | 1 新文件 | 零 | 低 |
| 1E: AnchorCoverageCheck 提取 | ~20 行 | 3 文件（新增+改 strategist/scribe） | 零 | 低 |
| 2A: 接入 DimensionState | ~30 行改 | salon.py | 零 | 中 |
| 2B: 接入 PhaseState | ~60 行改 | salon.py, scheduling_state.py | 零 | 中高 |
| 2C: StrategyOutput 精简 + Prompt | ~50 行删 + ~80 行改 | strategist.py, salon.py | 减少 ~200 tokens | 高 |
| 2D: 统一 closing_window | ~10 行改 | phase_state.py, scheduling_state.py | 零 | 低 |
| 3A: 锚点交叉验证 | ~30 行 | quality_gate.py | 零 | 低 |
| 3B: 白板 allowlist | ~20 行 | scribe.py | 零 | 低 |
| 3C: 路线图验证 | ~30 行 | quality_gate.py | 零 | 低 |
| 3D: 废弃 _StrategyCompat | ~20 行删 | salon.py | 零 | 低 |
| 4A: tension_level 修复 | ~30 行改 | observer.py | 零 | 低 |
| 4B: temp EMA 平滑 | ~10 行改 | observer.py | 零 | 低 |
| 4C: RoundMonitor 迁移评估 | 文档 | 无 | 零 | 低 |
| 5A: AgentConceptProfile | ~40 行 | scribe.py | +50 tokens/agent | 低 |
| 5B: ConceptBan | ~30 行 | strategist.py | +100 tokens | 低 |
| 5C: per-agent CoT | ~60 行 | salon.py | 零 | 低 |
| 5D: 违禁词检测 | ~25 行 | scribe.py | +50 tokens | 低 |

### 推荐实施顺序（修订）

```
第一批（可并行，零依赖）:
  1A: DimensionState         ← 核心，解决维度卡死
  1B: PhaseState             ← 核心，解决阶段失控
  1C: QualityGate 骨架        ← 基础设施
  1D: SessionController 骨架  ← 聚合调度器
  1E: AnchorCoverageCheck    ← 消除重复

第二批（依赖第一批，按价值排序）:
  2B: 接入 PhaseState         ← 最高价值，解决三路冲突
  2A: 接入 DimensionState     ← 第二高价值
  2C: StrategyOutput 精简     ← 配合 2A，含 prompt 重设计
  2D: 统一 closing_window     ← 低风险快速修复

第三批（可并行，依赖第二批）:
  3A-3C: 质量门验证
  4A-4B: 信号系统修复
  3D: 废弃 _StrategyCompat

第四批（依赖第二批 + 3A）:
  5A-5D: 反滥调机制

第五批（后续迭代）:
  4C: RoundMonitor 废弃
  debate 模式 PhaseState 接入评估
```

---

## 十、验证方案（修订）

### 每阶段验收标准

| 阶段 | 验证方式 | 成功标准 |
|------|---------|---------|
| 1A | 单元测试 DimensionState | 状态转移 100% 符合规则；非线性导航正确处理跳过/回溯 |
| 1B | 单元测试 PhaseState | 合法转移图 100% 正确；closing_window 与 SchedulingState 一致 |
| 1D | 单元测试 SessionController | advance_round 正确编排状态机调用顺序 |
| 2A | 完整会话对比 | 维度覆盖率从 ~60% 提升到 > 90% |
| 2B | 完整会话对比 | 阶段转移不再出现回退；SchedulingState 不再直接修改 phase |
| 2C | 检查 StrategyOutput 字段 | 不再包含 should_switch 等状态字段；新 prompt 生成质量不下降 |
| 3A | 日志检查 QualityGate 拦截 | LLM 误判被代码纠正的次数 > 0；阈值从配置读取 |
| 4A | 信号日志对比 | tension_level 不再被 LLM 单方面覆盖 |
| 5A-5D | 完整会话对比 | 概念重复率下降 > 20% |

### 回归风险（修订——完整消费者清单）

**StrategyOutput 字段移除的影响范围**（代码验证确认）：

| 文件 | 行号 | 访问的字段 | 适配方案 |
|------|------|-----------|---------|
| salon.py L374-375 | `moderator_notice` | 保留，无需适配 |
| salon.py L399 | `grounding_needed` | 保留，无需适配 |
| salon.py L425-437 | `preferred_agents`, `anchor_question`, `current_dimension_id` | `_StrategyCompat` 改为从 `DimensionState` 读取 `target_dimension` |
| salon.py L519-523 | `current_dimension_id`, `should_switch`, `switch_reason` | 改为从 `RoundDirective` 读取 |
| salon.py L534-536 | `current_dimension_id`, `anchor_question`, `should_switch` | 事件字段改为从 `RoundDirective` + `DimensionState` 读取 |
| salon.py L692-693 | `anchor_question` | 保留，无需适配 |
| salon.py L781-782 | `anchor_question` | 保留，无需适配 |
| salon.py L922-926 | `cot_template`, `anchor_question` | 保留，无需适配 |

**AgendaDecision.phase 移除的影响范围**（代码验证确认）：

| 文件 | 行号 | 操作 | 适配方案 |
|------|------|------|---------|
| moderator.py L155 | 读取 → 缓存 | 改为从 `PhaseState.phase` 读取 |
| salon.py L402 | 日志 | 改为从 `RoundDirective.phase` 读取 |
| salon.py L452 | 检查 `!= "CLOSING"` | 删除（PhaseState 已处理） |
| salon.py L513 | 白板 trace | 改为从 `RoundDirective.phase` 读取 |
| salon.py L531 | 事件 dict | 改为从 `RoundDirective.phase` 读取 |
| scheduling_state.py L388 | 检查 `== "CONVERGENCE"` | 改为从 `PhaseState.phase` 读取 |
| web/api/manager.py L715 | 白板 trace | 改为从 `PhaseState.phase` 读取 |

**额外发现的风险**：
- `web/api/manager.py:720` 读取 `decision.agenda_note`，但 `AgendaDecision` 无此字段。这可能是死代码或运行时错误，需要在 Phase 2 中排查。

---

## 十一、与现有文档的关系

| 文档 | 关系 |
|------|------|
| `docs/moderator-redesign.md` | 本文档是它的升级版，吸收了其阶段 1-7 的设计，但重构了核心架构 |
| `docs/strategist-upgrade.md` | 本文档的 Phase 5（反滥调）对应其升级三至七 |
| `docs/implementation-plan.md` | 本文档替代它作为新的实施计划 |
