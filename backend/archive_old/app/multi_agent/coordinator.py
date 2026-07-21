from app.multi_agent.agent_registry import agent_registry
from app.multi_agent.planner_agent import PlannerAgent
from app.multi_agent.reasoning_agent import ReasoningAgent
from app.multi_agent.vision_agent import VisionAgent
from app.multi_agent.memory_agent import MemoryAgent
from app.multi_agent.desktop_agent import DesktopAgent
from app.multi_agent.learning_agent import LearningAgent
from app.multi_agent.verification_agent import VerificationAgent
from app.multi_agent.coding_agent import CodingAgent
from app.multi_agent.browser_agent import BrowserAgent
from app.multi_agent.voice_agent import VoiceAgent

class MultiAgentCoordinator:
    def __init__(self):
        # Instantiate and register all agents
        self.planner = PlannerAgent()
        self.reasoner = ReasoningAgent()
        self.vision = VisionAgent()
        self.memory = MemoryAgent()
        self.desktop = DesktopAgent()
        self.learning = LearningAgent()
        self.verification = VerificationAgent()
        self.coding = CodingAgent()
        self.browser = BrowserAgent()
        self.voice = VoiceAgent()

        agent_registry.register("planner", self.planner)
        agent_registry.register("reasoner", self.reasoner)
        agent_registry.register("vision", self.vision)
        agent_registry.register("memory", self.memory)
        agent_registry.register("desktop", self.desktop)
        agent_registry.register("learning", self.learning)
        agent_registry.register("verification", self.verification)
        agent_registry.register("coding", self.coding)
        agent_registry.register("browser", self.browser)
        agent_registry.register("voice", self.voice)

    def execute_goal(self, goal: str) -> dict:
        print(f"\n[Coordinator] Starting Multi-Agent pipeline for: {goal}")
        
        # 1. Memory Agent retrieves context
        memories = self.memory.get_context(goal)
        context = ", ".join([f"{m[1]}: {m[2]}" for m in memories]) if memories else "None"
        
        # 2. Reasoning Agent checks safety
        reasoning_decision = self.reasoner.analyze(goal, context)
        
        # 3. Planner Agent generates steps
        steps = self.planner.run(goal)
        
        results = []
        overall_success = True
        
        # 4. Desktop Agent executes actions sequentially
        for step in steps:
            print(f"[Coordinator] Step execution: {step}")
            action_result = self.desktop.execute_action(step)
            results.append({"step": step, "result": action_result})
            
        # 5. Verification Agent inspects final output
        verified = self.verification.verify(goal)
        
        # 6. Learning Agent writes log
        self.learning.log_experience(goal, ", ".join(steps), "Completed execution run", verified)
        
        return {
            "goal": goal,
            "reasoning": reasoning_decision,
            "steps": steps,
            "results": results,
            "verified": verified
        }
multi_agent_coordinator = MultiAgentCoordinator()