"""Round Monitor — 轮次信号计算与概念追踪。

重构后采用 SignalSource 插件架构：每个信号维度是独立的 SignalSource 子类，
RoundMonitor 作为聚合器统一调用。注入文本生成已移至 injection_router.py。
"""

from __future__ import annotations

import logging
import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field

from src.config import MonitorConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 概念注册表：追踪每个概念的引入轮次和最后引用轮次
# ---------------------------------------------------------------------------

@dataclass
class ConceptInfo:
    name: str
    introduced_by: str  # agent_id
    round: int
    last_referenced: int
    status: str = "active"  # active / dormant


# ---------------------------------------------------------------------------
# 轮次信号数据结构
# ---------------------------------------------------------------------------

@dataclass
class RoundSignals:
    # 密度信号
    density_score: float = 0.0            # 最近3轮每轮新概念数均值
    density_trend: str = "stable"         # rising / stable / falling
    consecutive_high_density: int = 0     # 连续高密度轮次数

    # 节奏信号
    rounds_since_story: int = 0           # 距上次具体故事的轮次数
    rounds_since_anchor: int = 0          # 距上次显式回锚的轮次数

    # 概念信号
    orphaned_concepts: list[str] = field(default_factory=list)  # 3轮未引用的概念名

    # 意图信号
    consecutive_extend: int = 0           # 连续Extend意图的数量
    intent_distribution: dict[str, int] = field(default_factory=dict)  # 最近5轮分布

    # 可读性信号（面向人类观众）
    readability_score: float = 0.0        # 综合可读性得分 0.0=通俗, 1.0=满屏黑话
    abstract_ratio: float = 0.0           # 抽象词汇占比
    long_sentence_ratio: float = 0.0      # 长句（>40字）占比
    readability_entropy: float = 0.0      # 信息熵
    consecutive_high_readability: int = 0 # 连续高不可读轮次数


# ---------------------------------------------------------------------------
# 故事检测标记词
# ---------------------------------------------------------------------------

_STORY_MARKERS_ZH = [
    "比如", "譬如", "想象一下", "想象一个", "有一个", "曾经", "记得",
    "我认识", "我见过", "我听过", "故事", "案例", "场景",
    "有一次", "那一天", "几年前", "小时候", "昨天",
    "就像", "好比", "打个比方",
]

_STORY_MARKERS_EN = [
    "for example", "imagine", "there was", "i remember", "story",
    "once upon", "picture this", "think of", "like when",
]

# 锚定检测：这些短语表示发言者在显式连接回原始主题
_ANCHOR_MARKERS_ZH = [
    "回到最初", "回到原始", "回到主题", "回到问题",
    "和最初的", "和原始的", "与主题的关系",
    "我应该", "我需要",  # 直接引用原始问题中的关键词
]
_ANCHOR_MARKERS_EN = [
    "back to the original", "connecting to the topic",
    "relates to the original question",
]


# ---------------------------------------------------------------------------
# 可读性检测：抽象词汇标记
# ---------------------------------------------------------------------------

# 4 字以上的典型学术/哲学抽象词汇（中文）
_ABSTRACT_MARKERS_ZH = [
    "本体论", "认识论", "形而上学", "存在主义", "虚无主义",
    "现象学", "辩证法", "唯物主义", "唯心主义", "二元论",
    "一元论", "功利主义", "实用主义", "结构主义", "解构主义",
    "后现代", "现代性", "主体性", "客体性", "交互性",
    "超验", "先验", "内在性", "超越性", "偶然性",
    "必然性", "自由意志", "决定论", "兼容论", "因果律",
    "道德律", "绝对命令", "范畴", "理念", "精神",
    "自在之物", "物自体", "此在", "存在者", "存在",
    "话语权", "意识形态", "上层建筑", "经济基础", "异化",
    "物化", "商品拜物教", "剩余价值", "生产关系", "生产力",
    "范式", "范式转换", "不可通约性", "科学革命", "常规科学",
    "涌现", "自组织", "复杂系统", "混沌理论", "熵增",
]

# 4 字以上的典型学术/哲学抽象词汇（英文）
_ABSTRACT_MARKERS_EN = [
    "ontology", "epistemology", "metaphysics", "existentialism", "nihilism",
    "phenomenology", "dialectics", "materialism", "idealism", "dualism",
    "monism", "utilitarianism", "pragmatism", "structuralism", "deconstruction",
    "postmodern", "modernity", "subjectivity", "objectivity", "intersubjectivity",
    "transcendental", "a priori", "immanence", "transcendence", "contingency",
    "necessity", "free will", "determinism", "compatibilism", "causality",
    "categorical imperative", "paradigm", "paradigm shift", "incommensurability",
    "emergence", "self-organization", "entropy",
]


# ---------------------------------------------------------------------------
# SignalSource 抽象基类
# ---------------------------------------------------------------------------

class SignalSource(ABC):
    """信号源插件接口。每个信号维度实现一个子类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """信号源名称，用于日志和调试。"""

    @abstractmethod
    def compute(
        self,
        round_num: int,
        recent_messages: list,
        topic: str,
        intent_types: list[str] | None,
        round_monitor: RoundMonitor,
    ) -> dict:
        """计算信号，返回要合并到 RoundSignals 的字段字典。

        Args:
            round_num: 当前轮次
            recent_messages: 最近的消息列表
            topic: 讨论主题
            intent_types: 本轮各参与者提交的意图类型
            round_monitor: RoundMonitor 实例，用于访问内部状态（如概念注册表）
        """


# ---------------------------------------------------------------------------
# 密度信号源
# ---------------------------------------------------------------------------

class DensitySignal(SignalSource):
    @property
    def name(self) -> str:
        return "density"

    def compute(self, round_num, recent_messages, topic, intent_types, round_monitor) -> dict:
        # 按轮次分组
        round_texts: dict[int, str] = {}
        for msg in recent_messages:
            if hasattr(msg, 'round') and hasattr(msg, 'content'):
                rnd = msg.round
                if rnd not in round_texts:
                    round_texts[rnd] = ""
                round_texts[rnd] += " " + msg.content

        # 计算每轮的概念密度（逗号+句号分隔的短语数 / 2，粗略估计）
        current_density = 0
        if round_num in round_texts:
            text = round_texts[round_num]
            separators = len(re.findall(r'[，；。！？]', text))
            current_density = max(1, int(separators * 0.15))

        round_monitor._density_history.append(current_density)

        # 计算最近3轮均值
        recent = round_monitor._density_history[-3:]
        density_score = sum(recent) / len(recent)

        # 趋势
        density_trend = "stable"
        if len(recent) >= 2:
            if recent[-1] > recent[0]:
                density_trend = "rising"
            elif recent[-1] < recent[0]:
                density_trend = "falling"

        # 连续高密度计数
        threshold = round_monitor.config.density_high_threshold
        count = 0
        for d in reversed(round_monitor._density_history):
            if d >= threshold:
                count += 1
            else:
                break

        return {
            "density_score": density_score,
            "density_trend": density_trend,
            "consecutive_high_density": count,
        }


# ---------------------------------------------------------------------------
# 故事信号源
# ---------------------------------------------------------------------------

class StorySignal(SignalSource):
    @property
    def name(self) -> str:
        return "story"

    def compute(self, round_num, recent_messages, topic, intent_types, round_monitor) -> dict:
        has_story = 0
        for msg in recent_messages:
            if not hasattr(msg, 'content'):
                continue
            text = msg.content.lower()
            for marker in _STORY_MARKERS_ZH + _STORY_MARKERS_EN:
                if marker in text:
                    has_story = 1
                    break
            if has_story:
                break

        round_monitor._story_history.append(has_story)

        count = 0
        for s in reversed(round_monitor._story_history):
            if s == 0:
                count += 1
            else:
                break

        return {"rounds_since_story": count}


# ---------------------------------------------------------------------------
# 锚定信号源
# ---------------------------------------------------------------------------

class AnchorSignal(SignalSource):
    @property
    def name(self) -> str:
        return "anchor"

    def compute(self, round_num, recent_messages, topic, intent_types, round_monitor) -> dict:
        topic_keywords = set(re.findall(r'[一-鿿]{2,}', topic))

        has_anchor = 0
        for msg in recent_messages:
            if not hasattr(msg, 'content'):
                continue
            text = msg.content
            for marker in _ANCHOR_MARKERS_ZH + _ANCHOR_MARKERS_EN:
                if marker in text:
                    has_anchor = 1
                    break
            if not has_anchor and topic_keywords:
                matches = sum(1 for kw in topic_keywords if kw in text)
                if matches >= 2:
                    has_anchor = 1
            if has_anchor:
                break

        round_monitor._anchor_history.append(has_anchor)

        count = 0
        for a in reversed(round_monitor._anchor_history):
            if a == 0:
                count += 1
            else:
                break

        return {"rounds_since_anchor": count}


# ---------------------------------------------------------------------------
# 概念追踪信号源
# ---------------------------------------------------------------------------

class ConceptSignal(SignalSource):
    @property
    def name(self) -> str:
        return "concept"

    def compute(self, round_num, recent_messages, topic, intent_types, round_monitor) -> dict:
        for msg in recent_messages:
            if not hasattr(msg, 'content') or not hasattr(msg, 'agent_id'):
                continue
            text = msg.content
            for cname, info in round_monitor._concept_registry.items():
                if info.status != "retired" and cname in text:
                    info.last_referenced = round_num
                    info.status = "active"

        orphaned = []
        for cname, info in round_monitor._concept_registry.items():
            if info.status == "retired":
                continue
            if (round_num - info.last_referenced) >= round_monitor.config.dormant_concept_threshold:
                info.status = "dormant"
                orphaned.append(cname)

        return {"orphaned_concepts": orphaned}


# ---------------------------------------------------------------------------
# 意图信号源
# ---------------------------------------------------------------------------

class IntentSignal(SignalSource):
    @property
    def name(self) -> str:
        return "intent"

    def compute(self, round_num, recent_messages, topic, intent_types, round_monitor) -> dict:
        if intent_types:
            most_common = Counter(intent_types).most_common(1)[0][0]
            round_monitor._intent_history.append(most_common)

        count = 0
        for t in reversed(round_monitor._intent_history):
            if t in ("Extend", "extend"):
                count += 1
            else:
                break

        recent = round_monitor._intent_history[-5:]
        intent_distribution = dict(Counter(recent))

        return {
            "consecutive_extend": count,
            "intent_distribution": intent_distribution,
        }


# ---------------------------------------------------------------------------
# 可读性信号源（新增：面向人类观众）
# ---------------------------------------------------------------------------

class ReadabilitySignal(SignalSource):
    """站在人类观众视角，监控讨论的可理解程度。"""

    @property
    def name(self) -> str:
        return "readability"

    def compute(self, round_num, recent_messages, topic, intent_types, round_monitor) -> dict:
        # 收集最近 5 轮的公共消息文本
        round_texts: dict[int, str] = {}
        for msg in recent_messages:
            if hasattr(msg, 'round') and hasattr(msg, 'content') and hasattr(msg, 'agent_role'):
                # 只看参与者和主持人的发言，跳过 intent 和 system_notice
                if msg.speech_type in ("intent", "system_notice"):
                    continue
                rnd = msg.round
                if rnd not in round_texts:
                    round_texts[rnd] = ""
                round_texts[rnd] += " " + msg.content

        # 取最近 5 轮
        recent_rounds = sorted(round_texts.keys())[-5:]
        if not recent_rounds:
            return {
                "readability_score": 0.0,
                "abstract_ratio": 0.0,
                "long_sentence_ratio": 0.0,
                "readability_entropy": 0.0,
                "consecutive_high_readability": 0,
            }

        combined_text = " ".join(round_texts[r] for r in recent_rounds)

        # 1. 词汇抽象度：4 字以上抽象词汇占比
        abstract_ratio = self._calc_abstract_ratio(combined_text)

        # 2. 长句占比：单句超过 40 字的比例
        long_sentence_ratio = self._calc_long_sentence_ratio(combined_text)

        # 3. 信息熵：基于词频分布
        entropy = self._calc_entropy(combined_text)

        # 综合得分：三个维度归一化后加权平均
        # abstract_ratio 已经是 0-1
        # long_sentence_ratio 已经是 0-1
        # entropy 归一化到 0-1（中文文本熵通常在 3-7 之间）
        norm_entropy = min(1.0, max(0.0, (entropy - 3.0) / 4.0))
        readability_score = 0.4 * abstract_ratio + 0.3 * long_sentence_ratio + 0.3 * norm_entropy

        # 连续高不可读计数
        round_monitor._readability_history.append(readability_score)
        count = 0
        for r in reversed(round_monitor._readability_history):
            if r >= 0.6:  # 高不可读阈值
                count += 1
            else:
                break

        return {
            "readability_score": readability_score,
            "abstract_ratio": abstract_ratio,
            "long_sentence_ratio": long_sentence_ratio,
            "readability_entropy": entropy,
            "consecutive_high_readability": count,
        }

    def _calc_abstract_ratio(self, text: str) -> float:
        """计算抽象词汇占比。"""
        # 中文：按字符长度 + 匹配抽象词表
        words = re.findall(r'[一-鿿]{2,}', text)
        if not words:
            return 0.0
        abstract_count = 0
        for w in words:
            if w in _ABSTRACT_MARKERS_ZH:
                abstract_count += 1
            # 长度 >= 4 的非人名词也视为偏抽象
            elif len(w) >= 4 and w not in ("我们", "他们", "你们", "大家", "这个", "那个"):
                abstract_count += 1
        # 英文
        en_words = re.findall(r'[a-z]{4,}', text.lower())
        for w in en_words:
            if w in _ABSTRACT_MARKERS_EN:
                abstract_count += 1

        total_segments = len(words) + len(en_words)
        if total_segments == 0:
            return 0.0
        return min(1.0, abstract_count / total_segments)

    def _calc_long_sentence_ratio(self, text: str) -> float:
        """计算长句（>40字）占比。"""
        sentences = re.split(r'[。！？.!?\n]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return 0.0
        long_count = sum(1 for s in sentences if len(s) > 40)
        return long_count / len(sentences)

    def _calc_entropy(self, text: str) -> float:
        """基于字符频率计算信息熵。"""
        if not text:
            return 0.0
        freq = Counter(text)
        total = sum(freq.values())
        entropy = 0.0
        for count in freq.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy


# ---------------------------------------------------------------------------
# Round Monitor 核心类（聚合器）
# ---------------------------------------------------------------------------

class RoundMonitor:
    def __init__(self, config: MonitorConfig, sources: list[SignalSource] | None = None):
        self.config = config
        self._concept_registry: dict[str, ConceptInfo] = {}
        self._density_history: list[float] = []
        self._story_history: list[int] = []
        self._intent_history: list[str] = []
        self._anchor_history: list[int] = []
        self._readability_history: list[float] = []

        # 信号源：默认使用全部 6 个，支持自定义
        self._sources: list[SignalSource] = sources if sources is not None else [
            DensitySignal(),
            StorySignal(),
            AnchorSignal(),
            ConceptSignal(),
            IntentSignal(),
            ReadabilitySignal(),
        ]
        logger.info(f"RoundMonitor initialized with {len(self._sources)} signal sources: "
                     f"{[s.name for s in self._sources]}")

    def compute(
        self,
        round_num: int,
        recent_messages: list,  # list[Message]
        topic: str,
        intent_types: list[str] | None = None,
    ) -> RoundSignals:
        """计算当前轮次的信号。遍历所有 SignalSource 并合并结果。"""

        signals = RoundSignals()

        if not self.config.enabled:
            return signals

        for source in self._sources:
            try:
                result = source.compute(
                    round_num, recent_messages, topic, intent_types, self,
                )
                for key, value in result.items():
                    if hasattr(signals, key):
                        setattr(signals, key, value)
                    else:
                        logger.warning(f"SignalSource '{source.name}' returned unknown field: {key}")
            except Exception as e:
                logger.error(f"SignalSource '{source.name}' compute failed: {e}")

        return signals

    def register_concept(self, name: str, introduced_by: str, round_num: int) -> None:
        """由外部调用，注册新引入的概念。"""
        if name not in self._concept_registry:
            self._concept_registry[name] = ConceptInfo(
                name=name,
                introduced_by=introduced_by,
                round=round_num,
                last_referenced=round_num,
            )

    def get_active_concepts(self) -> list[ConceptInfo]:
        """返回所有活跃概念。"""
        return [c for c in self._concept_registry.values() if c.status == "active"]

    def get_concept_summary_for_whiteboard(self) -> str:
        """生成白板 active_concepts section 的内容。"""
        concepts = [c for c in self._concept_registry.values() if c.status != "retired"]
        if not concepts:
            return ""
        lines = []
        for c in concepts:
            lines.append(f"{c.name} | {c.introduced_by} | 第{c.round}轮 | {c.status}")
        return "\n".join(lines)
