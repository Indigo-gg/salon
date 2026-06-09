from __future__ import annotations

from pathlib import Path


def save_report(report_text: str, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(report_text, encoding="utf-8")
