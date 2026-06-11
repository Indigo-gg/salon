# Salon 多智能体对话协作系统 — 技术规格文档

> 版本：0.3 | 最后更新：2026-06-10

---

## 一、项目概述

### 1.1 项目愿景

Salon 是一个多智能体对话协作系统，灵感来源于 18 世纪法国沙龙式对话。系统的核心理念是**"过程即产出"**——对话过程本身比最终报告更有价值。

### 1.2 核心设计原则

| 原则 | 说明 |
|------|------|
| 沙龙，而非会议室 | 不是效率驱动的产出流水线，而是让思想碰撞自然发生 |
| 过程即产出 | 讨论过程有独立价值，报告只是副产品 |
| 发散优先，收敛随后 | 不急于达成共识，允许充分探索 |
| 尊重未解决的分歧 | 无法达成一致的问题忠实记录为开放性分歧 |
| 钢铁人论证法 | 回应他人前先重述对方最强版本的论点 |
| 建设性追评 | 赞同时补充新视角，而非简单附和 |

### 1.3 技术栈

| 层面 | 技术选型 | 说明 |
|------|---------|------|
| 语言 | Python 3.11+ | 主语言 |
| LLM 接口 | OpenAI API 规范 | 兼容任何遵循 OpenAI API 格式的提供商 |
| 存储 | 文件系统 | JSON/JSONL/Markdown/YAML |
| 界面（V1） | CLI | 命令行交互 |
| 界面（V2） | Web 前后端分离 | 后端 Python API，前端 HTML/CSS/JS |
| 包管理 | pip + requirements.txt | — |
| 配置 | YAML | 所有关键变量可手动配置 |

### 1.4 第一使用场景

**哲学对话** — 3-5 位具有不同哲学背景的 Agent 围绕一个哲学议题展开深度讨论。

### 1.5 基本参数

| 参数 | 默认值 | 可配置 |
|------|--------|--------|
| 参与者数量 | 3-5 人 | ✅ |
| 讨论轮次 | 20-50 轮 | ✅ |
| 单次发言字数上限 | 1000 字 | ✅ |
| 讨论语言 | 中文 | ✅ |
| 人类默认角色 | 观察者 | ✅ |
| 跨场次记忆 | 开启 | ✅ |

---

## 二、系统架构

### 2.1 整体架构图

```
                           ┌─────────────────────┐
                           │    main.py (入口)     │
                           └──────────┬──────────┘
                                      │
                           ┌──────────▼──────────┐
                           │   Orchestrator       │
                           │   (协调器 - 主控)      │
                           │                      │
                           │  ┌──────────────────┐│
                           │  │ SessionManager   ││
                           │  │ (场次生命周期)     ││
                           │  └──────────────────┘│
                           │  ┌──────────────────┐│
                           │  │ RoundMonitor     ││
                           │  │ (轮次信号计算器)   ││
                           │  └──────────────────┘│
                           └──┬─────┬─────┬──────┘
                              │     │     │
              ┌───────────────┤     │     ├───────────────┐
              │               │     │     │               │
     ┌────────▼───────┐ ┌────▼─────▼──┐ ┌▼──────────┐ ┌──▼──────────┐
     │  Context       │ │  Moderator  │ │  Human    │ │  Output     │
     │  Manager       │ │  + Strategist│ │  Interface│ │  (transcript│
     │  (上下文        │ │  (主持人     │ │  (人类     │ │   digest)   │
     │   管理器)       │ │   + 战略家)  │ │   接口)   │ │             │
     └──────┬─────────┘ └──────┬──────┘ └───────────┘ └─────────────┘
            │                  │
            │         ┌────────┼────────┐
            │         │        │        │
     ┌──────▼───────┐ │  ┌─────▼──────┐ │
     │  Memory      │ │  │ Agent Pool │ │
     │  System      │ │  │ (Agent 池) │ │
     │              │ │  │            │ │
     │ ┌──────────┐ │ │  │ ┌────────┐│ │
     │ │ Stream   │ │ │  │ │Partici-││ │
     │ │ (对话流)  │ │ │  │ │pant    ││ │
     │ ├──────────┤ │ │  │ ├────────┤│ │
     │ │Whiteboard│ │ │  │ │Scribe  ││ │
     │ │ (白板)    │ │ │  │ └────────┘│ │
     │ └──────────┘ │ │  │            │ │
     └──────────────┘ │  │ ┌────────┐│ │
                      │  │ │ Soul   ││ │
                      │  │ │ System ││ │
                      │  │ └────────┘│ │
                      │  └────────────┘ │
                      │                 │
                      │  ┌────────────┐ │
                      │  │ LLM Client │ │
                      │  │ (LLM 客户端)│ │
                      │  └────────────┘ │
                      └─────────────────┘
```

### 2.2 核心角色分工

系统中有四类角色，职责边界清晰：

| 角色 | 类型 | 是否参与对话流 | 核心职责 |
|------|------|--------------|---------|
| **主持人 (Moderator)** | 系统级Agent | ✅ 每轮参与 | 战术调度：选择发言人、发布notice、阶段判断 |
| **战略家 (Strategist)** | 系统级Agent | ❌ 后台运行 | 战略规划：维度地图管理、方向决策、维度切换 |
| **记录员 (Scribe)** | 系统级Agent | ❌ 后台运行 | 分析+记录：每轮论点提取、白板维护、维度地图维护、会后纪要生成 |
| **参与者 (Participant)** | 普通Agent | ✅ 被主持人选中后发言 | 基于Soul人格进行思想交锋 |

**设计决策**：职责分离为"感知（记录员）→ 战略（战略家）→ 战术（主持人）"三层。记录员负责事实提取，战略家负责方向决策，主持人负责执行调度。这种分离解决了早期版本中主持人"全栈决策"导致宏观视野被微观决策淹没的问题。

### 2.3 数据流图（单轮发言）

```
轮次 N 结束后：
                    ┌───────────────▼─────────────────┐
                    │  ① 记录员分析（每轮运行）          │
                    │     Scribe.analyze_round()        │
                    │                                   │
                    │  输入：轮次 N 的已完成发言          │
                    │  输出：RoundAnalysis               │
                    │  - 每个发言者的核心论点             │
                    │  - 新讨论角度                      │
                    │  - 维度覆盖（附证据）               │
                    │  - 收敛提示                        │
                    └───────────────┬─────────────────┘
                                    │
轮次 N+1 开始：                     │
                    ┌───────────────▼─────────────────┐
                    │  ② 战略家决策（stride=2）          │
                    │     Strategist.decide_strategy()  │
                    │                                   │
                    │  输入：RoundAnalysis + 维度地图     │
                    │  + 防御性信号 + 上一轮方向           │
                    │  输出：StrategyOutput              │
                    │  - 维度地图更新指令                 │
                    │  - 目标维度 + 锚定问题              │
                    │  - preferred_agents               │
                    │  - 收敛应对（如需要）               │
                    └───────────────┬─────────────────┘
                                    │
                    ┌───────────────▼─────────────────┐
                    │  ③ 意图收集（参与者看到锚定问题）   │
                    │     所有参与者并行生成 HandSignal    │
                    └───────────────┬─────────────────┘
                                    │
                    ┌───────────────▼─────────────────┐
                    │  ④ 信号计算                       │
                    │     RoundMonitor + SignalSystem   │
                    └───────────────┬─────────────────┘
                                    │
                    ┌───────────────▼─────────────────┐
                    │  ⑤ 主持人战术决策                  │
                    │     Moderator.decide_agenda()     │
                    │                                   │
                    │  - 选择发言人                      │
                    │  - 驳回跑题意图                    │
                    │  - 发布notice                     │
                    │  - 判断阶段                        │
                    └───────────────┬─────────────────┘
                                    │
                    ┌───────────────▼─────────────────┐
                    │  ⑥ 战略约束叠加                   │
                    │     SchedulingState               │
                    │     .apply_strategy_constraint()  │
                    │                                   │
                    │  - preferred_agents 优先级提升     │
                    │  - 强制点名（energy=0 的 preferred）│
                    │  - 红线保护（沉默太久的 agent）     │
                    └───────────────┬─────────────────┘
                                    │
                    ┌───────────────▼─────────────────┐
                    │  ⑦ 串行发言（注入战略方向）         │
                    │     参与者.speak()                │
                    │                                   │
                    │  注入：                           │
                    │  - Soul人格 + 行为规则             │
                    │  - 白板（聚焦版）                  │
                    │  - 近期对话 + 摘要历史              │
                    │  - 战略方向约束（锚定问题）         │
                    │  - 呼吸空间建议（条件性）           │
                    └───────────────┬─────────────────┘
                                    │
                    ┌───────────────▼─────────────────┐
                    │  ⑧ 后处理                        │
                    │  a. 发言 → ConversationStream    │
                    │  b. 发言 → Transcript (JSONL)    │
                    │  c. 每5轮触发白板同步（记录员）    │
                    │  d. 每轮触发记录员结构化分析       │
                    └─────────────────────────────────┘
```

---

## 三、核心模块规格

### 3.1 Orchestrator（协调器）

**文件**：`src/core/orchestrator.py`

**职责**：系统主控，管理整个讨论的生命周期。

```python
class Orchestrator:
    """
    系统主控协调器。

    职责：
    1. 初始化所有子系统（Agent池、记忆系统、Round Monitor等）
    2. 运行主讨论循环
    3. 处理人类介入
    4. 管理场次生命周期
    """

    def __init__(self, config: SalonConfig):
        self.config = config
        self.session_manager = SessionManager(config)
        self.context_manager = ContextManager(config)
        self.human_interface = HumanInterface(config.human)
        self.llm_client = LLMClient(config.llm)
        self.round_monitor: RoundMonitor | None = None

    def run(self, topic: str, agent_ids: list[str], mode: str = "salon") -> None:
        """启动一场讨论"""
        ...

    def _main_loop(self) -> None:
        """
        主讨论循环：

        while round < max_rounds:
            1. 检查人类输入窗口
            2. _participant_turn():
               a. 战略家决策（stride=2，收敛时强制触发）
               b. 并发收集所有参与者的 SpeakIntent
               c. RoundMonitor.compute() 计算轮次信号
               d. Moderator.decide_agenda_and_speakers() 战术决策
               e. 战略约束叠加（preferred_agents 优先级提升）
               f. 被选中的参与者依次 speak()（注入战略方向）
            3. 每5轮触发 Scribe.sync_whiteboard()
            4. 每轮触发 Scribe.analyze_round()
        """
        ...

    def _closing_round(self, round_num: int) -> int:
        """CLOSING轮：所有参与者给出总结陈词"""
        ...

    def _wrap_up(self) -> None:
        """讨论结束：生成纪要、保存白板"""
        ...
```

**主循环状态机**：

```
         ┌─────────┐
         │ CREATED  │ ← 初始化完成
         └────┬─────┘
              │ run()
         ┌────▼─────┐
         │ RUNNING   │ ← 主讨论循环
         └──┬──┬─────┘
            │  │
   /pause   │  │ 终止条件触发
            │  │ (/end, 达到max_rounds)
     ┌──────▼──┐        ┌──────────┐
     │ PAUSED  │        │ WRAPPING │ ← 生成最终总结
     └──┬──────┘        │  _UP     │
        │ /resume       └────┬─────┘
        │                    │
     ┌──▼──────┐        ┌────▼─────┐
     │ RUNNING │        │ FINISHED │ ← 所有产出物生成完毕
     └─────────┘        └──────────┘
```

---

### 3.2 Agent 系统

#### 3.2.1 Soul 系统

**文件**：`config/souls/*.md`（参与者人格）+ `config/roles/*.md`（角色约束）

每位参与者 Agent 拥有独立的「灵魂档案」（soul.md）。主持人、战略家和记录员没有 soul 文件，而是通过角色约束文件定义行为。

**Soul 文件结构**（参与者）：

```markdown
# [角色名] — [昵称]

## 基本画像
[角色的身份背景、思维传统、知识领域]

## 性格特质
- [特质 1]：[描述]
- [特质 2]：[描述]

## 自我认知
[用第一人称写的自我描述]

## 行为准则
- [准则 1]
- [准则 2]
```

**角色约束文件**（主持人/战略家/记录员）：

```markdown
# [角色]职能约束

> 本文件定义[角色]的职能约束和行为准则。它与人格 SOUL 是独立的。

## 核心目标
[角色的核心职责定义]

## [方法论/分析方法]
[具体的工作方法和技巧]

## 行为准则
[具体的行为约束]
```

**注入方式**：Soul 内容通过 `Soul.inject_role()` 注入到 System Prompt 中，位于基础系统提示之后、讨论行为规则之前。

#### 3.2.2 Agent 基类

**文件**：`src/agents/base.py`

```python
class BaseAgent:
    """
    所有 Agent 的基类。

    属性：
    - agent_id: 唯一标识
    - name: 显示名称
    - role: 角色类型 (moderator / participant / scribe / strategist)
    - soul: Soul 实例
    - config: SalonConfig
    """

    def __init__(self, agent_id: str, soul_path: str, config: SalonConfig):
        self.agent_id = agent_id
        self.soul = Soul.load(soul_path) if soul_path else Soul(name=agent_id, ...)
        self.name = self.soul.name
        self.role = "participant"
        self.config = config

    def generate_intent(self, context: DiscussionContext, llm: LLMClient, round_info: str = "") -> SpeakIntent:
        """生成发言意向（非公开）。返回 SpeakIntent。"""
        ...

    def speak(self, context: DiscussionContext, llm: LLMClient, round_info: str = "") -> SpeechOutput:
        """生成正式发言。返回 SpeechOutput。"""
        ...

    def stream_speak(self, context: DiscussionContext, llm: LLMClient, round_info: str = "") -> Generator[str, None, None]:
        """流式发言：逐块 yield 纯文本发言内容。"""
        ...
```

#### 3.2.3 主持人 Agent（战术调度）

**文件**：`src/agents/moderator.py`

主持人负责战术调度：选人、发通知、拒绝意图、阶段判断。不负责论点提取（记录员做）和议程方向（战略家做）。

```python
class AgendaDecision(BaseModel):
    """主持人的战术调度决策"""
    speakers: list[str]                 # 排序后的获准发言者列表
    notice: str = ""                    # 全局广播通知（可选）
    reject_intents: list[str] = []      # 被驳回的Agent ID
    phase: str = "EXPLORATION"          # OPENING/EXPLORATION/DEEPENING/CONVERGENCE/CLOSING
    emotional_temperature: float = 0.5  # 情绪温度 (0-1)
    perceived_tension: str = "moderate" # 对话张力
    pending_question: str = ""          # 锚定问题


class ModeratorAgent(BaseAgent):
    def decide_agenda_and_speakers(
        self,
        context: DiscussionContext,
        intents: dict[str, str],
        llm: LLMClient,
        max_speakers: int = 3,
        signal_injection: str = "",
        perception_data: str = "",
    ) -> AgendaDecision:
        """
        战术调度决策。

        职责（仅限战术层）：
        1. 选择最有价值的发言人（最多 max_speakers 人）
        2. 驳回跑题意图
        3. 发布 notice（如需要）
        4. 判断当前阶段

        以下职责已移交：
        - 论点提取 → 记录员的 RoundAnalysis
        - 议程方向 → 战略家的 DirectionGuidance
        - 感知摘要 → 信号系统的 ControlSignals
        """
        ...
```

**主持人方法论**（定义在 `config/roles/moderator_role.md`）：

1. **经验检验**：用现实场景检验宏大断言
2. **海拔调节**：动态调节讨论的抽象↔具体程度
3. **揭示隐含假设**：摊开双方未说出的前提
4. **思想实验**：构建具体处境打破理论僵局
5. **光谱映射**：帮助看到非黑即白之间的灰色地带

#### 3.2.4 战略家 Agent（议题规划）

**文件**：`src/agents/strategist.py`

战略家负责管理讨论的维度空间，防止讨论过早收敛到角色引力场的固定轨道。不选人、不发通知。

```python
class StrategyOutput(BaseModel):
    """战略家每轮输出"""
    map_update: MapUpdate              # 维度地图更新指令
    direction: DirectionGuidance       # 本轮方向建议
    convergence_response: str | None   # 收敛应对（如需要）

class DirectionGuidance(BaseModel):
    """方向建议"""
    target_dimension: str              # 目标维度 ID
    reason: str                        # 选择原因
    anchor_question: str               # 锚定问题（注入发言人 prompt）
    preferred_agents: list[str]        # 最适合展开此维度的参与者

class MapUpdate(BaseModel):
    """维度地图更新"""
    mark_covered: list[str]            # 标记为已覆盖
    mark_active: list[str]             # 标记为正在讨论
    add_dimension: list[NewDimension]  # 新增维度
    depth_increment: list[str]         # 深度 +1
    archive_dimension: list[str]       # 归档


class TopicStrategist(BaseAgent):
    def initialize_dimension_map(self, topic, llm, language) -> DimensionMapInit | None:
        """初始化维度地图（3-4 核心维度 + 1-2 placeholder）"""
        ...

    def decide_strategy(self, context, llm, round_analysis_text,
                        dimension_map_text, signal_summary,
                        participants, rounds_left, language) -> StrategyOutput | None:
        """每轮战略决策"""
        ...
```

**战略家职能约束**（定义在 `config/roles/strategist_role.md`）：

- **维度管理**：维护维度地图，防止讨论收敛到单一维度
- **方向决策**：每轮决定下一步探索哪个维度
- **维度切换**：当讨论陷入维度低谷时，引导切换到正交方向
- **选人建议**：指定 preferred_agents（软引导，非硬限制）

**Stride 机制**：
- 默认每 2 轮运行一次战略家（stride=2）
- 当战略家输出 `convergence_response` 时，下一轮强制触发
- 第 1 轮总是触发（初始化后的首次决策）

**维度地图初始化**：
- 留白机制：只初始化 3-4 个核心维度 + 1-2 个 placeholder
- placeholder 标注"待涌现"，等待讨论中自然产生
- 维度总数硬上限 9 个（含 placeholder）

#### 3.2.5 参与者 Agent

**文件**：`src/agents/participant.py`

```python
class ParticipantAgent(BaseAgent):
    """
    讨论参与者 Agent。

    行为特点：
    - 根据 Soul 中的人格特质和思维方式来回应讨论
    - 遵循钢铁人论证法和建设性追评准则
    - 可以选择 pass（不发言）
    """
    pass
```

**参与者共享行为规则**（定义在 `src/llm/prompts.py` 的 `DISCUSSION_BEHAVIOR_RULES`）：

1. **聚焦交锋**：选择性回应关键观点，不逐个表态
2. **思想空间的正确使用**：复述在 review 字段完成，发言直接切入论证
3. **场景复现**：优先代入已有案例，旧案例无法承载时才引入新场景
4. **修辞警觉与逻辑穿透**：警惕隐喻旋涡，穿透修辞检验底层命题
5. **方法论而非黑话**：用日常语言展现思维方式
6. **Show, Don't Tell**：不在发言中解释身份或角色功能
7. **精确回应**：通过 mentions 字段标注回应对象，不在发言中指名道姓

#### 3.2.6 记录员 Agent（分析 + 记录）

**文件**：`src/agents/scribe.py`

记录员有双重职责：每轮结构化分析（`analyze_round`）和定期白板同步（`sync_whiteboard`）。

```python
class ArgumentSummary(BaseModel):
    """单个发言者的核心论点"""
    agent_id: str
    core_claim: str          # 一句话核心主张
    key_metaphor: str | None # 关键比喻
    responds_to: str | None  # 回应了谁

class CoveredDimension(BaseModel):
    """维度覆盖记录"""
    id: str                  # 维度 ID
    confidence: str          # "high" / "low"
    evidence: str            # 触发该维度的发言原句摘要

class RoundAnalysis(BaseModel):
    """记录员每轮输出的结构化分析"""
    arguments: list[ArgumentSummary]      # 每个发言者的核心论点
    new_angles: list[str]                 # 新讨论角度（不在已知维度中）
    covered_dimensions: list[CoveredDimension]  # 触及的维度（附证据）
    convergence_hint: str                 # 收敛趋势判断

class WhiteboardOperation(BaseModel):
    """白板操作"""
    action: str      # rewrite / add / clear_section / delete
    section: str     # 目标板块（含 dimension_map，不可操作 agenda_trace）
    content: str     # 操作内容

class WhiteboardSync(BaseModel):
    """白板同步结果"""
    operations: list[WhiteboardOperation]


class ScribeAgent(BaseAgent):
    def analyze_round(
        self,
        context: DiscussionContext,
        llm: LLMClient,
        dimension_labels: list[str],
        language: str = "zh",
    ) -> RoundAnalysis | None:
        """
        每轮结构化分析（每轮运行）。

        职责：
        - 提取每个发言者的核心论点
        - 标记新讨论角度（与已知维度去重）
        - 标记触及的维度（附证据和置信度）
        - 判断收敛趋势
        """
        ...

    def sync_whiteboard(
        self,
        context: DiscussionContext,
        llm: LLMClient,
        whiteboard_chars: int = 0,
        compression_threshold: int = 0,
    ) -> WhiteboardSync | None:
        """
        后台白板同步（每5轮或超长时触发）。

        职责：
        - 更新 current_focus（疑问句形式）
        - 更新 discussion_phase
        - 合并/清理冗余分歧（Diff & Merge）
        - 压缩超载内容（子弹笔记风格）
        - 维护 active_concepts（概念账本）
        - 维护 dimension_map（维度状态更新）
        """
        ...

    def generate_digest(...) -> str:
        """会后生成讨论纪要"""
        ...

    def generate_overview(...) -> str:
        """会后生成讨论总览"""
        ...
```

**记录员职能约束**（定义在 `config/roles/scribe_role.md`）：

- **论点提取**：每轮提取结构化论点，供战略家使用
- **白板维护**：维护共享白板的所有板块（agenda_trace 除外）
- **维度地图维护**：更新维度状态、新增涌现维度
- **概念账本维护**：追踪活跃的隐喻/术语/概念
- **会后纪要**：在讨论结束后生成结构化纪要和总览

---

### 3.3 信号系统与调度防御

#### 3.3.1 Round Monitor（轮次信号计算器）

**文件**：`src/core/round_monitor.py`

轻量级的纯函数模块，不依赖 LLM，用文本分析计算每轮的信号。

```python
class RoundSignals:
    # 密度信号
    density_score: float            # 最近3轮每轮新概念数均值
    density_trend: str              # "rising" / "stable" / "falling"
    consecutive_high_density: int   # 连续高密度轮次数

    # 节奏信号
    rounds_since_story: int         # 距上次具体故事的轮次数
    rounds_since_anchor: int        # 距上次显式回锚的轮次数

    # 概念信号
    orphaned_concepts: list[str]    # 已引入但N轮未被引用的概念

    # 意图信号
    consecutive_extend: int         # 连续Extend意图的数量
    intent_distribution: dict       # 最近5轮的意图类型分布
```

#### 3.3.2 信号系统（Moderator Signal System）

**文件**：`src/core/moderator_signal/`

三层信号架构：

```
Layer 1: 传感器（RawSignals）
  - topic_keyword_overlap, idf_abstraction, kl_divergence
  - concept_turnover, reference_density, stance_opposition, gini_coefficient

Layer 2: 观察者（SignalObserver）
  - 双重 EMA 平滑（short=3, long=10 半衰期）
  - 8 维状态向量 → 5 维控制信号
  - StateVector: direction, height, speed, formation + deltas
  - ControlSignals: readability_alert, depth_tide, topic_focus, tension, energy

Layer 3: 注入器（SignalInjector）
  - 17 条规则，按优先级互斥选择
  - 最多 1 条内容指令 + 1 条交互指令
  - 注入到主持人和参与者的 prompt 中
```

#### 3.3.3 调度状态（SchedulingState）

**文件**：`src/core/scheduling_state.py`

三层防线的第 3 层——硬规则后处理：

```python
class SchedulingState:
    def apply_strategy_constraint(self, decision, strategy, all_intents, participants):
        """战略约束叠加（优先级排序，无硬删除）"""
        # 红线 > preferred > 其他
        # preferred_agents 获得优先级提升
        # 强制点名：preferred 中 energy=0 的 agent
        ...

    def post_process(self, decision, participants, intents, max_speakers):
        """硬规则后处理"""
        # 规则 1：重复诱导的话题转移
        # 规则 2：穷尽提醒
        # 规则 3：沉默保护
        ...
```

**收敛检测信号**：
- **维度锁定**：只有一个 active 维度且深度超过 `max(6, participants * 1.5)`
- **维度发现停滞**：距离上次新增维度超过 `max(4, participants)` 轮
- **记录员 convergence_hint**：LLM 生成的收敛趋势判断

---

### 3.4 记忆系统

#### 3.4.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  共享白板 (Whiteboard)                                       │
│  生命周期：单场次                                              │
│  所有者：记录员维护，所有参与者可读                               │
│  存储：data/sessions/{session_id}/whiteboard.md               │
│  访问：每轮发言时注入 Prompt（全景版给主持人/战略家，聚焦版给参与者）│
├─────────────────────────────────────────────────────────────┤
│  对话流 (Conversation Stream)                                 │
│  生命周期：单场次，滑动窗口                                     │
│  所有者：所有参与者共享                                         │
│  存储：内存（完整记录持久化到 transcript.jsonl）                  │
│  访问：最近 N 条完整保留，旧消息摘要化                           │
└─────────────────────────────────────────────────────────────┘
```

#### 3.4.2 对话流 (Conversation Stream)

**文件**：`src/memory/stream.py`

```python
class ConversationStream:
    """
    管理当前场次的对话流。

    核心策略：滑动窗口 + 渐进式摘要
    """

    def __init__(self, config: ConversationStreamConfig):
        self.messages: list[Message] = []
        self.summaries: list[Summary] = []
        self.recent_count = config.recent_messages_count  # 默认 12

    def get_recent_messages(self) -> list[Message]:
        """获取最近 N 条完整的消息"""
        ...

    def get_summarized_history(self) -> str:
        """获取摘要化的早期对话"""
        ...

    def get_messages_for_summarization(self) -> list[Message] | None:
        """当消息数量超过窗口时，返回需要摘要化的最旧一批消息"""
        ...
```

**消息数据结构**：

```python
@dataclass
class Message:
    id: str                  # 唯一 ID
    round: int               # 轮次编号
    timestamp: str           # ISO 时间戳
    agent_id: str            # 发言者 ID
    agent_name: str          # 发言者显示名
    agent_role: str          # 角色类型
    content: str             # 发言内容
    speech_type: str         # Extend / Dissent / New_Angle / Clarify / Ask / Pass
    mentions: list[str]      # 提及的 Agent ID 列表
```

#### 3.4.3 共享白板 (Whiteboard)

**文件**：`src/memory/whiteboard.py`

```python
class SharedWhiteboard:
    """
    所有参与者可见的讨论状态板。

    固定板块：
    1. current_focus    — 当前焦点（疑问句形式）
    2. discussion_phase — 讨论所处阶段
    3. current_topic    — 全局主题
    4. consensus        — 已达成的共识
    5. disagreements    — 活跃的分歧
    6. backlog          — 议题积压区
    7. surprises        — 意外发现
    8. agenda_trace     — 议程轨迹（主持人自动维护）
    9. active_concepts  — 活跃概念清单（记录员维护）
    10. dimension_map   — 讨论维度地图（战略家初始化，记录员维护）
    """

    def update(self, section: str, action: str, content: str, round_num: int, added_by: str) -> None:
        """
        更新白板条目。

        action: add / remove / delete / modify / rewrite / clear_section
        """
        ...

    def to_prompt_text(self, current_round: int = 0) -> str:
        """全景版白板（供主持人/战略家决策）。包含所有活跃板块。"""
        ...

    def to_brief_prompt_text(self) -> str:
        """聚焦版白板（供参与者发言）。仅 current_focus + disagreements。"""
        ...
```

**白板视野分离**：

| 版本 | 使用者 | 内容 | 用途 |
|------|--------|------|------|
| `to_prompt_text()` | 主持人/战略家/记录员 | 全部活跃板块 | 战略/战术决策 |
| `to_brief_prompt_text()` | 参与者 | 仅焦点+分歧 | 发言时的轻量导航 |

**维度地图格式**（YAML，存储在 `dimension_map` section）：

```yaml
dimensions:
  - id: definition
    label: "无我的定义与概念分析"
    status: covered        # covered / active / pending / blank / archived
    depth: 3
    notes: "已达成基本共识"
    type: core             # core / placeholder
  - id: phenomenology
    label: "无我体验的现象学"
    status: blank
    depth: 0
    type: placeholder
emergent: []
last_new_dimension_round: 0
```

**冷板凳机制**：条目超过 `cold_storage_ttl` 轮（默认4轮）未更新则标记为 `cold=True`，保留在内存但不再喂给 LLM。

#### 3.4.4 上下文管理器 (Context Manager)

**文件**：`src/core/context_manager.py`

```python
class ContextManager:
    """
    负责为每个 Agent 的每次发言组装完整的上下文。

    Token 预算分配：
    ┌──────────────┬─────────┬────────────┬──────────────────┐
    │ 上下文类型    │ 预算     │ 白板视图    │ 额外数据          │
    ├──────────────┼─────────┼────────────┼──────────────────┤
    │ intent       │ 1,200   │ brief      │ 上轮摘要          │
    │ speak        │ 5,000   │ brief      │ 摘要历史+论证栈    │
    │ moderator    │ 8,000   │ full       │ 完整摘要          │
    │ scribe       │ 3,000   │ full       │ 无               │
    │ strategist   │ 3,000   │ full       │ 无（复用scribe预算）│
    └──────────────┴─────────┴────────────┴──────────────────┘
    总预算：~12,000 tokens（含 2,000 生成预留）
    """

    def build_context(self, agent: BaseAgent, memory: MemorySystem,
                      round_number: int, context_type: str = "speak") -> DiscussionContext:
        """为指定 Agent 构建上下文。按优先级截断超出预算的部分。"""
        ...
```

---

### 3.5 发言结构化输出

#### 3.5.1 发言意向 (HandSignal)

```python
class HandSignal(BaseModel):
    want_to_speak: bool = True
    energy: str                 # "high" / "medium" / "low"
    target: str | None          # 想回应的角色名
    direction: str              # challenge / extend / new_angle / clarify / summarize / pass
    search_queries: list[str]   # 搜索关键词（如需要）
```

#### 3.5.2 发言输出 (SpeechOutput)

```python
class SpeechOutput(BaseModel):
    review: str | None              # 信息咀嚼：客观梳理对话流，盘点他人观点
    thought: str | None             # 逻辑推演：作为角色的内在思考过程（CoT）
    speech: str                     # 正式开口：最终公开发表的发言内容
    speech_type: str                # Extend / Dissent / New_Angle / Clarify / Ask / Pass
    mentions: list[str]             # 本次发言中回应的角色名列表
    next_direction: str             # 一句话：下一步想推动的方向
    understood_claims: list[str]    # 对他人论点的复述
```

#### 3.5.3 认知卸载机制

`review` 和 `thought` 字段是**认知卸载**空间。参与者被要求：
- 在 `review` 中完成信息复述和盘点（"把复述的欲望在这里发泄完"）
- 在 `thought` 中完成角色视角的逻辑推演
- 在 `speech` 中直接切入论证，禁止总结性陈述

---

### 3.6 人类接口 (Human Interface)

**文件**：`src/human/interface.py` + `src/human/commands.py`

#### 3.6.1 三种介入模式

```python
class HumanRole(Enum):
    CHAIR = "chair"              # 主持人：抛出议题、控制节奏
    PARTICIPANT = "participant"  # 参与者：与 Agent 平等讨论
    OBSERVER = "observer"        # 观察者：默认，旁观并偶尔介入
```

#### 3.6.2 控制指令集

| 指令 | 说明 |
|------|------|
| `/pause` | 暂停讨论 |
| `/resume` | 恢复讨论 |
| `/ask @角色名 问题` | 向特定角色提问 |
| `/topic 新议题` | 引入新议题 |
| `/whiteboard` | 查看当前白板 |
| `/end` | 结束讨论 |
| `/inject @角色名 指令` | 向某角色注入私有指令 |
| `/skip` | 跳过当前议题 |
| `/status` | 查看当前讨论状态 |
| `/help` | 显示所有可用指令 |

---

### 3.7 LLM 客户端

**文件**：`src/llm/client.py`

```python
class LLMClient:
    """
    OpenAI 兼容的 LLM 客户端。

    特点：
    - 兼容任何遵循 OpenAI API 规范的提供商
    - 自动重试（retry_count 次，间隔 retry_delay 秒）
    - 超时控制
    - 结构化输出解析（基于 pydantic 模型）
    - 流式输出支持
    """

    def chat(self, messages: list[dict]) -> str:
        """发送聊天请求，返回纯文本。"""
        ...

    def chat_structured(self, messages: list[dict], schema: Type[BaseModel]) -> BaseModel:
        """发送结构化输出请求，返回 pydantic 模型实例。"""
        ...

    def chat_stream(self, messages: list[dict]) -> Generator[str, None, None]:
        """流式输出。"""
        ...
```

---

### 3.8 产出物

#### 3.8.1 产出物层次

| 层次 | 名称 | 自动生成 | 格式 | 说明 |
|------|------|---------|------|------|
| 1 | 原始记录 | ✅ 实时 | JSONL | 完整的对话记录，每条发言即时写入磁盘 |
| 2 | 讨论纪要 | ✅ 结束时 | Markdown | 记录员生成的结构化摘要 |
| 3 | 讨论总览 | ✅ 结束时 | Markdown | 记录员生成的简要总览 |

#### 3.8.2 原始记录格式 (transcript.jsonl)

每行一条消息，JSON 格式：

```json
{
  "id": "msg_0001_philosopher_west",
  "round": 1,
  "timestamp": "2026-06-02T01:41:00",
  "agent_id": "philosopher_west",
  "agent_name": "卡尔",
  "agent_role": "participant",
  "speech_type": "Extend",
  "content": "关于自由意志的问题，我认为首先需要厘清...",
  "mentions": ["existentialist"]
}
```

消息类型包括：
- `intent`：举手意图
- `speech`：正式发言
- `system_notice`：主持人场控通知
- `question`：人类提问

---

## 四、文件存储结构

```
agent-team/                            # 项目根目录
├── CLAUDE.md                          # Claude Code 指引
├── README.md                          # 项目说明
├── requirements.txt                   # Python 依赖
├── docs/
│   ├── specification.md               # 本规格文档
│   ├── moderator-redesign.md          # 主持人重构设计方案
│   └── implementation-plan.md         # 实施计划
│
├── config/
│   ├── default.yaml                   # 默认配置
│   ├── local.yaml                     # 本地覆盖配置（.gitignore）
│   ├── souls/                         # 参与者人格档案
│   │   ├── existentialist.md
│   │   ├── marxist.md
│   │   ├── philosopher_east.md
│   │   ├── philosopher_west.md
│   │   └── scientist.md
│   └── roles/                         # 系统角色约束
│       ├── moderator_role.md
│       ├── scribe_role.md
│       └── strategist_role.md
│
├── src/
│   ├── main.py                        # 程序入口
│   ├── config.py                      # 配置加载
│   │
│   ├── core/
│   │   ├── orchestrator.py            # 协调器（主控）
│   │   ├── round_monitor.py           # 轮次信号计算器
│   │   ├── context_manager.py         # 上下文窗口管理
│   │   ├── session.py                 # 场次生命周期管理
│   │   ├── scheduling_state.py        # 调度状态与硬规则
│   │   └── moderator_signal/          # 信号系统
│   │       ├── observer.py            # EMA 观察者
│   │       ├── sensors.py             # 原始传感器
│   │       └── injector.py            # 信号注入器
│   │
│   ├── agents/
│   │   ├── base.py                    # Agent 基类 + 数据结构
│   │   ├── soul.py                    # Soul 系统
│   │   ├── moderator.py              # 主持人 Agent（战术调度）
│   │   ├── strategist.py             # 战略家 Agent（议题规划）
│   │   ├── participant.py            # 参与者 Agent
│   │   └── scribe.py                 # 记录员 Agent（分析+记录）
│   │
│   ├── memory/
│   │   ├── __init__.py                # MemorySystem
│   │   ├── stream.py                  # 对话流管理
│   │   └── whiteboard.py              # 共享白板（含维度地图）
│   │
│   ├── human/
│   │   ├── interface.py               # 人类交互接口
│   │   └── commands.py                # 控制指令解析器
│   │
│   ├── output/
│   │   └── transcript.py              # 原始记录（实时写入 JSONL）
│   │
│   └── llm/
│       ├── client.py                  # OpenAI 兼容 LLM 客户端
│       └── prompts.py                 # Prompt 模板 + 行为规则
│
├── data/                              # 运行时数据（自动创建）
│   └── sessions/
│       └── {session_id}/
│           ├── transcript.jsonl       # 原始对话记录
│           ├── whiteboard.md          # 白板终态
│           ├── digest.md              # 讨论纪要
│           └── metadata.json          # 场次元数据
│
└── tests/                             # 测试
```

---

## 五、配置规格

所有关键变量均通过 `config/default.yaml` 配置，支持 `config/local.yaml` 覆盖。

**配置加载优先级**：

```
环境变量 (SALON_*) > local.yaml > default.yaml > 代码中的默认值
```

**关键可配置项速查**：

| 分类 | 配置项 | 默认值 | 说明 |
|------|--------|--------|------|
| LLM | `llm.api_base` | OpenAI | API 端点 |
| LLM | `llm.model` | gpt-4o | 模型名称 |
| LLM | `llm.temperature` | 0.8 | 生成温度 |
| 讨论 | `discussion.max_rounds` | 50 | 最大轮次 |
| 讨论 | `discussion.min_rounds` | 10 | 最少轮次 |
| 讨论 | `discussion.max_speech_chars` | 1000 | 发言字数上限 |
| 记忆 | `memory.conversation_stream.recent_messages_count` | 12 | 保留完整消息数 |
| 记忆 | `memory.whiteboard.auto_update_interval` | 5 | 白板同步间隔（轮） |
| 记忆 | `memory.whiteboard.compression_threshold_chars` | 800 | 白板压缩阈值 |
| 记忆 | `memory.whiteboard.cold_storage_ttl` | 4 | 冷板凳TTL（轮） |
| 上下文 | `context.max_prompt_tokens` | 12000 | Prompt token 上限 |
| 人类 | `human.default_role` | observer | 人类默认角色 |
| 人类 | `human.input_timeout` | 30 | 人类输入超时（秒） |
| 监控 | `monitor.enabled` | true | 是否启用轮次监控 |
| 监控 | `monitor.density_high_threshold` | 3.0 | 高密度阈值 |
| 监控 | `monitor.consecutive_high_trigger` | 3 | 连续高密度触发轮数 |
| 监控 | `monitor.rounds_since_story_trigger` | 5 | 无故事触发轮数 |
| 监控 | `monitor.rounds_since_anchor_trigger` | 8 | 未回锚触发轮数 |
| 监控 | `monitor.dormant_concept_threshold` | 3 | 概念休眠阈值 |
| 监控 | `monitor.extend_ratio_threshold` | 0.8 | Extend占比阈值 |

---

## 六、渐进式实现路线

### V0.1 — MVP ✅

- [x] 项目脚手架（目录结构、配置加载、依赖管理）
- [x] LLM 客户端（OpenAI 兼容、重试、超时、结构化输出）
- [x] Agent 基类 + Soul 系统加载
- [x] 主持人决策式发言调度（替代轮询）
- [x] 对话流（滑动窗口 + 渐进式摘要）
- [x] 原始记录持久化（transcript.jsonl 实时写入）
- [x] CLI 基础交互
- [x] 共享白板机制
- [x] 上下文窗口管理（token预算 + 截断）
- [x] 结构化输出解析（SpeechOutput / SpeakIntent）
- [x] 记录员后台白板同步

### V0.2 — Round Monitor + 概念管理 ✅

- [x] Round Monitor 轮次信号计算器
- [x] 主持人信号注入（条件性）
- [x] 呼吸空间机制（参与者 round_info 注入）
- [x] 概念账本（白板 active_concepts 板块）
- [x] 意图分布追踪
- [x] 讨论纪要自动生成

### V0.3 — 议题战略系统 ✅

- [x] 记录员每轮结构化分析（RoundAnalysis）
- [x] 维度地图（白板 dimension_map 板块）
- [x] 战略家 Agent（维度空间管理、方向决策）
- [x] 维度地图初始化（留白机制）
- [x] 收敛检测（维度锁定 + 维度发现停滞）
- [x] 战术调度改造（Shortlist 优先级排序）
- [x] 主持人瘦身（职责分离）
- [x] 战略方向注入（锚定问题 + 维度约束）
- [x] 强制点名机制（preferred_agents 中 energy=0 的 agent）

### V0.4 — 完整记忆 + 产出物

- [ ] 档案馆系统（归档、索引）
- [ ] 档案检索引擎（keyword → hybrid）
- [ ] 跨场次记忆注入
- [ ] 笔记本版本历史

### V1.0 — Web 界面

- [ ] 后端 API（FastAPI）
- [ ] Web 前端（前后端分离）
- [ ] 实时对话流展示
- [ ] 白板可视化

---

## 七、已废弃的设计

| 废弃设计 | 废弃原因 |
|---------|---------|
| `scheduler.py` 加权评分调度器 | 固定评分规则无法适应各种讨论情况，改为完全由主持人LLM判断 |
| 记录员在对话流中发言 | 与主持人职责重叠，导致控场能力分散。记录员改为纯后台角色 |
| `topic_exhaustion_check` 独立检查函数 | 功能已整合到主持人的 `decide_agenda_and_speakers` 中 |
| `detect_repetition()` / `detect_concept_confusion()` 独立函数 | 功能已通过 Round Monitor 的信号机制和主持人prompt实现 |
| SpeakIntent 的 `relevance` 字段 | 简化为只保留 `intent_type` 和 `target` |
| 主持人全栈决策（感知+战略+战术） | 拆分为记录员（感知）+ 战略家（战略）+ 主持人（战术）三层 |
| 主持人的 `speaker_focus` 字段 | 已移交记录员的 `RoundAnalysis.arguments` |
| 主持人的 `agenda_note` 字段 | 已移交战略家的 `DirectionGuidance` |
| 主持人的 `perception_summary` 字段 | 已移交信号系统的 `ControlSignals` |
| 加减分战略约束（STRATEGY_BOOST） | 被 Shortlist 优先级排序替代，避免调参困难 |
| `avoid_agents` 列表 | 战略家只指定 preferred，不指定 avoid。全员进入候选池 |

---

*本文档版本 0.3，与当前代码实现同步。*
