from __future__ import annotations

from pydantic import BaseModel, Field


class AgentMeta(BaseModel):
    id: str
    name: str
    role: str = "participant"
    group: str = ""
    tags: list[str] = []
    avatar: str = ""
    gender: str = ""
    voice: str = ""
    voice_description: str = ""
    soul_path: str = ""


class AgentCreate(BaseModel):
    name: str
    role: str = "participant"
    group: str = ""
    tags: list[str] = []
    avatar: str = ""
    gender: str = ""
    voice: str = ""
    voice_description: str = ""
    soul_content: str = ""


class AgentUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    group: str | None = None
    tags: list[str] | None = None
    avatar: str | None = None
    gender: str | None = None
    voice: str | None = None
    voice_description: str | None = None
    soul_content: str | None = None


class GroupMeta(BaseModel):
    id: str
    name: str
    description: str = ""
    emoji: str = ""


class GroupCreate(BaseModel):
    name: str
    description: str = ""
    emoji: str = ""


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    emoji: str | None = None


class SessionCreate(BaseModel):
    topic: str
    agent_ids: list[str]
    mode: str = "salon"
    mode_config: dict | None = None  # 模式专属配置，结构随 mode 变化


class SessionInfo(BaseModel):
    session_id: str
    topic: str
    agent_ids: list[str]
    agent_names: list[str] = []
    mode: str = "salon"
    state: str
    round_count: int
    created_at: str
    archived: bool = False
    mode_config: dict | None = None


class ChatMessage(BaseModel):
    id: str
    round: int
    agent_id: str
    agent_name: str
    agent_role: str
    content: str
    speech_type: str
    mentions: list[str] = []
    timestamp: str


class CommandRequest(BaseModel):
    command: str
    target: str | None = None
    content: str | None = None


class ConfigUpdate(BaseModel):
    llm: dict | None = None
    discussion: dict | None = None
