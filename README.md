
# 🏛️ Salon — 多智能体对话协作系统

<p align="center">
  <img src="docs/logo.jpg" width="300" alt="Salon Logo">
</p>

> *灵感源自 18 世纪法国沙龙——思想在对话中碰撞，而非在会议室里表决。*

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](LICENSE)

**Salon** 是一个多 Agent 对话协作系统，让 3–5 位拥有独立人格的 AI Agent 围绕议题展开深度讨论。系统的核心理念是：

- 🎭 **过程即产出** — 对话过程本身比最终报告更有价值
- 🌊 **发散优先，收敛随后** — 不急于达成共识
- ⚖️ **尊重未解决的分歧** — 忠实记录各方立场

---

## 📖 目录

- [核心特性](#-核心特性)
- [技术栈](#-技术栈)
- [项目结构](#-项目结构)
- [快速开始](#-快速开始)
- [讨论模式](#-讨论模式)
- [Web API](#-web-api)
- [人类控制指令](#-人类控制指令)
- [配置说明](#-配置说明)
- [设计哲学](#-设计哲学)
- [许可证](#-许可证)

---

## ✨ 核心特性

| # | 特性 | 说明 |
|---|------|------|
| 1 | 🏛️ **沙龙式对话** | 3–5 位 AI Agent 围绕议题展开多轮深度讨论 |
| 2 | 🧬 **Soul 系统** | 每位参与者拥有独立的人格档案（`soul.md`），不只是简单的角色设定 |
| 3 | 🧠 **多层记忆架构** | 对话流 (Stream) → 个人笔记 (Notebook) → 共享白板 (Whiteboard) → 跨场次存档 (Archive) |
| 4 | 🎯 **智能发言调度** | 基于关联度权重的有机发言顺序，由主持人判断议题是否充分讨论 |
| 5 | 🤝 **人类三模式介入** | 主持人 / 参与者 / 观察者（默认观察者） |
| 6 | 📄 **产出物体系** | 实时原始记录、自动生成的讨论纪要、终稿报告 |
| 7 | 🎬 **多种讨论模式** | 沙龙 (Salon)、辩论 (Debate)、采访 (Interview) |
| 8 | 👥 **Agent 分组管理** | 支持自定义 Agent 组合，快速创建讨论场次 |
| 9 | 🖥️ **Web UI** | Vue 3 前端 + FastAPI 后端，可视化管理对话全流程 |

---

## 🛠️ 技术栈

| 类别 | 选型 |
|------|------|
| 语言 | Python 3.11+ |
| LLM 接口 | 兼容 OpenAI API 规范（支持任何兼容的提供商） |
| 存储 | 文件系统（JSON / JSONL / Markdown / YAML） |
| 后端 API | FastAPI + Uvicorn + SSE（Server-Sent Events） |
| 前端 | Vue 3 + Vite + Vue Router + Pinia |
| CLI | 命令行交互模式 |
| 包管理 | pip + requirements.txt（后端）/ npm（前端） |

---

## 📁 项目结构

```
agent-team/
├── README.md
├── requirements.txt
│
├── docs/
│   ├── specification.md                  # 技术规格文档
│   └── mode-extension-guide.md           # 讨论模式扩展指南
│
├── config/
│   ├── default.yaml                      # 系统默认配置
│   ├── agents/                           # Agent 配置（JSON 格式）
│   │   ├── philosopher_east.json
│   │   ├── philosopher_west.json
│   │   ├── scientist.json
│   │   ├── marxist.json
│   │   ├── existentialist.json
│   │   └── ...
│   ├── souls/                            # Agent 人格档案
│   │   ├── philosopher_east.md
│   │   ├── philosopher_west.md
│   │   ├── scientist.md
│   │   ├── marxist.md
│   │   └── ...
│   ├── groups/                           # Agent 分组配置
│   ├── roles/                            # 角色提示词（主持人、记录员等）
│   └── local.yaml                        # 本地覆盖配置（不入库）
│
├── src/
│   ├── __init__.py
│   ├── main.py                           # CLI 入口
│   ├── api.py                            # API 入口
│   ├── config.py                         # 配置加载
│   │
│   ├── core/                             # 核心引擎
│   │   ├── orchestrator.py               # 协调器（主控状态机）
│   │   ├── session.py                    # 场次生命周期
│   │   ├── context_manager.py            # 上下文窗口管理
│   │   ├── scheduling_state.py           # 调度状态
│   │   ├── round_monitor.py              # 轮次监控
│   │   ├── injection_router.py           # 注入指令路由
│   │   ├── modes/                        # 讨论模式
│   │   │   ├── base.py                   # 模式基类
│   │   │   ├── salon.py                  # 沙龙模式
│   │   │   ├── debate.py                 # 辩论模式
│   │   │   └── interview.py              # 采访模式
│   │   └── moderator_signal/             # 主持人信号系统
│   │       ├── sensors.py                # 信号传感器
│   │       ├── observer.py               # 观察者
│   │       └── injector.py               # 注入器
│   │
│   ├── agents/                           # Agent 实现
│   │   ├── base.py                       # Agent 基类
│   │   ├── moderator.py                  # 主持人 Agent
│   │   ├── participant.py                # 参与者 Agent
│   │   ├── scribe.py                     # 记录员 Agent
│   │   └── soul.py                       # 人格档案加载
│   │
│   ├── memory/                           # 记忆系统
│   │   ├── stream.py                     # 对话流（滑动窗口）
│   │   ├── whiteboard.py                 # 共享白板
│   │   └── agent_memory.py               # Agent 个人记忆
│   │
│   ├── human/                            # 人类交互
│   │   ├── interface.py                  # 人类交互接口
│   │   └── commands.py                   # 控制指令解析
│   │
│   ├── llm/                              # LLM 接口层
│   │   ├── client.py                     # OpenAI 兼容客户端
│   │   └── prompts.py                    # Prompt 模板
│   │
│   ├── tools/                            # 工具集
│   │   └── search.py                     # 搜索工具
│   │
│   └── output/                           # 产出物生成
│       ├── transcript.py                 # 原始记录
│       ├── digest.py                     # 讨论纪要
│       ├── report.py                     # 终稿报告
│       └── export.py                     # 导出工具
│
├── web/                                  # Web UI 模块
│   ├── api/                              # FastAPI 后端
│   │   ├── main.py                       # API 入口（FastAPI app）
│   │   ├── manager.py                    # WebOrchestrator（后台线程运行对话）
│   │   ├── models.py                     # 请求/响应数据模型
│   │   └── routes/                       # API 路由
│   │       ├── sessions.py               # 场次管理
│   │       ├── chat.py                   # 对话 SSE 流 + 指令发送
│   │       ├── agents.py                 # Agent 管理
│   │       ├── groups.py                 # 分组管理
│   │       ├── archive.py                # 存档浏览
│   │       ├── config.py                 # 配置查看/修改
│   │       └── tts.py                    # TTS 接口
│   └── frontend/                         # Vue 3 前端
│       ├── src/
│       │   ├── views/                    # 页面视图
│       │   │   ├── Home.vue              # 首页
│       │   │   ├── ChatRoom.vue          # 聊天室
│       │   │   ├── Agents.vue            # Agent 管理
│       │   │   ├── Groups.vue            # 分组管理
│       │   │   ├── Archive.vue           # 存档浏览
│       │   │   ├── ArchivePlay.vue       # 存档回放
│       │   │   └── Settings.vue          # 设置
│       │   ├── components/               # 通用组件
│       │   └── stores/                   # Pinia 状态管理
│       ├── package.json
│       └── vite.config.js
│
├── scripts/                              # 工具脚本
│   └── normalize_sprites.py
│
└── data/                                 # 运行时数据（自动创建，不入库）
    ├── sessions/                         # 场次数据
    └── export/                           # 导出文件
```

---

## 🚀 快速开始

### 1. 安装

```bash
git clone <repo-url>
cd agent-team
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制默认配置
cp config/default.yaml config/local.yaml
```

编辑 `config/local.yaml`，设置你的 LLM API 密钥和端点：

```yaml
llm:
  api_key: "sk-your-api-key"
  base_url: "https://api.openai.com/v1"
  model: "gpt-4"
```

### 3. 运行

#### CLI 模式

```bash
# 🏛️ 启动一场哲学对话
python -m src.main --config config/local.yaml --topic "自由意志是否存在？"

# 👥 指定参与者数量
python -m src.main --config config/local.yaml --topic "意识的本质" --participants 4

# 🎤 以主持人模式介入
python -m src.main --config config/local.yaml --topic "AI伦理" --human-role chair
```

#### Web UI 模式

Web UI 采用前后端分离架构，需要分别启动后端 API 和前端开发服务器。

```bash
# 1. 安装前端依赖
cd web/frontend
npm install
cd ../..

# 2. 启动后端 API（默认 http://localhost:8000）
uvicorn web.api.main:app --reload --host 0.0.0.0 --port 8000

# 3. 另开终端，启动前端开发服务器（默认 http://localhost:5173）
cd web/frontend
npm run dev
```

打开浏览器访问 `http://localhost:5173`，即可通过 Web 界面创建场次、选择参与者、发起对话并通过 SSE 实时查看讨论进展。

> **💡 提示**：如果只需生产部署，可先执行 `cd web/frontend && npm run build` 构建前端产物，后端会自动挂载 `web/frontend/dist` 下的静态文件，访问 `http://localhost:8000` 即可使用完整应用。

---

## 🎬 讨论模式

系统支持多种讨论模式，每种模式有不同的对话结构和规则：

| 模式 | 说明 |
|------|------|
| 🏛️ **Salon（沙龙）** | 默认模式。自由讨论，有机发言，主持人引导深度探索 |
| ⚔️ **Debate（辩论）** | 正反方阵营对抗，结构化攻防，记录员中立记录 |
| 🎤 **Interview（采访）** | 一对一深度访谈，主持人引导提问 |

> 📘 模式扩展指南详见 [`docs/mode-extension-guide.md`](docs/mode-extension-guide.md)。

---

## 🔌 Web API

后端提供以下 REST API 端点（启动后访问 `http://localhost:8000/docs` 查看 Swagger 文档）：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/agents` | GET | 获取可用 Agent 列表 |
| `/api/agents/{id}` | GET/PUT | 获取/编辑 Agent 配置 |
| `/api/groups` | GET/POST | 分组列表/创建分组 |
| `/api/groups/{id}` | GET/PUT/DELETE | 分组详情/编辑/删除 |
| `/api/config` | GET/PUT | 查看/修改运行时配置 |
| `/api/sessions` | POST | 创建新场次 |
| `/api/sessions` | GET | 列出所有场次 |
| `/api/sessions/{id}` | GET | 获取场次详情 |
| `/api/sessions/{id}/start` | POST | 启动/恢复对话 |
| `/api/sessions/{id}/stream` | GET | SSE 实时事件流 |
| `/api/sessions/{id}/command` | POST | 发送控制指令（pause/resume/ask 等） |
| `/api/archive` | GET | 存档列表 |
| `/api/archive/{id}` | GET | 存档详情 |

SSE 事件类型：`message`（新发言）、`status`（状态变更）、`whiteboard`（白板更新）、`notebook`（笔记本更新）、`system`（系统消息）、`done`（对话结束）。

---

## 🎮 人类控制指令

在讨论进行中，人类可以通过以下指令介入：

| 指令 | 说明 |
|------|------|
| `/pause` | ⏸️ 暂停讨论（当前发言者说完后暂停） |
| `/resume` | ▶️ 恢复讨论 |
| `/ask @角色 问题` | 💬 向特定角色提问 |
| `/topic 新议题` | 🔄 引入新议题 |
| `/summarize` | 📋 触发主持人做中场总结 |
| `/whiteboard` | 🖊️ 查看当前白板 |
| `/notebook` | 📓 查看 Agent 个人笔记 |
| `/end` | 🏁 结束讨论，生成最终总结 |
| `/inject @角色 指令` | 💉 向某角色注入私有指令 |
| `/skip` | ⏭️ 跳过当前发言者 |
| `/status` | 📊 查看当前状态 |

> **💡 提示**：默认以「观察者」模式加入讨论，你可以静静旁观 AI 之间的对话，在任何时刻通过指令介入。

---

## ⚙️ 配置说明

所有关键变量均可通过 `config/default.yaml` 配置：

| 配置类别 | 包含内容 |
|----------|----------|
| **LLM 连接** | API 地址、模型、温度、超时等 |
| **讨论参数** | 最大轮次、发言字数限制、超时时间等 |
| **发言调度** | 关联度权重、沉默阈值等 |
| **上下文窗口** | 各层记忆的 Token 分配比例 |
| **人类介入** | 默认角色、指令前缀等 |
| **产出物格式** | 记录格式、纪要模板等 |

Agent 人格档案存放在 `config/souls/` 下（Markdown 格式），Agent 配置存放在 `config/agents/` 下（JSON 格式）。

> 📘 完整技术规格详见 [`docs/specification.md`](docs/specification.md)。

---

## 💭 设计哲学

> **「沙龙，而非会议室。」**

本系统的设计围绕五个核心原则：

- 🎭 **过程即产出** — 讨论过程本身有独立价值，报告只是副产品
- 🌊 **有机流动** — 发言顺序不是机械轮转，而是由关联度自然涌现
- 🔬 **深度优先** — 主持人智能判断议题是否被充分讨论，而非固定轮次
- ⚖️ **尊重分歧** — 无法达成共识的问题被忠实记录为开放性分歧
- 📝 **隐式思考流** — Agent 在发言前通过内在的逻辑推演 (CoT) 完善思考

```
        ┌─────────────────────────────────────────────┐
        │              🏛️  沙 龙 对 话                │
        │                                             │
        │   🧑‍🏫 主持人    🧙 哲学家    🔬 科学家       │
        │       ↕           ↕           ↕             │
        │   ┌─────────────────────────────────┐       │
        │   │     💬  对 话 流 (Stream)        │       │
        │   └──────────────┬──────────────────┘       │
        │                  │                          │
        │                  ▼                          │
        │               🖊️ 白板                       │
        │              (共享知识)                     │
        └─────────────────────────────────────────────┘
```

---

## 📜 许可证

本项目基于 [CC BY-NC 4.0](LICENSE) 许可证发布，禁止商业使用。

---

<p align="center">
  <i>「真正的智慧不在于答案，而在于对话本身。」</i>
</p>
