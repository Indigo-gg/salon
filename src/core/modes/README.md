# 对话模式策略系统

## 1. 概述

本模块实现了对话模式的策略模式抽象。不同对话模式（沙龙、会谈等）的调度逻辑封装在独立的策略类中，编排器（Orchestrator）只负责框架级的生命周期管理。

## 2. 架构

```
┌─────────────────────────────────────────────────┐
│  Orchestrator（框架层）                          │
│  - 生命周期管理（run → main_loop → wrap_up）     │
│  - 参与者加载                                    │
│  - 记忆/转录初始化                               │
│  - 框架级命令处理（/pause, /end, /status...）     │
│  - 渐进式摘要                                    │
│  - CLOSING 轮                                    │
└──────────────┬──────────────────────────────────┘
               │ 委托
               ▼
┌─────────────────────────────────────────────────┐
│  DialogueModeStrategy（策略接口）                │
│  - setup(ctx)        初始化模式组件              │
│  - execute_round(ctx) 执行一轮对话               │
│  - should_continue(ctx) 是否继续                 │
│  - get_mode_commands() 特有命令                  │
└──────────────┬──────────────────────────────────┘
               │ 实现
        ┌──────┴──────┐
        ▼             ▼
  SalonMode    InterviewMode
  (AI 自动)    (人类驱动)
```

## 3. 核心组件

### ModeContext — 模式上下文
策略能访问的共享状态，不直接持有编排器引用：
- `config`, `memory`, `context_manager`, `llm`, `transcript`, `session_manager`
- `participants`, `all_agents`
- 可选组件：`moderator`, `scribe`, `round_monitor`, `signal_system`, `scheduling_state`
- `command_source: CommandSource` — 统一的命令输入源
- `emit_event` — 事件回调（Web 模式用）

### CommandSource — 命令输入源
统一 CLI 和 Web 的输入接口：
- `try_get()` — 非阻塞获取
- `wait(timeout)` — 阻塞等待
- `CLITerminalCommandSource` — 基于 HumanInterface
- `WebCommandSource` — 基于 queue.Queue

### ModeFactory — 模式工厂
```python
from src.core.modes import ModeFactory

strategy = ModeFactory.create("salon")      # 创建策略
strategy.setup(ctx)                          # 初始化
ModeFactory.register("chaos", ChaosMode)     # 注册新模式
ModeFactory.available_modes()                # 列出可用模式
```

## 4. 现有模式

| 模式 | 策略类 | 主持人 | 信号系统 | 调度方式 |
|------|--------|--------|----------|---------|
| salon | SalonModeStrategy | ✅ AI 主持人 | ✅ 完整三层防线 | 意图→决策→发言 |
| interview | InterviewModeStrategy | ❌ | ❌ | 人类提问→举手→批准 |

## 5. 扩展新模式

1. 在 `src/core/modes/` 下创建新文件
2. 实现 `DialogueModeStrategy` 的 4 个抽象方法
3. 在 `__init__.py` 的 `_MODE_REGISTRY` 中注册
4. 前端/CLI 添加模式选项

示例：
```python
class RoundRobinMode(DialogueModeStrategy):
    name = "round_robin"
    
    def setup(self, ctx):
        ctx.moderator = None  # 不需要主持人
        ctx.scribe = ScribeAgent(...)
        self._idx = 0
    
    def execute_round(self, ctx):
        speaker = ctx.participants[self._idx % len(ctx.participants)]
        ctx.round_num += 1
        agent_ctx = ctx.context_manager.build_context(speaker, ctx.memory, ctx.round_num)
        output = speaker.speak(agent_ctx, ctx.llm, round_info="轮到你发言了。")
        _process_speech(ctx, speaker, output, ctx.round_num)
        self._idx += 1
        return ctx.round_num
```

## 6. CLI 与 Web 的统一

两种前端共享同一套策略实现，区别只在：
- **输入源**：CLI 用 `CLITerminalCommandSource`，Web 用 `WebCommandSource`
- **事件输出**：CLI 直接 `print()`，Web 通过 `emit_event` 回调推送到 SSE
- **生命周期**：CLI 单线程阻塞，Web 后台线程 + 队列通信
