from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


@dataclass
class LLMConfig:
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o"
    use_native_thinking: bool = False
    temperature: float = 0.8
    max_tokens: int = 2000
    timeout: int = 60
    retry_count: int = 3
    retry_delay: int = 2


@dataclass
class DiscussionConfig:
    language: str = "zh"
    max_rounds: int = 50
    min_rounds: int = 10
    max_speech_chars: int = 1000
    min_speech_chars: int = 50
    default_participant_count: int = 3
    topic_exhaustion_check_interval: int = 5


@dataclass
class ConversationStreamConfig:
    recent_messages_count: int = 5
    summary_batch_size: int = 5





@dataclass
class WhiteboardConfig:
    max_tokens: int = 1500
    auto_update_interval: int = 5
    compression_threshold_chars: int = 800
    cold_storage_ttl: int = 4
    sections: list[str] = field(default_factory=lambda: [
        "current_focus", "discussion_phase", "current_topic",
        "consensus", "disagreements", "backlog",
        "surprises", "agenda_trace", "active_concepts",
        "search_materials", "concept_load",
    ])


@dataclass
class ArchiveConfig:
    enabled: bool = True
    retrieval_top_k: int = 5
    retrieval_strategy: str = "hybrid"
    index_categories: list[str] = field(default_factory=lambda: [
        "acknowledged_consensus", "brilliant_insights",
        "similar_patterns", "unresolved_tensions", "key_references",
    ])


@dataclass
class SearchConfig:
    enabled: bool = False                              # 是否启用搜索
    api_key: str = ""                                  # Tavily API Key（也可从环境变量 TAVILY_API_KEY 读取）
    max_results: int = 3                               # 每次搜索返回的最大结果数
    max_queries_per_intent: int = 2                    # 每个意图最多搜索几次


@dataclass
class MemoryConfig:
    conversation_stream: ConversationStreamConfig = field(default_factory=ConversationStreamConfig)
    whiteboard: WhiteboardConfig = field(default_factory=WhiteboardConfig)
    archive: ArchiveConfig = field(default_factory=ArchiveConfig)


@dataclass
class ContextAllocation:
    system_prompt: int = 500
    soul: int = 800
    archive_injection: int = 1000
    whiteboard: int = 1500
    summarized_history: int = 2000
    recent_messages: int = 5000
    action_prompt: int = 200


@dataclass
class ContextConfig:
    max_prompt_tokens: int = 12000
    allocation: ContextAllocation = field(default_factory=ContextAllocation)
    reserve_for_generation: int = 2000
    # 按行动类型的 token 预算
    intent_max_tokens: int = 800             # 意图收集（极简）
    speak_max_tokens: int = 5000             # 发言（精简）
    moderator_max_tokens: int = 8000         # 主持人决策（较完整）
    scribe_max_tokens: int = 3000            # 记录员同步（白板+近期）


@dataclass
class HumanConfig:
    default_role: str = "observer"
    input_timeout: int = 30
    auto_skip_on_timeout: bool = True
    ai_chair_takeover_timeout: int = 60
    pause_behavior: str = "finish_current"
    at_human_timeout: int = 15


@dataclass
class OutputConfig:
    transcript_format: str = "jsonl"
    transcript_include_metadata: bool = True
    digest_auto_generate: bool = True
    digest_format: str = "markdown"
    report_auto_generate: bool = False
    report_format: str = "markdown"


@dataclass
class StorageConfig:
    base_dir: str = "data"
    sessions_dir: str = "data/sessions"
    archives_dir: str = "data/archives"
    encoding: str = "utf-8"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "data/salon.log"
    console: bool = True
    decision_log: bool = True       # 是否在终端实时打印决策面板
    signal_log: bool = False        # 是否在日志中记录每轮信号值（VERBOSE）


@dataclass
class MonitorConfig:
    enabled: bool = True
    density_high_threshold: float = 3.0
    consecutive_high_trigger: int = 3
    rounds_since_story_trigger: int = 5
    rounds_since_anchor_trigger: int = 8
    dormant_concept_threshold: int = 3
    extend_ratio_threshold: float = 0.8
    breathing_suggestion: str = "考虑用一个具体的生活场景或故事来回应当前讨论，而不是引入新的理论框架。"
    # 可读性信号配置
    readability_abstract_threshold: float = 0.4     # 抽象词汇占比阈值
    readability_long_sentence_threshold: float = 0.3  # 长句占比阈值
    readability_entropy_threshold: float = 4.5      # 信息熵阈值
    readability_consecutive_trigger: int = 3         # 连续N轮触发干预

    # --- 调度器防线配置 ---
    novelty_low_threshold: float = 0.2               # novelty_score 低于此值视为高重复（更保守，避免误判）
    repetition_topic_shift_speeches: int = 12        # 连续 N 次发言新颖度低 → 强制话题转移
    repetition_exhausted_speeches: int = 20          # 连续 N 次发言新颖度低 → 穷尽提醒
    recent_speak_window: int = 3                     # 发言统计窗口大小
    closing_window_min: int = 2                      # closing_window 最小值
    closing_window_max: int = 5                      # closing_window 最大值
    anchor_soft_trigger: int = 6                     # 轮温和锚定提醒
    anchor_medium_trigger: int = 10                  # 轮中等锚定提醒
    anchor_hard_trigger: int = 15                    # 轮强制罗盘检查


@dataclass
class SalonConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    discussion: DiscussionConfig = field(default_factory=DiscussionConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    human: HumanConfig = field(default_factory=HumanConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    config_dir: str = "config"


def _build_config_from_dict(data: dict[str, Any]) -> SalonConfig:
    llm_raw = data.get("llm", {})
    llm = LLMConfig(
        api_base=llm_raw.get("api_base", LLMConfig.api_base),
        api_key=llm_raw.get("api_key", ""),
        model=llm_raw.get("model", LLMConfig.model),
        use_native_thinking=llm_raw.get("use_native_thinking", LLMConfig.use_native_thinking),
        temperature=llm_raw.get("temperature", LLMConfig.temperature),
        max_tokens=llm_raw.get("max_tokens", LLMConfig.max_tokens),
        timeout=llm_raw.get("timeout", LLMConfig.timeout),
        retry_count=llm_raw.get("retry_count", LLMConfig.retry_count),
        retry_delay=llm_raw.get("retry_delay", LLMConfig.retry_delay),
    )

    disc_raw = data.get("discussion", {})
    discussion = DiscussionConfig(**{k: disc_raw.get(k, v) for k, v in DiscussionConfig().__dict__.items()})

    mem_raw = data.get("memory", {})
    cs_raw = mem_raw.get("conversation_stream", {})
    conversation_stream = ConversationStreamConfig(
        recent_messages_count=cs_raw.get("recent_messages_count", ConversationStreamConfig.recent_messages_count),
        summary_batch_size=cs_raw.get("summary_batch_size", ConversationStreamConfig.summary_batch_size),
    )

    _wb_defaults = WhiteboardConfig()
    wb_raw = mem_raw.get("whiteboard", {})
    whiteboard = WhiteboardConfig(
        max_tokens=wb_raw.get("max_tokens", _wb_defaults.max_tokens),
        auto_update_interval=wb_raw.get("auto_update_interval", _wb_defaults.auto_update_interval),
        compression_threshold_chars=wb_raw.get("compression_threshold_chars", _wb_defaults.compression_threshold_chars),
        cold_storage_ttl=wb_raw.get("cold_storage_ttl", _wb_defaults.cold_storage_ttl),
        sections=wb_raw.get("sections", _wb_defaults.sections),
    )
    _arch_defaults = ArchiveConfig()
    arch_raw = mem_raw.get("archive", {})
    archive = ArchiveConfig(
        enabled=arch_raw.get("enabled", _arch_defaults.enabled),
        retrieval_top_k=arch_raw.get("retrieval_top_k", _arch_defaults.retrieval_top_k),
        retrieval_strategy=arch_raw.get("retrieval_strategy", _arch_defaults.retrieval_strategy),
        index_categories=arch_raw.get("index_categories", _arch_defaults.index_categories),
    )
    memory = MemoryConfig(
        conversation_stream=conversation_stream,
        whiteboard=whiteboard,
        archive=archive,
    )

    ctx_raw = data.get("context", {})
    alloc_raw = ctx_raw.get("allocation", {})
    allocation = ContextAllocation(**{k: alloc_raw.get(k, v) for k, v in ContextAllocation().__dict__.items()})
    context = ContextConfig(
        max_prompt_tokens=ctx_raw.get("max_prompt_tokens", ContextConfig.max_prompt_tokens),
        allocation=allocation,
        reserve_for_generation=ctx_raw.get("reserve_for_generation", ContextConfig.reserve_for_generation),
    )

    human_raw = data.get("human", {})
    human = HumanConfig(**{k: human_raw.get(k, v) for k, v in HumanConfig().__dict__.items()})

    out_raw = data.get("output", {})
    output = OutputConfig(
        transcript_format=out_raw.get("transcript", {}).get("format", OutputConfig.transcript_format),
        transcript_include_metadata=out_raw.get("transcript", {}).get("include_metadata", OutputConfig.transcript_include_metadata),
        digest_auto_generate=out_raw.get("digest", {}).get("auto_generate", OutputConfig.digest_auto_generate),
        digest_format=out_raw.get("digest", {}).get("format", OutputConfig.digest_format),
        report_auto_generate=out_raw.get("report", {}).get("auto_generate", OutputConfig.report_auto_generate),
        report_format=out_raw.get("report", {}).get("format", OutputConfig.report_format),
    )

    stor_raw = data.get("storage", {})
    storage = StorageConfig(**{k: stor_raw.get(k, v) for k, v in StorageConfig().__dict__.items()})

    log_raw = data.get("logging", {})
    logging_cfg = LoggingConfig(**{k: log_raw.get(k, v) for k, v in LoggingConfig().__dict__.items()})

    _mon_defaults = MonitorConfig()
    mon_raw = data.get("monitor", {})
    monitor = MonitorConfig(
        enabled=mon_raw.get("enabled", _mon_defaults.enabled),
        density_high_threshold=mon_raw.get("density_high_threshold", _mon_defaults.density_high_threshold),
        consecutive_high_trigger=mon_raw.get("consecutive_high_trigger", _mon_defaults.consecutive_high_trigger),
        rounds_since_story_trigger=mon_raw.get("rounds_since_story_trigger", _mon_defaults.rounds_since_story_trigger),
        rounds_since_anchor_trigger=mon_raw.get("rounds_since_anchor_trigger", _mon_defaults.rounds_since_anchor_trigger),
        dormant_concept_threshold=mon_raw.get("dormant_concept_threshold", _mon_defaults.dormant_concept_threshold),
        extend_ratio_threshold=mon_raw.get("extend_ratio_threshold", _mon_defaults.extend_ratio_threshold),
        breathing_suggestion=mon_raw.get("breathing_suggestion", _mon_defaults.breathing_suggestion),
        readability_abstract_threshold=mon_raw.get("readability_abstract_threshold", _mon_defaults.readability_abstract_threshold),
        readability_long_sentence_threshold=mon_raw.get("readability_long_sentence_threshold", _mon_defaults.readability_long_sentence_threshold),
        readability_entropy_threshold=mon_raw.get("readability_entropy_threshold", _mon_defaults.readability_entropy_threshold),
        readability_consecutive_trigger=mon_raw.get("readability_consecutive_trigger", _mon_defaults.readability_consecutive_trigger),
        # 调度器防线配置
        novelty_low_threshold=mon_raw.get("novelty_low_threshold", _mon_defaults.novelty_low_threshold),
        repetition_topic_shift_speeches=mon_raw.get("repetition_topic_shift_speeches", _mon_defaults.repetition_topic_shift_speeches),
        repetition_exhausted_speeches=mon_raw.get("repetition_exhausted_speeches", _mon_defaults.repetition_exhausted_speeches),
        recent_speak_window=mon_raw.get("recent_speak_window", _mon_defaults.recent_speak_window),
        closing_window_min=mon_raw.get("closing_window_min", _mon_defaults.closing_window_min),
        closing_window_max=mon_raw.get("closing_window_max", _mon_defaults.closing_window_max),
        anchor_soft_trigger=mon_raw.get("anchor_soft_trigger", _mon_defaults.anchor_soft_trigger),
        anchor_medium_trigger=mon_raw.get("anchor_medium_trigger", _mon_defaults.anchor_medium_trigger),
        anchor_hard_trigger=mon_raw.get("anchor_hard_trigger", _mon_defaults.anchor_hard_trigger),
    )

    # 搜索配置
    search_raw = data.get("search", {})
    _search_defaults = SearchConfig()
    import os
    search = SearchConfig(
        enabled=search_raw.get("enabled", _search_defaults.enabled),
        api_key=search_raw.get("api_key", "") or os.environ.get("TAVILY_API_KEY", ""),
        max_results=search_raw.get("max_results", _search_defaults.max_results),
        max_queries_per_intent=search_raw.get("max_queries_per_intent", _search_defaults.max_queries_per_intent),
    )

    return SalonConfig(
        llm=llm, discussion=discussion,
        memory=memory, context=context, human=human, output=output,
        storage=storage, logging=logging_cfg, monitor=monitor, search=search,
    )


def load_config(config_path: str | None = None) -> SalonConfig:
    load_dotenv()

    # Load default config
    default_path = Path("config/default.yaml")
    default_data: dict[str, Any] = {}
    if default_path.exists():
        with open(default_path, "r", encoding="utf-8") as f:
            default_data = yaml.safe_load(f) or {}

    # Load local.yaml overrides (auto-loaded if exists)
    local_path = Path("config/local.yaml")
    if local_path.exists():
        with open(local_path, "r", encoding="utf-8") as f:
            local_data = yaml.safe_load(f) or {}
        default_data = _deep_merge(default_data, local_data)

    # Load explicit override config (if provided, takes precedence over local)
    if config_path:
        override_path = Path(config_path)
        if override_path.exists():
            with open(override_path, "r", encoding="utf-8") as f:
                override_data = yaml.safe_load(f) or {}
            default_data = _deep_merge(default_data, override_data)

    config = _build_config_from_dict(default_data)

    # Environment variable overrides (SALON_* takes precedence)
    env_api_base = os.environ.get("SALON_API_BASE") or os.environ.get("ANTHROPIC_BASE_URL")
    env_api_key = os.environ.get("SALON_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    env_model = os.environ.get("SALON_MODEL") or os.environ.get("ANTHROPIC_MODEL")

    if env_api_base:
        config.llm.api_base = env_api_base
    if env_api_key:
        config.llm.api_key = env_api_key
    if env_model:
        config.llm.model = env_model

    return config
