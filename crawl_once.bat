@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Please run run_local.bat once first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -c "from database import init_db; init_db(); from crawler import run_crawl; print(run_crawl())"
pause
endlocal
