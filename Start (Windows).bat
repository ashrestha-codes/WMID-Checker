@echo off
cd /d "%~dp0"
if not exist .venv (
  echo First run: installing... this takes a minute.
  py -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
  .venv\Scripts\python -m playwright install chromium
)
.venv\Scripts\python app.py
pause
