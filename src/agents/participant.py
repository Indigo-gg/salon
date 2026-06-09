from src.agents.base import BaseAgent


class ParticipantAgent(BaseAgent):
    def __init__(self, agent_id: str, soul_path: str, config):
        super().__init__(agent_id, soul_path, config)
        self.role = "participant"
