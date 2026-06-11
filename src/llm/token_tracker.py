"""Token 消耗追踪器。

透明记录每次 LLM API 调用的 token 用量，不干扰调用方。
LLMClient 内部自动调用 tracker.record()，外部无需感知。
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TokenCallRecord:
    """单次 LLM 调用的 token 记录。"""
    timestamp: str
    model: str
    call_type: str          # "chat" / "stream" / "structured"
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    agent_id: str = ""      # 可选：哪个 agent 发起的
    context_type: str = ""  # 可选：intent / speak / moderator / scribe / summary


class TokenUsageTracker:
    """Token 消耗追踪器。线程安全。"""

    def __init__(self) -> None:
        self._records: list[TokenCallRecord] = []
        self._lock = threading.Lock()
        # 线程级上下文：让调用方在 LLM 调用前设置 agent 信息
        self._context = threading.local()

    def set_context(self, agent_id: str = "", context_type: str = "") -> None:
        """设置当前线程的调用上下文（可选）。"""
        self._context.agent_id = agent_id
        self._context.context_type = context_type

    def clear_context(self) -> None:
        """清除当前线程的调用上下文。"""
        self._context.agent_id = ""
        self._context.context_type = ""

    def record(
        self,
        model: str,
        call_type: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        """记录一次 LLM 调用的 token 用量。"""
        agent_id = getattr(self._context, "agent_id", "")
        context_type = getattr(self._context, "context_type", "")

        entry = TokenCallRecord(
            timestamp=datetime.now().isoformat(),
            model=model,
            call_type=call_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            agent_id=agent_id,
            context_type=context_type,
        )
        with self._lock:
            self._records.append(entry)

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self._records)

    def summary(self) -> dict:
        """生成汇总统计。"""
        with self._lock:
            records = list(self._records)

        total_prompt = sum(r.prompt_tokens for r in records)
        total_completion = sum(r.completion_tokens for r in records)
        total = sum(r.total_tokens for r in records)

        by_model: dict[str, dict] = {}
        by_agent: dict[str, dict] = {}
        by_call_type: dict[str, dict] = {}

        for r in records:
            # by model
            m = by_model.setdefault(r.model, {"prompt": 0, "completion": 0, "calls": 0})
            m["prompt"] += r.prompt_tokens
            m["completion"] += r.completion_tokens
            m["calls"] += 1

            # by agent
            if r.agent_id:
                a = by_agent.setdefault(r.agent_id, {"prompt": 0, "completion": 0, "calls": 0})
                a["prompt"] += r.prompt_tokens
                a["completion"] += r.completion_tokens
                a["calls"] += 1

            # by call type
            t = by_call_type.setdefault(r.call_type, {"prompt": 0, "completion": 0, "calls": 0})
            t["prompt"] += r.prompt_tokens
            t["completion"] += r.completion_tokens
            t["calls"] += 1

        return {
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total,
            "call_count": len(records),
            "by_model": by_model,
            "by_agent": by_agent,
            "by_call_type": by_call_type,
        }

    def save(self, path: str | Path) -> None:
        """保存完整记录到 JSON 文件。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "summary": self.summary(),
            "records": [
                {
                    "timestamp": r.timestamp,
                    "model": r.model,
                    "call_type": r.call_type,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "agent_id": r.agent_id,
                    "context_type": r.context_type,
                }
                for r in self._records
            ],
        }
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Token usage saved: {p} ({data['summary']['call_count']} calls, {data['summary']['total_tokens']} tokens)")
