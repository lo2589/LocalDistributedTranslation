@echo off
chcp 65001 >nul
echo [启动] 分布式翻译主机 Master ...
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe master\master.py
) else (
    python master\master.py
)
pause
