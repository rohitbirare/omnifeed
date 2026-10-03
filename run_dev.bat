@echo off
echo ========================================================
echo Starting OmniFeed (Backend on :8000, Frontend on :3000)
echo ========================================================

REM Check if backend .venv exists
if exist backend\.venv\Scripts\activate.bat (
    echo Activating backend virtual environment...
    start "OmniFeed Backend (Port 8000)" cmd /k "cd backend && call .venv\Scripts\activate.bat && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
) else (
    echo Starting backend with system python...
    start "OmniFeed Backend (Port 8000)" cmd /k "cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
)

REM Start frontend server
start "OmniFeed Frontend (Port 3000)" cmd /k "cd frontend && python -m http.server 3000"

echo Both servers started in background windows.
echo Frontend: http://localhost:3000
echo Backend:  http://localhost:8000
echo ========================================================
