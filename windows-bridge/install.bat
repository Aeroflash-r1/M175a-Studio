@echo off
REM M175 Bridge installer - puts everything on D:
setlocal
set ROOT=D:\M175Bridge

echo === M175 Bridge installer ===
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install from https://python.org
  echo (tick "Add python.exe to PATH" in the installer^)
  pause & exit /b 1
)

echo [1/3] Creating virtualenv on D: ...
if not exist %ROOT%\venv python -m venv %ROOT%\venv
call %ROOT%\venv\Scripts\activate.bat

echo [2/3] Installing Python dependencies ...
python -m pip install --upgrade pip >nul
pip install -r %ROOT%\requirements.txt
if errorlevel 1 ( echo pip install FAILED & pause & exit /b 1 )

echo [3/3] Creating desktop launcher ...
set SCRIPT=%PUBLIC%\Desktop\M175Bridge.bat
> "%SCRIPT%" echo @echo off
>> "%SCRIPT%" echo cd /d %ROOT%
>> "%SCRIPT%" echo call venv\Scripts\activate.bat
>> "%SCRIPT%" echo python run.py
>> "%SCRIPT%" echo pause
echo Desktop shortcut created: M175Bridge.bat

echo.
echo Done! Run: D:\M175Bridge\run.bat   (or the desktop icon)
pause
