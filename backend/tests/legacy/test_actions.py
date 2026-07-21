from app.automation.actions import execute_action
import time

print("Testing in 3 seconds...")

time.sleep(3)

execute_action("ctrl+l")
execute_action("type:https://google.com")
execute_action("enter")