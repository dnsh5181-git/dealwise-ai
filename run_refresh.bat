@echo off
REM DealWise daily price refresh — re-ingests tracked queries and records a fresh
REM real price point per product, building genuine 90-day history over time.
REM Scheduled via Windows Task Scheduler (see README). Logs to refresh.log.
REM %~dp0 is this file's folder, so the task works regardless of working directory.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app.retailers.refresh >> "refresh.log" 2>&1
