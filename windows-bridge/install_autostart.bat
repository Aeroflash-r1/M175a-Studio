@echo off
REM Register M175 Bridge to auto-start at every login
schtasks /Create /F /SC ONLOGON /TN "M175Bridge" ^
  /TR "D:\M175Bridge\venv\Scripts\python.exe -u D:\M175Bridge\run.py" ^
  /RL LIMITED
if %errorlevel%==0 (
  echo Auto-start registered. The bridge runs at every login.
) else (
  echo Failed - run this file as Administrator.
)
pause
