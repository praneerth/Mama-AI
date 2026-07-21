import subprocess
def run_command(cmd: str):
    return subprocess.check_output(cmd, shell=True).decode()