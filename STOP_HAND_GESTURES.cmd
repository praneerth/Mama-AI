@echo off
powershell -NoProfile -Command "$items = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*hand_gesture_stable.py*' -or $_.CommandLine -like '*hand_gesture_agent.py*' }; if ($items) { $items | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Write-Host 'Mama AI gesture processes stopped.' } else { Write-Host 'No Mama AI gesture process is running.' }"
pause
