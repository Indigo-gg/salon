# Salon 多智能体对话协作系统 — 技术规格文档

> 版本：0.2 | 最后更新：2026-06-02

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
     │  Manager       │ │  Agent      │ │  Interface│ │  (transcript│
     │  (上下文        │ │  (主持人     │ │  (人类     │ │   digest)   │
     │   管理器)       │ │   议程决策)  │ │   接口)   │ │             │
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

系统中有三类角色，职责边界清晰：

| 角色 | 类型 | 是否参与对话流 | 核心职责 |
|------|------|--------------|---------|
| **主持人 (Moderator)** | 系统级Agent | ✅ 每轮参与 | 唯一的议程控制者：选择发言人、发布notice、阶段判断、议程指引 |
| **记录员 (Scribe)** | 系统级Agent | ❌ 后台运行 | 白板维护 + 概念账本维护 + 会后纪要生成 |
| **参与者 (Participant)** | 普通Agent | ✅ 被主持人选中后发言 | 基于Soul人格进行思想交锋 |

**设计决策**：议程控制能力完全集中于主持人。记录员专注于记录和白板维护，不参与对话流。这是经过多轮迭代后的架构选择——早期版本中记录员和主持人职责重叠，导致控场能力分散。

### 2.3 数据流图（单轮发言）

```
                    ┌─────────────────────────────────┐
                    │          Orchestrator            │
                    │   (主循环：while round < max)     │
                    └───────────────┬─────────────────┘
                                    │
                    ① 意图收集（并发）
                                    │
                    ┌───────────────▼─────────────────┐
                    │     所有参与者并行生成 SpeakIntent  │
                    │     (轻量LLM调用，返回JSON)        │
                    └───────────────┬─────────────────┘
                                    │
                    ② Round Monitor 计算信号
                                    │
                    ┌───────────────▼─────────────────┐
                    │        RoundMonitor              │
                    │                                  │
                    │  - 密度信号（概念计数趋势）         │
                    │  - 节奏信号（距上次故事的轮数）      │
                    │  - 锚定信号（距上次回锚的轮数）      │
                    │  - 概念信号（孤立概念清单）          │
                    │  - 意图信号（Extend占比）           │
                    └───────────────┬─────────────────┘
                                    │
                    ③ 主持人决策（注入信号）
                                    │
                    ┌───────────────▼─────────────────┐
                    │     Moderator.decide_agenda()    │
                    │                                  │
                    │  - 选择本轮发言人（最多N/2+1人）    │
                    │  - 驳回跑题意图                    │
                    │  - 发布notice（可选）              │
                    │  - 判断当前阶段                    │
                    │  - 写下议程指引                    │
                    │  - 条件性接收Round Monitor信号     │
                    └───────────────┬─────────────────┘
                                    │
                    ④ 串行发言（被选中者依次发言）
                                    │
                    ┌───────────────▼─────────────────┐
                    │     参与者.speak()               │
                    │                                  │
                    │  注入：                           │
                    │  - Soul人格 + 行为规则             │
                    │  - 白板（聚焦版）                  │
                    │  - 近期对话 + 摘要历史              │
                    │  - 发言意图提醒                    │
                    │  - 呼吸空间建议（条件性）           │
                    └───────────────┬─────────────────┘
                                    │
                    ⑤ 后处理
                                    │
                    ┌───────────────▼─────────────────┐
                    │  a. 发言 → ConversationStream    │
                    │  b. 发言 → Transcript (JSONL)    │
                    │  c. 检查是否需要摘要化旧消息       │
                    │  d. 每5轮触发白板同步（记录员）    │
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
               a. 并发收集所有参与者的 SpeakIntent
               b. RoundMonitor.compute() 计算轮次信号
               c. Moderator.decide_agenda_and_speakers() 决策（注入信号）
               d. 被选中的参与者依次 speak()
            3. 每5轮触发 Scribe.sync_whiteboard()
            4. 检查是否需要摘要化旧消息
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

每位参与者 Agent 拥有独立的「灵魂档案」（soul.md）。主持人和记录员没有 soul 文件，而是通过角色约束文件（`moderator_role.md` / `scribe_role.md`）定义行为。

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

**角色约束文件**（主持人/记录员）：

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
    - role: 角色类型 (moderator / participant / scribe)
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

#### 3.2.3 主持人 Agent

**文件**：`src/agents/moderator.py`

主持人是唯一的议程控制者。每轮都参与决策，但不直接参与对话流中的发言。

```python
class AgendaDecision(BaseModel):
    """主持人的结构化决策输出"""
    notice: str = ""                    # 全局广播通知（可选）
    reject_intents: list[str] = []      # 被驳回的Agent ID
    speakers: list[str]                 # 排序后的获准发言者列表
    phase: str = "EXPLORATION"          # OPENING/EXPLORATION/DEEPENING/CONVERGENCE/CLOSING
    agenda_note: str = ""               # 对下一步方向的判断（写入议程轨迹，下轮可见）


class ModeratorAgent(BaseAgent):
    def decide_agenda_and_speakers(
        self,
        context: DiscussionContext,
        intents: dict[str, str],         # {agent_id: "[intent_type] summary"}
        llm: LLMClient,
        max_speakers: int = 3,
        signals: RoundSignals | None = None,  # Round Monitor 信号（条件性注入）
    ) -> AgendaDecision:
        """
        根据当前讨论局势和所有参与者的意图，决定议程和发言顺位。

        决策流程：
        1. 审阅白板、议程轨迹、近期对话、所有举手意图
        2. 选择最有价值的发言人（最多 max_speakers 人）
        3. 驳回跑题或废话意图
        4. 如需干预，填写 notice
        5. 判断当前讨论阶段
        6. 写下议程指引（agenda_note）

        如果收到 Round Monitor 信号，会在 prompt 中条件性追加：
        - 密度警报（连续高密度轮次）
        - 着陆提示（长时间无具体故事）
        - 锚定提示（长时间未回锚原始问题）
        - 概念清单（孤立的隐喻/术语）
        - 意图失衡（Extend占比过高）
        """
        ...
```

**主持人方法论**（定义在 `config/roles/moderator_role.md`）：

1. **经验检验**：用现实场景检验宏大断言
2. **海拔调节**：动态调节讨论的抽象↔具体程度
3. **揭示隐含假设**：摊开双方未说出的前提
4. **思想实验**：构建具体处境打破理论僵局
5. **光谱映射**：帮助看到非黑即白之间的灰色地带

#### 3.2.4 参与者 Agent

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

#### 3.2.5 记录员 Agent

**文件**：`src/agents/scribe.py`

记录员是后台白板管理员，**不参与对话流**。

```python
class WhiteboardOperation(BaseModel):
    """白板操作"""
    action: str      # rewrite / add / clear_section / delete
    section: str     # 目标板块（不可操作 agenda_trace）
    content: str     # 操作内容

class WhiteboardSync(BaseModel):
    """白板同步结果"""
    operations: list[WhiteboardOperation]


class ScribeAgent(BaseAgent):
    def sync_whiteboard(
        self,
        context: DiscussionContext,
        llm: LLMClient,
        whiteboard_chars: int = 0,
        compression_threshold: int = 0,
    ) -> WhiteboardSync | None:
        """
        后台白板同步（不发言，只更新白板）。

        触发条件：
        1. 每 auto_update_interval 轮（默认5轮）
        2. 白板活跃内容超过 compression_threshold_chars（默认800字）

        职责：
        - 更新 current_focus（疑问句形式）
        - 更新 discussion_phase
        - 合并/清理冗余分歧（Diff & Merge）
        - 压缩超载内容（子弹笔记风格）
        - 维护 active_concepts（概念账本）
        """
        ...

    def generate_digest(self, topic, transcript_text, whiteboard_text, whiteboard_sections, llm) -> str:
        """会后生成讨论纪要"""
        ...

    def generate_overview(self, topic, transcript_text, whiteboard_sections, round_count, participant_names, llm) -> str:
        """会后生成讨论总览"""
        ...
```

**记录员职能约束**（定义在 `config/roles/scribe_role.md`）：

- **白板维护**：维护共享白板的所有板块（agenda_trace 除外）
- **概念账本维护**：追踪活跃的隐喻/术语/概念，标记孤立概念
- **会后纪要**：在讨论结束后生成结构化纪要和总览

---

### 3.3 Round Monitor（轮次信号计算器）

**文件**：`src/core/round_monitor.py`

轻量级的纯函数模块，不依赖 LLM，用文本分析计算每轮的信号。信号以条件性文本注入主持人 prompt 和参与者 round_info，仅在问题出现时激活。

#### 3.3.1 信号数据结构

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

#### 3.3.2 计算方法

| 信号 | 计算方式 | 无额外LLM调用 |
|------|---------|:---:|
| 密度 | 统计每轮发言中的中文标点分隔短语数（粗略概念计数） | ✅ |
| 故事检测 | 匹配"比如"、"想象"、"曾经"等故事引入标记词 | ✅ |
| 锚定检测 | 匹配原始topic关键词在当前发言中的出现频率 | ✅ |
| 概念追踪 | 维护内部概念注册表，跟踪引入和引用轮次 | ✅ |
| 意图追踪 | 统计最近5轮的意图类型分布 | ✅ |

#### 3.3.3 信号注入机制

信号是**条件性**的——只在问题出现时才注入，正常运行时零开销：

```python
# 模块级函数，可被 moderator 直接导入
def build_moderator_signals(config: MonitorConfig, signals: RoundSignals) -> str:
    """仅在问题出现时返回非空字符串。"""
    parts = []
    if signals.consecutive_high_density >= config.consecutive_high_trigger:
        parts.append("⚠️ 【密度警报】...")
    if signals.rounds_since_story >= config.rounds_since_story_trigger:
        parts.append("⚠️ 【着陆提示】...")
    if signals.rounds_since_anchor >= config.rounds_since_anchor_trigger:
        parts.append("⚠️ 【锚定提示】...")
    if signals.orphaned_concepts:
        parts.append("📋 【概念清单】...")
    if extend_ratio_too_high:
        parts.append("⚠️ 【意图失衡】...")
    return "\n".join(parts)

def build_breathing_hints(config: MonitorConfig, signals: RoundSignals) -> str:
    """连续高密度+长时间无故事时，返回呼吸空间建议。"""
    ...
```

#### 3.3.4 设计特性

| 特性 | 说明 |
|------|------|
| 零开销正常运行 | 信号只在问题出现时才注入文本 |
| 不引入新LLM调用 | 纯文本分析 |
| 不改变agent行为规则 | 只改变agent能看到的信息 |
| 所有参数可配 | 通过 `config/default.yaml` 的 `monitor` 段调整 |
| 通用性 | 支持不同沙龙类型（哲学/文学/经济/艺术） |

---

### 3.4 记忆系统

#### 3.4.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  共享白板 (Whiteboard)                                       │
│  生命周期：单场次                                              │
│  所有者：记录员维护，所有参与者可读                               │
│  存储：data/sessions/{session_id}/whiteboard.md               │
│  访问：每轮发言时注入 Prompt（全景版给主持人，聚焦版给参与者）      │
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
    """

    def update(self, section: str, action: str, content: str, round_num: int, added_by: str) -> None:
        """
        更新白板条目。

        action: add / remove / delete / modify / rewrite / clear_section
        """
        ...

    def to_prompt_text(self, current_round: int = 0) -> str:
        """全景版白板（供主持人决策）。包含所有活跃板块。议程轨迹保留首条+最近3条。"""
        ...

    def to_brief_prompt_text(self) -> str:
        """聚焦版白板（供参与者发言）。仅 current_focus + disagreements。"""
        ...
```

**白板视野分离**：

| 版本 | 使用者 | 内容 | 用途 |
|------|--------|------|------|
| `to_prompt_text()` | 主持人 | 全部活跃板块 | 战略决策 |
| `to_brief_prompt_text()` | 参与者 | 仅焦点+分歧 | 发言时的轻量导航 |

**冷板凳机制**：条目超过 `cold_storage_ttl` 轮（默认4轮）未更新则标记为 `cold=True`，保留在内存但不再喂给 LLM。

#### 3.4.4 上下文管理器 (Context Manager)

**文件**：`src/core/context_manager.py`

```python
class ContextManager:
    """
    负责为每个 Agent 的每次发言组装完整的上下文。

    Prompt 结构（从上到下）：
    ┌─────────────────────────────────────────────┐
    │  System Prompt + Soul + 行为规则              │  ~1300 tokens
    ├─────────────────────────────────────────────┤
    │  摘要化的早期对话 (Summarized History)        │  ~2000 tokens
    ├─────────────────────────────────────────────┤
    │  最近的原始对话 (Recent Messages)             │  ~5000 tokens
    ├─────────────────────────────────────────────┤
    │  共享白板 (Whiteboard) + 行动指令             │  ~1500 tokens
    └─────────────────────────────────────────────┘
    总预算：~12000 tokens
    """

    def build_context(self, agent: BaseAgent, memory: MemorySystem, round_number: int) -> DiscussionContext:
        """为指定 Agent 构建上下文。按优先级截断超出预算的部分。"""
        ...

    def _truncate_to_budget(self, sections: dict[str, str]) -> dict[str, str]:
        """
        截断优先级（从先截到后截）：
        1. summarized_history
        2. whiteboard
        3. recent_messages（保留最新的）
        4. system_prompt + soul（绝不截断）
        """
        ...
```

---

### 3.5 发言结构化输出

#### 3.5.1 发言意向 (SpeakIntent)

```python
class SpeakIntent(BaseModel):
    summary: str                    # 一句话概括想说什么
    intent_type: str                # Extend / Dissent / New_Angle / Clarify / Ask / Pass
    target: str | None              # 如果是回应某人，标注目标角色名
```

#### 3.5.2 发言输出 (SpeechOutput)

```python
class SpeechOutput(BaseModel):
    review: str | None              # 信息咀嚼：客观梳理对话流，盘点他人观点
    thought: str | None             # 逻辑推演：作为角色的内在思考过程（CoT）
    speech: str                     # 正式开口：最终公开发表的发言内容
    speech_type: str                # Extend / Dissent / New_Angle / Clarify / Ask / Pass
    mentions: list[str]             # 本次发言中回应的角色名列表
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
│   └── specification.md               # 本规格文档
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
│       └── scribe_role.md
│
├── src/
│   ├── main.py                        # 程序入口
│   ├── config.py                      # 配置加载
│   │
│   ├── core/
│   │   ├── orchestrator.py            # 协调器（主控）
│   │   ├── round_monitor.py           # 轮次信号计算器
│   │   ├── context_manager.py         # 上下文窗口管理
│   │   └── session.py                 # 场次生命周期管理
│   │
│   ├── agents/
│   │   ├── base.py                    # Agent 基类 + 数据结构
│   │   ├── soul.py                    # Soul 系统
│   │   ├── moderator.py              # 主持人 Agent
│   │   ├── participant.py            # 参与者 Agent
│   │   └── scribe.py                 # 记录员 Agent
│   │
│   ├── memory/
│   │   ├── __init__.py                # MemorySystem
│   │   ├── stream.py                  # 对话流管理
│   │   └── whiteboard.py              # 共享白板
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

### V0.3 — 完整记忆 + 产出物

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

以下设计在早期版本中存在但已被废弃：

| 废弃设计 | 废弃原因 |
|---------|---------|
| `scheduler.py` 加权评分调度器 | 固定评分规则无法适应各种讨论情况，改为完全由主持人LLM判断 |
| 记录员在对话流中发言 | 与主持人职责重叠，导致控场能力分散。记录员改为纯后台角色 |
| `topic_exhaustion_check` 独立检查函数 | 功能已整合到主持人的 `decide_agenda_and_speakers` 中 |
| `detect_repetition()` / `detect_concept_confusion()` 独立函数 | 功能已通过 Round Monitor 的信号机制和主持人prompt实现 |
| SpeakIntent 的 `relevance` 字段 | 简化为只保留 `intent_type` 和 `target` |

---

*本文档版本 0.2，与当前代码实现同步。*
