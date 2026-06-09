"""网络搜索工具：基于 Tavily API 的信息检索。

用法：
    from src.tools.search import WebSearchTool

    tool = WebSearchTool(api_key="tvly-...", max_results=3)
    results = tool.search_sync("佛学 因缘果报 现代应用")
    text = tool.format_results(results)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"


@dataclass
class SearchResult:
    """一条搜索结果。"""
    title: str
    url: str
    snippet: str


class WebSearchTool:
    """基于 Tavily API 的网络搜索工具。"""

    def __init__(self, api_key: str, max_results: int = 3, timeout: float = 15.0):
        self.api_key = api_key
        self.max_results = max_results
        self.timeout = timeout

    def search_sync(self, query: str) -> list[SearchResult]:
        """同步搜索。返回 SearchResult 列表，失败时返回空列表。"""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    TAVILY_API_URL,
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": self.max_results,
                        "search_depth": "basic",
                        "include_answer": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            results = []
            for item in data.get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", "")[:500],
                ))
            logger.info(f"Search '{query}' returned {len(results)} results")
            return results

        except Exception as e:
            logger.warning(f"Search failed for '{query}': {e}")
            return []

    async def search(self, query: str) -> list[SearchResult]:
        """异步搜索。返回 SearchResult 列表，失败时返回空列表。"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    TAVILY_API_URL,
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": self.max_results,
                        "search_depth": "basic",
                        "include_answer": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            results = []
            for item in data.get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", "")[:500],
                ))
            logger.info(f"Search '{query}' returned {len(results)} results")
            return results

        except Exception as e:
            logger.warning(f"Search failed for '{query}': {e}")
            return []

    def format_results(self, results: list[SearchResult], max_snippet: int = 300) -> str:
        """将搜索结果格式化为可注入 prompt 的文本。精炼版：标题+摘要+来源。"""
        if not results:
            return ""
        lines = []
        for i, r in enumerate(results, 1):
            snippet = r.snippet[:max_snippet].rsplit("，", 1)[0] if len(r.snippet) > max_snippet else r.snippet
            # 提取域名作为来源标识
            from urllib.parse import urlparse
            domain = urlparse(r.url).netloc.replace("www.", "")
            lines.append(f"{i}. [{domain}] {r.title}：{snippet}")
        return "\n".join(lines)

    def format_results_brief(self, results: list[SearchResult]) -> str:
        """极简格式：仅标题和来源，用于白板等空间受限的场景。"""
        if not results:
            return ""
        from urllib.parse import urlparse
        lines = []
        for r in results:
            domain = urlparse(r.url).netloc.replace("www.", "")
            lines.append(f"- {r.title}（{domain}）")
        return "\n".join(lines)


class SearchTool:
    """搜索工具适配器——实现 Tool 接口，包装 WebSearchTool。

    供 Agent 工作循环调用。Agent 通过 tool_call 请求搜索，
    SearchTool 执行搜索并返回格式化的结果。
    """

    def __init__(self, web_search_tool: WebSearchTool):
        self._tool = web_search_tool

    @property
    def name(self) -> str:
        return "search"

    @property
    def description(self) -> str:
        return "搜索网络获取具体事实、研究数据或案例。输入：{\"queries\": [\"关键词1\", \"关键词2\"]}"

    def execute(self, input: dict) -> str:
        """执行搜索。input 格式：{"queries": ["关键词1", "关键词2"]}"""
        queries = input.get("queries", [])
        if not queries:
            return "错误：请在 queries 中提供搜索关键词"

        if isinstance(queries, str):
            queries = [queries]

        all_results = []
        for query in queries[:2]:  # 最多2个搜索词
            results = self._tool.search_sync(query)
            all_results.extend(results)

        if not all_results:
            return "搜索无结果。请基于你已有的知识发言。"

        formatted = self._tool.format_results(all_results)
        return (
            f"以下是搜索结果。请从中提取对你论点最有用的关键事实，"
            f"直接融入你的发言中，并在提及来源时用括号标注出处域名。"
            f"不要逐条罗列搜索结果，只用你需要的部分。\n\n"
            f"{formatted}"
        )
