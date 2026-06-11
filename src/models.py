"""公共数据模型——跨模块共享的 Pydantic 模型。

从 strategist.py 和 scribe.py 中提取的重复定义，
统一在此模块中定义，各处 import from src.models。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnchorCoverageCheck(BaseModel):
    """锚定问题回应检查——战略家和记录员共用。

    当前在 strategist.py 和 scribe.py 中各有一份完全相同的定义，
    提取到此公共模块消除重复。
    """
    was_addressed: bool = Field(description="核心问题是否被实质性回应")
    quality: str = Field(
        default="unknown",
        description="回应质量",
        json_schema_extra={"enum": ["deep", "surface", "token", "ignored", "unknown"]}
    )
    who_addressed: list[str] = Field(
        default_factory=list, description="谁回应了"
    )
    evidence: str = Field(default="", description="证据（发言中的具体语句）")
    needs_escalation: bool = Field(
        default=False,
        description="是否需要升级约束强度（敷衍或完全没回应时为 true）"
    )
