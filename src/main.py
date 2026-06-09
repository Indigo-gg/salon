from __future__ import annotations

import argparse
import logging
import sys
import threading

from src.config import load_config
from src.core.orchestrator import Orchestrator


# Default agent pool for auto-selection with --participants
DEFAULT_PARTICIPANT_POOL = [
    "philosopher_east", "philosopher_west", "scientist",
    "existentialist", "marxist", "ai_observer",
]


def setup_logging(logging_cfg) -> None:
    """Configure logging with console and/or file handlers."""
    level = getattr(logging, logging_cfg.level.upper(), logging.INFO)
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    handlers: list[logging.Handler] = []

    if logging_cfg.console:
        handlers.append(logging.StreamHandler(sys.stderr))

    if logging_cfg.file:
        from pathlib import Path
        log_path = Path(logging_cfg.file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_path), encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
        handlers.append(fh)

    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S", handlers=handlers)
    # Suppress noisy HTTP client logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("openai._base_client").setLevel(logging.WARNING)


def input_reader(orchestrator: Orchestrator) -> None:
    """Read input in a separate thread and feed to orchestrator."""
    while True:
        try:
            line = input()
            orchestrator.human_interface.signal_input(line)
        except EOFError:
            break
        except Exception:
            break


def build_agent_ids(args, config) -> list[str]:
    """Build the agent ID list from CLI arguments.

    Priority: --agents > --participants > config default.
    """
    if args.agents:
        # Explicit agent IDs (comma-separated)
        return [a.strip() for a in args.agents.split(",") if a.strip()]

    # Auto-select from pool based on --participants count
    count = args.participants or config.discussion.default_participant_count
    return DEFAULT_PARTICIPANT_POOL[:count]


def main() -> None:
    parser = argparse.ArgumentParser(description="Salon — Multi-Agent Dialogue System")
    parser.add_argument("--config", type=str, default=None, help="Path to config YAML file")
    parser.add_argument("--topic", type=str, required=True, help="Discussion topic")
    parser.add_argument("--agents", type=str, default=None,
                        help="Comma-separated agent IDs (e.g. moderator,philosopher_east,scientist,scribe)")
    parser.add_argument("--participants", type=int, default=None,
                        help="Number of participants (auto-select from pool, 3-5)")
    parser.add_argument("--mode", type=str, default="salon", choices=["salon", "interview"],
                        help="Discussion mode: salon (multi-agent) or interview (host mode)")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config.logging)

    agent_ids = build_agent_ids(args, config)

    orchestrator = Orchestrator(config)

    # Start input reader in background thread
    reader_thread = threading.Thread(target=input_reader, args=(orchestrator,), daemon=True)
    reader_thread.start()

    try:
        orchestrator.run(args.topic, agent_ids, mode=args.mode)
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
