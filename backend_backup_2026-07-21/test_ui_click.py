from app.tools.ui_click import handle_ui_click

print("Program started")
input("Press Enter after opening the window you want to test...")

command = input("Command: ")

print("Step 1")
result = handle_ui_click(command)

print("Result:", result)

input("Press Enter to exit...")