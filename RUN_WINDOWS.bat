@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (set "PYTHON=py -3") else (set "PYTHON=python")
if not exist ".venv\Scripts\python.exe" (
  echo Creating isolated Python environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto :failed
)
set "GEMINI_API_KEY=AQ.Ab8RN6LwtDba4vrb4S2aHp12CnhuHrote9JtoQsPzhhkgbm7RQ"
set "GEMINI_MODEL=gemini-3.5-flash-lite"
echo Installing requirements...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
start "" "http://127.0.0.1:8000"
echo Starting local VentureOS at http://127.0.0.1:8000
echo Close this window to stop the app.
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
exit /b 0
:failed
echo Unable to start. Make sure Python 3.10+ is installed and internet is available for first-time dependency installation.
pause
