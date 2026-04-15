@echo off
cd /d "C:\Testing_Fi\instagram_auto_poster"
call .\venv\Scripts\Activate.ps1
python main.py %*
pause