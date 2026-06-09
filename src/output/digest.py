from __future__ import annotations

from pathlib import Path


def save_digest(digest_text: str, path: str | Path, overview: str = "") -> None:
    """Save digest to file, optionally prepending an overview section."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if overview:
        content = overview.rstrip() + "\n\n---\n\n" + digest_text
    else:
        content = digest_text
    p.write_text(content, encoding="utf-8")
