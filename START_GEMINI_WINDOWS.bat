@echo off
cd /d "%~dp0"
echo ======================================================
echo  VentureOS - Gemini Online AI (Auto-configured)
echo ======================================================
set "GEMINI_API_KEY=AQ.Ab8RN6LwtDba4vrb4S2aHp12CnhuHrote9JtoQsPzhhkgbm7RQ"
set "GEMINI_MODEL=gemini-3.5-flash-lite"
start "" "http://127.0.0.1:8000"
echo Starting VentureOS on http://127.0.0.1:8000
python -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
