class AgentRegistry:
    def __init__(self):
        self._agents = {}

    def register(self, role: str, agent_instance):
        self._agents[role] = agent_instance
        print(f"[Registry] Registered agent: {role}")

    def get_agent(self, role: str):
        return self._agents.get(role)

    def list_agents(self):
        return list(self._agents.keys())
agent_registry = AgentRegistry()