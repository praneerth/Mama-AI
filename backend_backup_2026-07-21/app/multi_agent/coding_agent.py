import subprocess
class CodingAgent:
    def __init__(self):
        self.role = "coding"

    def run_script(self, code_filepath: str) -> dict:
        print(f"[CodingAgent] Executing python script: {code_filepath}")
        try:
            res = subprocess.run(["python", code_filepath], capture_output=True, text=True, timeout=10)
            return {"success": res.returncode == 0, "stdout": res.stdout, "stderr": res.stderr}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Execution timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}