@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Python environment check...
where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py -3
) else (
  set PY=python
)

if not exist .venv (
  echo [2/4] Creating .venv...
  %PY% -m venv .venv
)

call .venv\Scripts\activate.bat

echo [3/4] Installing requirements...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [4/4] Starting VCU crawler at http://127.0.0.1:8000
start "VCU Local Site" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000"
python main.py
endlocal
