# 模式扩展指南

本文档记录如何为 Salon 系统新增一个对话模式。基于沙龙（salon）、会谈（interview）、辩论（debate）三个模式的实践经验总结。

## 一、扩展一个新模式需要做什么

### 后端（Python）

| 步骤 | 文件 | 说明 |
|------|------|------|
| 1. 定义策略类 | `src/core/modes/xxx.py` | 继承 `DialogueModeStrategy`，实现 4 个方法 |
| 2. 注册模式 | `src/core/modes/__init__.py` | 在 `_MODE_REGISTRY` 中添加 |
| 3. 创建灵魂文件 | `config/souls/xxx_*.md` | 按模式需要创建角色（可选） |
| 4. 创建角色约束 | `config/roles/xxx_*.md` | 主持人/记录员的职能约束（可选） |
| 5. 配置 mode_config | 前端创建会话时传入 | 模式专属配置，存入 metadata.json |

### 前端（Vue）

| 步骤 | 文件 | 说明 |
|------|------|------|
| 1. 首页模式入口 | `views/Home.vue` | 在 `modes` 数组中添加新条目 |
| 2. 角色选择 | `views/Home.vue` | 如果有特殊选择逻辑（如辩论的正反方），用 `AgentRoster` 的 slot |
| 3. 讨论室 | `views/ChatRoom.vue` | 根据 mode 添加条件渲染（标签、指示器等） |
| 4. 回放 | `views/ArchivePlay.vue` | 同 ChatRoom，根据 mode 渲染专属元素 |

## 二、必须实现的接口

```python
class DialogueModeStrategy(ABC):
    @property
    def name(self) -> str:           # 模式名称，如 "debate"
    
    def setup(self, ctx, **kwargs):  # 初始化组件（主持人、记录员、信号系统等）
    
    def execute_round(self, ctx) -> int:  # 执行一轮，返回新的 round_num
    
    def should_continue(self, ctx) -> bool:  # 是否继续（可选覆盖）
    
    def get_mode_commands(self) -> dict:     # 特有命令（可选覆盖）
```

## 三、可复用的组件

### 后端

| 组件 | 说明 | 所有模式都需要？ |
|------|------|----------------|
| `ModeContext` | 共享上下文（config、memory、llm、participants 等） | ✅ 必须 |
| `Message` | 消息数据结构，支持 `faction` 等扩展字段 | ✅ 必须 |
| `MemorySystem` | 记忆系统（对话流 + 白板） | ✅ 必须 |
| `ContextManager` | 上下文窗口管理（token 预算） | ✅ 必须 |
| `TranscriptWriter` | JSONL 转录写入 | ✅ 必须 |
| `SessionManager` | 会话生命周期 | ✅ 必须 |
| `ModeratorAgent` | 主持人 agent | 看模式需要 |
| `ScribeAgent` | 记录员 agent | 看模式需要 |
| `RoundMonitor` | 信号监控（密度、锚定、可读性） | 沙龙需要，其他可选 |
| `ModeratorSignalSystem` | 三层信号系统 | 沙龙需要，其他可选 |
| `SchedulingState` | 调度防线（收敛递增、沉默保护） | 沙龙需要，其他可选 |

### 前端

| 组件 | 说明 | 位置 |
|------|------|------|
| `AgentRoster` | 角色选择器（已选区 + 待选区 + slot 按钮） | `components/AgentRoster.vue` |
| `ChatRoom` | 讨论室（消息流 + 舞台 + 输入框） | `views/ChatRoom.vue` |
| `ArchivePlay` | 回放页面 | `views/ArchivePlay.vue` |
| `DraggablePanel` | 可拖拽浮动面板 | `components/DraggablePanel.vue` |
| `WhiteboardPanel` | 白板显示 | `components/WhiteboardPanel.vue` |

## 四、数据存储结构

### metadata.json（会话元信息）

```json
{
  "session_id": "s_xxx",
  "topic": "讨论主题",
  "mode": "debate",
  "participants": ["agent1", "agent2", ...],
  "state": "running",
  "round_count": 15,
  "created_at": "2024-01-01T00:00:00",
  "mode_config": {
    // 模式专属配置，结构随 mode 变化
    // 沙龙: {} 或不存
    // 会谈: {} 或不存
    // 辩论: {"factions": {"agent1": "affirmative", ...}}
    // 未来: 任何需要恢复状态的数据
  }
}
```

### transcript.jsonl（消息流）

每行一个 JSON 对象，公共字段统一，扩展字段可选：

```json
{"id":"msg_0001","round":1,"agent_id":"a1","agent_name":"凌锋","agent_role":"participant","content":"...","speech_type":"Extend","mentions":[],"faction":"affirmative"}
```

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| id | string | ✅ | 消息唯一 ID |
| round | int | ✅ | 轮次号 |
| timestamp | string | ✅ | ISO 时间戳 |
| agent_id | string | ✅ | 发言者 ID |
| agent_name | string | ✅ | 发言者名称 |
| agent_role | string | ✅ | 角色（moderator/participant/scribe/host） |
| content | string | ✅ | 发言内容 |
| speech_type | string | ✅ | 类型（Extend/Dissent/New_Angle/Clarify/Ask/Pass/intent/question/system_notice） |
| mentions | list | ❌ | 被提及的 agent ID 列表 |
| faction | string | ❌ | 辩论专属：affirmative/negative |
| metadata | dict | ❌ | 通用扩展字段 |

**原则：公共字段保持统一，模式专属字段用可选字段扩展。回放页面根据 mode 决定渲染哪些字段。**

## 五、关键设计决策

### 1. mode_config 在创建时写入，不是运行时

```
用户在首页选好配置 → createSession 写入 metadata.json
→ 前端跳转 ChatRoom（需要 mode_config 渲染）
→ 后端 strategy.setup 从 metadata 读 mode_config
```

不要在 strategy.setup 中生成 mode_config — 前端在会话创建前就需要它。

### 2. 轮数统一由 max_rounds 控制

每个模式的策略内部自行分配各阶段轮数，但总轮数不超过 `config.discussion.max_rounds`。

```python
# 辩论示例：自动分配
constructive = constructive_per_side * 2
closing = closing_per_side * 2
free_debate = max_rounds - constructive - closing
```

这样用户在配置中只管设 max_rounds，不需要了解每个模式的内部结构。

### 3. ChatRoom 复用，不新建页面

沙龙和会谈已经证明 ChatRoom 可以通过条件渲染支持不同模式。辩论也复用 ChatRoom，通过 `v-if="isDebate"` 渲染专属元素。

如果某个模式的 UI 差异太大（如需要完全不同的布局），可以：
- 在 ChatRoom 中用动态组件 `<component :is="modeComponent">`
- 或新建页面，但复用消息渲染逻辑

### 4. 归档 API 无需改动

`GET /api/archives/{id}` 直接返回 metadata.json + transcript.jsonl。模式专属数据（mode_config、faction）自动保留。回放页面根据 mode 字段决定渲染逻辑。

### 5. 角色选择用 AgentRoster 组件

`AgentRoster` 提供已选区 + 待选区 + slot 按钮。不同模式通过 slot 自定义操作按钮：

```vue
<!-- 沙龙：默认"参与"按钮 -->
<AgentRoster :agents="agents" :selected="selected" @add="toggle" @remove="remove" />

<!-- 辩论：自定义"正方/反方"按钮 -->
<AgentRoster :agents="agents" :selected="selected" :factions="factions" @add="cycle" @remove="remove">
  <template #actions="{ agent }">
    <button @click.stop="setFaction(agent.id, 'affirmative')">正方</button>
    <button @click.stop="setFaction(agent.id, 'negative')">反方</button>
  </template>
</AgentRoster>
```

## 六、常见陷阱

### 1. 忘记在 metadata 中存 mode_config

如果 mode_config 只存在内存中，会话恢复/归档后前端拿不到阵营等信息。**创建会话时就写入 metadata.json。**

### 2. 消息中忘记写扩展字段

辩论的 `faction` 字段必须在 `_process_speech` 中传入 Message 构造函数。如果遗漏，回放时无法显示阵营标签。

### 3. 状态机没有与 max_rounds 对齐

如果辩论的内部轮数加起来超过 max_rounds，会导致循环提前结束或永远不停。用 `resolve_free_rounds(max_rounds)` 确保总和等于 max_rounds。

### 4. setup 中没有正确构建 all_agents

`ctx.all_agents` 必须包含 moderator + participants + scribe。如果遗漏，前端的角色列表会不完整。

### 5. 忘记注册模式

在 `__init__.py` 的 `_MODE_REGISTRY` 中添加条目，否则 `ModeFactory.create("xxx")` 会抛 ValueError。

## 七、模式对比表

| 维度 | 沙龙 (salon) | 会谈 (interview) | 辩论 (debate) |
|------|-------------|-----------------|--------------|
| 主持人 | AI 主持人（调度+场控） | 用户担任 | AI 主持人（程序推进） |
| 记录员 | 通用记录员 | 通用记录员 | 辩论记录员（论点追踪） |
| 调度方式 | 意图→LLM决策→发言 | 用户指定发言人 | 状态机驱动（固定顺序+启发式） |
| 信号系统 | ✅ 完整三层防线 | ❌ | ❌ |
| 白板结构 | 通用（共识/分歧/焦点） | 通用 | 辩论专属（正方/反方/交锋点） |
| 消息扩展 | intent 类型 | host 角色 | faction 字段 |
| mode_config | {} | {} | {factions: {...}} |
| 轮数控制 | max_rounds | 无限制（用户 /end） | max_rounds 自动分配 |
| 用户输入 | /ask, /skip, /inject | 直接发言, /approve | /debate（查看状态） |
