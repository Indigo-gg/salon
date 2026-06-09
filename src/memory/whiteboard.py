from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.config import WhiteboardConfig


@dataclass
class WhiteboardEntry:
    content: str
    round: int
    added_by: str
    metadata: dict = field(default_factory=dict)
    cold: bool = False  # 冷板凳标记：被 TTL 过期后置 True，保留在内存但不喂给 LLM

    def to_dict(self) -> dict:
        """序列化为 dict（用于 JSON 存储）。"""
        d = {"content": self.content, "round": self.round, "added_by": self.added_by}
        if self.metadata:
            d["metadata"] = self.metadata
        if self.cold:
            d["cold"] = True
        return d

    @classmethod
    def from_dict(cls, data: dict) -> WhiteboardEntry:
        """从 dict 反序列化。"""
        return cls(
            content=data["content"],
            round=data.get("round", 0),
            added_by=data.get("added_by", "restored"),
            metadata=data.get("metadata", {}),
            cold=data.get("cold", False),
        )


class SharedWhiteboard:
    def __init__(self, config: WhiteboardConfig, topic: str = ""):
        self.sections: dict[str, list[WhiteboardEntry]] = {s: [] for s in config.sections}
        self.max_tokens = config.max_tokens
        self.compression_threshold_chars = config.compression_threshold_chars
        self.cold_storage_ttl = config.cold_storage_ttl
        if topic:
            self.sections["current_topic"].append(WhiteboardEntry(
                content=topic, round=0, added_by="system",
            ))

    def update(
        self,
        section: str,
        action: str,
        content: str,
        round_num: int = 0,
        added_by: str = "system",
        metadata: dict | None = None,
    ) -> None:
        if section not in self.sections:
            return

        entries = self.sections[section]

        if action == "add":
            entries.append(WhiteboardEntry(
                content=content, round=round_num, added_by=added_by,
                metadata=metadata or {},
            ))
        elif action in ["remove", "delete"]:
            self.sections[section] = [e for e in entries if e.content != content]
        elif action == "modify":
            if entries:
                entries[-1].content = content
                entries[-1].round = round_num
                entries[-1].added_by = added_by
                entries[-1].cold = False  # 修改即复活
            else:
                entries.append(WhiteboardEntry(
                    content=content, round=round_num, added_by=added_by,
                    metadata=metadata or {},
                ))
        elif action == "rewrite":
            self.sections[section] = [WhiteboardEntry(
                content=content, round=round_num, added_by=added_by,
                metadata=metadata or {},
            )]
        elif action == "clear_section":
            self.sections[section] = []

    def _archive_stale_entries(self, current_round: int) -> None:
        """将陈旧条目标记为冷板凳（cold=True），保留在内存但不再喂给 LLM。"""
        if current_round <= 0:
            return
        for key, entries in self.sections.items():
            if key == "agenda_trace":
                continue  # 议程轨迹有自己的滑动窗口，不走冷板凳
            ttl = 3 if key == "surprises" else self.cold_storage_ttl
            for e in entries:
                if not e.cold and (current_round - e.round) >= ttl:
                    e.cold = True

    def _get_active_entries(self, section: str) -> list[WhiteboardEntry]:
        """返回指定板块中未进入冷板凳的活跃条目。"""
        return [e for e in self.sections.get(section, []) if not e.cold]

    def to_prompt_text(self, current_round: int = 0) -> str:
        # 先执行冷板凳归档
        self._archive_stale_entries(current_round)

        parts = []
        labels = {
            "current_focus": "当前的焦点（即刻交锋点）",
            "discussion_phase": "讨论所处阶段",
            "current_topic": "全局主题",
            "consensus": "已达成的共识",
            "disagreements": "活跃的分歧",
            "backlog": "议题积压区",
            "surprises": "意外发现",
            "agenda_trace": "议程轨迹",
            "active_concepts": "活跃概念清单",
            "search_materials": "检索素材池",
            "concept_load": "概念负荷状态",
        }
        for key, entries in self.sections.items():
            if not entries:
                continue

            # 议程轨迹：保留第 1 条 + 最近 3 条（首尾保留法）
            if key == "agenda_trace":
                active = [e for e in entries if not e.cold]
                if len(active) > 4:
                    active = [active[0]] + active[-3:]
            else:
                active = [e for e in entries if not e.cold]

            if active:
                label = labels.get(key, key)
                items = "\n".join(f"- {e.content}" for e in active)
                parts.append(f"### {label}\n{items}")
        return "\n\n".join(parts) if parts else "（白板为空）"

    def to_brief_prompt_text(self) -> str:
        """精简版白板，用于意图生成：仅焦点 + 分歧。"""
        parts = []
        focus_entries = self._get_active_entries("current_focus")
        if focus_entries:
            parts.append(f"焦点：{focus_entries[-1].content}")
        elif self.sections.get("current_topic"):
            topic_active = self._get_active_entries("current_topic")
            if topic_active:
                parts.append(f"主题：{topic_active[-1].content}")

        disagreements = self._get_active_entries("disagreements")
        if disagreements:
            items = " | ".join(e.content for e in disagreements[:2])
            parts.append(f"核心分歧：{items}")
        return "\n".join(parts) if parts else ""

    def total_chars(self) -> int:
        """返回白板所有活跃条目（非冷板凳）的总字符数，供压缩触发判断。"""
        total = 0
        for entries in self.sections.values():
            for e in entries:
                if not e.cold:
                    total += len(e.content)
        return total

    def get_cold_entries(self) -> dict[str, list[WhiteboardEntry]]:
        """返回所有已进入冷板凳的条目，按板块分组。供报告/UI 使用。"""
        result: dict[str, list[WhiteboardEntry]] = {}
        for key, entries in self.sections.items():
            cold = [e for e in entries if e.cold]
            if cold:
                result[key] = cold
        return result

    def save_to_file(self, path: str) -> None:
        """将白板保存为 JSON 文件（完整序列化，保留 metadata 和 cold 标记）。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for key, entries in self.sections.items():
            data[key] = [e.to_dict() for e in entries]
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_from_file(self, path: str) -> bool:
        """从 JSON 文件加载白板。返回是否成功。"""
        p = Path(path)
        if not p.exists():
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for key, entries_data in data.items():
                if key in self.sections:
                    self.sections[key] = [WhiteboardEntry.from_dict(d) for d in entries_data]
            return True
        except Exception:
            return False

    def save_to_markdown(self, path: str) -> None:
        """保存为人类可读的 Markdown 文件（用于调试/UI，不用于恢复）。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        content = "# 白板\n\n"
        labels = {
            "current_focus": "当前的焦点（即刻交锋点）",
            "discussion_phase": "讨论所处阶段",
            "current_topic": "全局主题",
            "consensus": "已达成的共识",
            "disagreements": "活跃的分歧",
            "backlog": "议题积压区",
            "surprises": "意外发现",
            "agenda_trace": "议程轨迹",
            "active_concepts": "活跃概念清单",
            "search_materials": "检索素材池",
            "concept_load": "概念负荷状态",
        }

        # 活跃条目
        for key, entries in self.sections.items():
            label = labels.get(key, key)
            active = [e for e in entries if not e.cold]
            content += f"## {label}\n"
            if active:
                for e in active:
                    content += f"- {e.content}（第 {e.round} 轮，由 {e.added_by} 添加）\n"
            else:
                content += "（空）\n"
            content += "\n"

        # 冷板凳归档区
        cold_entries = self.get_cold_entries()
        if cold_entries:
            content += "---\n\n## 冷板凳（已归档）\n\n"
            for key, entries in cold_entries.items():
                label = labels.get(key, key)
                content += f"### {label}\n"
                for e in entries:
                    content += f"- {e.content}（第 {e.round} 轮，由 {e.added_by} 添加）\n"
                content += "\n"

        p.write_text(content, encoding="utf-8")
