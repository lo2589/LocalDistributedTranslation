@echo off
chcp 65001 >nul
echo [启动] 分布式翻译从机 Slave ...
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe slave\slave.py
) else (
    python slave\slave.py
)
pause
