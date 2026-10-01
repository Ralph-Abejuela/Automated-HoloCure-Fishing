@echo off
where uv >nul 2>nul
if errorlevel 1 (
    echo Error: uv is not installed. See https://docs.astral.sh/uv/getting-started/installation/
    exit /b 1
)

uv sync
PAUSE
