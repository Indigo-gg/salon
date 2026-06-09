"""Injection Router — 信号注入路由器。

独立模块，负责将 RoundSignals 翻译为条件性注入文本。
注入目标分为两类：主持人 prompt（宏观控场）和参与者 round_info（微观提示）。

设计原则：
- 每条规则是独立的 InjectionRule，包含触发条件和文本生成器
- 新增信号维度只需添加新规则，无需修改现有代码
- 规则按优先级排序，高优先级的注入文本排在前面
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from src.config import MonitorConfig
from src.core.round_monitor import RoundSignals

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 注入规则数据结构
# ---------------------------------------------------------------------------

@dataclass
class InjectionRule:
    """一条注入规则：当条件满足时，生成注入文本到指定目标。"""
    name: str                                    # 规则名称（用于日志和调试）
    target: str                                  # "moderator" | "participant" | "both"
    condition: Callable[[RoundSignals], bool]    # 触发条件
    text_builder: Callable[[RoundSignals], str]  # 生成注入文本
    priority: int = 0                            # 优先级（高值排前面）


# ---------------------------------------------------------------------------
# Injection Router
# ---------------------------------------------------------------------------

class InjectionRouter:
    """信号注入路由器。持有注入规则集，根据 RoundSignals 生成注入文本。"""

    def __init__(self, config: MonitorConfig, rules: list[InjectionRule] | None = None):
        self.config = config
        self.rules = rules or self._default_rules()
        logger.info(f"InjectionRouter initialized with {len(self.rules)} rules: "
                     f"{[r.name for r in self.rules]}")

    def build_moderator_injection(self, signals: RoundSignals) -> str:
        """返回注入主持人 prompt 的文本。无问题时返回空字符串。"""
        parts = []
        for rule in sorted(self.rules, key=lambda r: r.priority, reverse=True):
            if rule.target in ("moderator", "both") and rule.condition(signals):
                text = rule.text_builder(signals)
                if text:
                    parts.append(text)
        return "\n".join(parts)

    def build_participant_injection(self, signals: RoundSignals) -> str:
        """返回注入参与者 round_info 的文本。无问题时返回空字符串。"""
        parts = []
        for rule in sorted(self.rules, key=lambda r: r.priority, reverse=True):
            if rule.target in ("participant", "both") and rule.condition(signals):
                text = rule.text_builder(signals)
                if text:
                    parts.append(text)
        return "\n".join(parts)

    def _default_rules(self) -> list[InjectionRule]:
        """从 config 构建默认注入规则集。"""
        cfg = self.config
        return [
            # --- 主持人注入规则（宏观控场）---

            # 1. 密度警报：连续高密度 → 要求用故事替代新框架
            InjectionRule(
                name="density_alert",
                target="moderator",
                condition=lambda s: s.consecutive_high_density >= cfg.consecutive_high_trigger,
                text_builder=lambda s: (
                    f"⚠️ 【密度警报】最近{s.consecutive_high_density}轮每轮引入超过"
                    f"{cfg.density_high_threshold:.0f}个新概念。"
                    f"考虑要求一位参与者用一个具体故事而非新框架来发言。"
                ),
                priority=10,
            ),

            # 2. 着陆提示：长时间没有具体故事 → 安排生活场景
            InjectionRule(
                name="landing_prompt",
                target="moderator",
                condition=lambda s: s.rounds_since_story >= cfg.rounds_since_story_trigger,
                text_builder=lambda s: (
                    f"⚠️ 【着陆提示】已{s.rounds_since_story}轮没有出现具体故事或案例。"
                    f"考虑安排一位参与者用生活场景来落地当前讨论。"
                ),
                priority=8,
            ),

            # 3. 锚定提示：长时间未回锚原始问题 → 罗盘检查
            InjectionRule(
                name="anchor_prompt",
                target="moderator",
                condition=lambda s: s.rounds_since_anchor >= cfg.rounds_since_anchor_trigger,
                text_builder=lambda s: (
                    f"⚠️ 【锚定提示】已{s.rounds_since_anchor}轮未显式连接回原始问题。"
                    f"考虑在notice中做一次罗盘检查：'我们从原始问题出发，现在探索到了哪里？'"
                ),
                priority=6,
            ),

            # 4. 孤立概念清单：有概念长期未被引用 → 复用或退役
            InjectionRule(
                name="orphaned_concepts",
                target="moderator",
                condition=lambda s: len(s.orphaned_concepts) > 0,
                text_builder=lambda s: (
                    f"📋 【概念清单】以下概念已引入但近期未被使用："
                    f"{', '.join(s.orphaned_concepts[:5])}。"
                    f"可以要求参与者复用或显式退役。"
                ),
                priority=4,
            ),

            # 5. 意图失衡：Extend 意图占比过高 → 鼓励不同声音
            InjectionRule(
                name="intent_imbalance",
                target="moderator",
                condition=lambda s: (
                    s.intent_distribution
                    and sum(s.intent_distribution.values()) > 0
                    and s.intent_distribution.get("Extend", 0) / sum(s.intent_distribution.values())
                        >= cfg.extend_ratio_threshold
                ),
                text_builder=lambda s: (
                    f"⚠️ 【意图失衡】最近{sum(s.intent_distribution.values())}轮中"
                    f"{s.intent_distribution.get('Extend', 0) / sum(s.intent_distribution.values()):.0%}"
                    f"的意图是Extend。"
                    f"考虑优先选择Dissent或New_Angle意图的发言者，或在notice中鼓励不同声音。"
                ),
                priority=5,
            ),

            # 6. 可读性过载（新增）：连续高不可读 → 要求白话翻译
            InjectionRule(
                name="readability_overload",
                target="moderator",
                condition=lambda s: s.consecutive_high_readability >= cfg.readability_consecutive_trigger,
                text_builder=lambda s: (
                    f"⚠️ 【可读性过载】最近{s.consecutive_high_readability}轮讨论的学术密度持续偏高"
                    f"（抽象词汇占比{s.abstract_ratio:.0%}，长句占比{s.long_sentence_ratio:.0%}）。"
                    f"作为观众代言人，请打断当前的深度推演，邀请一位发言者用日常生活的具体场景"
                    f"把刚才的核心观点翻译成白话版。"
                ),
                priority=9,  # 高优先级：保护人类观众的理解
            ),

            # --- 参与者注入规则（微观提示）---

            # 7. 呼吸空间建议：连续高密度 + 长时间没有故事 → 提醒用故事回应
            InjectionRule(
                name="breathing_hints",
                target="participant",
                condition=lambda s: (
                    s.consecutive_high_density >= cfg.consecutive_high_trigger
                    and s.rounds_since_story >= cfg.rounds_since_story_trigger
                ),
                text_builder=lambda s: f"💡 {cfg.breathing_suggestion}",
                priority=3,
            ),
        ]
