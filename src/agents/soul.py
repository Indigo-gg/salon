from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Soul:
    name: str
    role: str
    basic_profile: str
    personality_traits: str
    self_perception: str
    behavioral_principles: str
    raw_text: str
    role_prompt: str = ""
    speech_style: str = ""
    core_thesis: str = ""

    def get_full_prompt(self) -> str:
        """Return the combined prompt: persona + role constraints."""
        if self.role_prompt:
            return self.raw_text + "\n\n---\n\n" + self.role_prompt
        return self.raw_text

    def inject_role(self, role_prompt_text: str) -> None:
        """Inject role-specific constraints into this soul."""
        self.role_prompt = role_prompt_text

    @classmethod
    def load(cls, path: str) -> Soul:
        text = Path(path).read_text(encoding="utf-8")

        # Parse the title: # Role — Name
        title_match = re.search(r"^#\s+(.+?)(?:\s*[—–-]\s*(.+))?$", text, re.MULTILINE)
        role = title_match.group(1).strip() if title_match else "participant"
        name = title_match.group(2).strip() if title_match and title_match.group(2) else role

        sections: dict[str, str] = {}
        current_section = ""
        current_content: list[str] = []

        for line in text.split("\n"):
            header_match = re.match(r"^##\s+(.+)", line)
            if header_match:
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = header_match.group(1).strip()
                current_content = []
            else:
                current_content.append(line)

        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        return cls(
            name=name,
            role=role,
            basic_profile=sections.get("你是谁", sections.get("基本画像", sections.get("Basic Profile", ""))),
            personality_traits=sections.get("你的内核", sections.get("性格特质", sections.get("Personality Traits", ""))),
            self_perception=sections.get("你的矛盾", sections.get("自我认知", sections.get("Self-Perception", ""))),
            behavioral_principles=sections.get("你怎么想", sections.get("行为准则", sections.get("Behavioral Principles", ""))),
            speech_style=sections.get("你怎么说话", sections.get("Speech Style", "")),
            raw_text=text,
            core_thesis=sections.get("核心主张", sections.get("Core Thesis", "")),
        )

