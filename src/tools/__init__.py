"""工具模块：为 Agent 提供外部能力（搜索、检索等）。

设计原则：
- Tool 是最小的可执行单元，接受 dict 输入，返回 str 输出
- ToolRegistry 管理工具的注册和查找
- Agent 在发言工作循环中按需调用工具
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class Tool(ABC):
    """工具基类。所有工具必须实现 name、description 和 execute。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称，用于 Agent 请求调用时的标识。"""

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述，注入到 Agent 的 prompt 中，帮助它决定是否使用。"""

    @abstractmethod
    def execute(self, input: dict) -> str:
        """执行工具调用。

        参数:
            input: 工具输入参数，由 Agent 在 tool_call 中指定

        返回:
            工具输出文本，将注入到 Agent 的下一步 context 中
        """


class ToolRegistry:
    """工具注册表。管理 Agent 可用的工具集合。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具。"""
        self._tools[tool.name] = tool
        logger.info(f"Tool registered: {tool.name}")

    def get(self, name: str) -> Tool | None:
        """按名称获取工具。"""
        return self._tools.get(name)

    def has_tools(self) -> bool:
        """是否有注册的工具。"""
        return len(self._tools) > 0

    def execute(self, name: str, input: dict) -> str:
        """执行指定工具。找不到工具时返回错误信息。"""
        tool = self._tools.get(name)
        if not tool:
            available = ", ".join(self._tools.keys()) or "(无)"
            return f"错误：工具 '{name}' 不存在。可用工具：{available}"
        try:
            result = tool.execute(input)
            logger.info(f"Tool '{name}' executed, input={str(input)[:100]}, result_len={len(result)}")
            return result
        except Exception as e:
            logger.warning(f"Tool '{name}' execution failed: {e}")
            return f"错误：工具 '{name}' 执行失败 - {e}"

    def get_tool_descriptions(self) -> str:
        """生成工具描述文本，用于注入 Agent 的 prompt。"""
        if not self._tools:
            return ""
        lines = []
        for tool in self._tools.values():
            lines.append(f"- **{tool.name}**: {tool.description}")
        return "\n".join(lines)
