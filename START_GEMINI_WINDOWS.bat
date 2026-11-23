@echo off
cd /d "%~dp0"
echo ======================================================
echo  VentureOS - Gemini Online AI (Auto-configured)
echo ======================================================
set "GEMINI_API_KEY=YOUR_API_KEY"
set "GEMINI_MODEL=gemini-3.5-flash-lite"
start "" "http://127.0.0.1:8000"
echo Starting VentureOS on http://127.0.0.1:8000
python -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
