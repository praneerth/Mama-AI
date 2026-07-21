from app.cognition.verifier import verify
class VerificationAgent:
    def __init__(self):
        self.role = "verification"

    def verify(self, goal: str) -> bool:
        print(f"[VerificationAgent] Verifying goal achievement: {goal}")
        try:
            return verify(goal)
        except Exception as e:
            print(f"Verification failed: {e}")
            return False