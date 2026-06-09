from __future__ import annotations

import yaml
from pathlib import Path

from fastapi import APIRouter

from src.config import load_config

router = APIRouter()

CONFIG_PATH = Path("config/default.yaml")
LOCAL_CONFIG_PATH = Path("config/local.yaml")


@router.get("")
def get_config():
    config = load_config()
    return {
        "llm": {
            "api_base": config.llm.api_base,
            "api_key": config.llm.api_key,
            "model": config.llm.model,
            "temperature": config.llm.temperature,
            "max_tokens": config.llm.max_tokens,
            "use_native_thinking": config.llm.use_native_thinking,
            "timeout": config.llm.timeout,
        },
        "discussion": {
            "language": config.discussion.language,
            "max_rounds": config.discussion.max_rounds,
            "min_rounds": config.discussion.min_rounds,
            "max_speech_chars": config.discussion.max_speech_chars,
            "min_speech_chars": config.discussion.min_speech_chars,
            "default_participant_count": config.discussion.default_participant_count,
        },
        "search": {
            "enabled": config.search.enabled,
            "api_key": config.search.api_key,
            "max_results": config.search.max_results,
        },
        "memory": {
            "whiteboard": {
                "auto_update_interval": config.memory.whiteboard.auto_update_interval,
                "cold_storage_ttl": config.memory.whiteboard.cold_storage_ttl,
            },
        },
        "output": {
            "digest_auto_generate": config.output.digest_auto_generate,
            "report_auto_generate": config.output.report_auto_generate,
        },
        "logging": {
            "level": config.logging.level,
        },
        "monitor": {
            "enabled": config.monitor.enabled,
        },
    }


@router.put("")
def update_config(updates: dict):
    # Read existing local config
    local_data = {}
    if LOCAL_CONFIG_PATH.exists():
        local_data = yaml.safe_load(LOCAL_CONFIG_PATH.read_text(encoding="utf-8")) or {}

    # Merge updates
    for key, value in updates.items():
        if isinstance(value, dict) and key in local_data and isinstance(local_data[key], dict):
            local_data[key].update(value)
        else:
            local_data[key] = value

    LOCAL_CONFIG_PATH.write_text(
        yaml.dump(local_data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return {"status": "updated"}
