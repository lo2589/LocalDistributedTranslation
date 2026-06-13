@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM Local Distributed Translation - Slave 6-step self-test
REM Steps:
REM   1. Detect Python 64-bit
REM   2. Install pip dependencies
REM   3. Detect / start Ollama + pull model
REM   4. Start Slave service (background)
REM   5. Parallel translation self-test
REM   6. Show local IP (ready to be added to Master)
REM ============================================================

cd /d "%~dp0"

set PORT=8001
set PARAGRAPHS=5
set OLLAMA_MODEL=hunyuan-mt:1.8b-q4

echo.
echo ============================================
echo   Local Distributed Translation - Slave
echo ============================================
echo.

REM ============ Step 1: Python 64-bit ============
echo [1/6] Checking Python 64-bit...
if defined PYTHON (
    set "PYEXE=!PYTHON!"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found in PATH
        echo         Download: https://www.python.org/downloads/windows/
        echo         Or set PYTHON env var to a 64-bit Python path:
        echo             set PYTHON=C:\Path\To\python.exe
        pause
        exit /b 1
    )
    set "PYEXE=python"
)

"!PYEXE!" scripts\check_python.py
if errorlevel 1 (
    echo [ERROR] Python detection script failed
    pause
    exit /b 1
)
for /f "delims=" %%i in ('"!PYEXE!" scripts\check_python.py') do set BITS=%%i
if not "!BITS!"=="64" (
    echo [ERROR] Python is !BITS!-bit, must be 64-bit
    echo         Current: !PYEXE!
    echo         Set PYTHON env var to 64-bit Python, e.g.:
    echo             set PYTHON=C:\Path\To\python.exe
    pause
    exit /b 1
)
echo        OK (64-bit: !PYEXE!)

REM ============ Step 2: Install deps ============
echo.
echo [2/6] Installing pip dependencies (fastapi uvicorn httpx pyyaml)...
"!PYEXE!" -m pip install --quiet --disable-pip-version-check fastapi uvicorn httpx pydantic pyyaml
if errorlevel 1 (
    echo [ERROR] pip install failed, trying with --user ...
    "!PYEXE!" -m pip install --user --quiet --disable-pip-version-check fastapi uvicorn httpx pydantic pyyaml
    if errorlevel 1 (
        echo [ERROR] pip install failed even with --user
        pause
        exit /b 1
    )
)
echo        OK

REM ============ Step 3: Ollama check ============
echo.
echo [3/6] Checking Ollama and model (%OLLAMA_MODEL%)...
"!PYEXE!" scripts\check_ollama.py %OLLAMA_MODEL%
set OLLAMA_RC=!errorlevel!

if !OLLAMA_RC!==1 (
    echo [ERROR] Ollama not installed
    echo         Download: https://ollama.com/download
    pause
    exit /b 1
)
if !OLLAMA_RC!==2 (
    echo        Ollama not running, starting...
    start "Ollama" /min ollama serve
    echo        Waiting 8 seconds for Ollama to start...
    timeout /t 8 /nobreak >nul
    REM 再次检查
    "!PYEXE!" scripts\check_ollama.py %OLLAMA_MODEL% >nul 2>&1
    set RETRY_RC=!errorlevel!
    if !RETRY_RC!==1 (
        echo [ERROR] Ollama still not running after start
        echo         Please run manually: ollama serve
        pause
        exit /b 1
    )
    set OLLAMA_RC=!RETRY_RC!
)
if !OLLAMA_RC!==3 (
    echo        Model not found, pulling %OLLAMA_MODEL% ...
    ollama pull %OLLAMA_MODEL%
    if errorlevel 1 (
        echo [ERROR] Model pull failed (network issue?)
        echo         Try again with: ollama pull %OLLAMA_MODEL%
        pause
        exit /b 1
    )
)
echo        OK (model: %OLLAMA_MODEL%)

REM ============ Step 4: Start Slave (background) ============
echo.
echo [4/6] Starting Slave service (port !PORT!)...

REM 如果端口被占用，杀掉旧进程
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":!PORT! "') do (
    echo        Killing old process on port !PORT! (PID=%%a)...
    taskkill /F /PID %%a >nul 2>&1
    timeout /t 2 /nobreak >nul
)

REM 启动 Slave 服务：使用 PYEXE，让 Python 从项目根目录运行
REM 日志统一放到 logs\，启动前清理旧日志
if not exist logs (
    mkdir logs
)
if exist logs\slave.log (
    del /q logs\slave.log
)
set "PYTHONPATH=%~dp0;!PYTHONPATH!"
start "LocalTrans-Slave" /min cmd /c ""!PYEXE!" -m uvicorn slave.slave:app --host 0.0.0.0 --port !PORT! > logs\slave.log 2>&1"

echo        Waiting for service to come online...
set /a WAIT=0
:wait_slave
timeout /t 2 /nobreak >nul
curl -s --max-time 2 http://127.0.0.1:!PORT!/health >nul 2>&1
if not errorlevel 1 goto slave_ready
set /a WAIT+=1
if !WAIT! GEQ 20 (
    echo [ERROR] Slave startup timeout (40s)
    echo         Check logs\slave.log for details:
    if exist logs\slave.log (
        echo        ---------------- logs\slave.log ----------------
        type logs\slave.log
        echo        -----------------------------------------------
    )
    pause
    exit /b 1
)
goto wait_slave

:slave_ready
echo        OK (Slave running on port !PORT!)

REM ============ Step 5: Parallel translation self-test ============
echo.
echo [5/6] Running parallel translation self-test (!PARAGRAPHS! paragraphs)...
"!PYEXE!" scripts\slave_selftest.py !PORT!
if errorlevel 1 (
    echo [ERROR] Self-test failed
    echo         Check logs\slave.log for details
    if exist logs\slave.log (
        echo        ---------------- logs\slave.log ----------------
        type logs\slave.log
        echo        -----------------------------------------------
    )
    pause
    exit /b 1
)

REM ============ Step 6: Show local IP ============
echo.
echo [6/6] Getting local IP...
set LOCAL_IP=127.0.0.1
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /C:"IPv4"') do (
    set "TMP=%%i"
    set "TMP=!TMP: =!"
    if "!TMP!"=="" continue
    REM 跳过 127 开头的，取第一个非回环 IP
    if not "!TMP:~0,3!"=="127" (
        set "LOCAL_IP=!TMP!"
        goto got_ip
    )
)
:got_ip

echo.
echo ============================================
echo   SLAVE READY
echo ============================================
echo   IP:    !LOCAL_IP!:!PORT!
echo   URL:   http://!LOCAL_IP!:!PORT!
echo   Model: %OLLAMA_MODEL% (Ollama backend)
echo.
echo   Copy this line into master's master\config.yaml:
echo.
echo     - name: "slave-!LOCAL_IP!"
echo       url: "http://!LOCAL_IP!:!PORT!"
echo       weight: 1
echo.
echo   Slave running in background (minimized window)
echo   Stop command: taskkill /F /FI "WINDOWTITLE eq LocalTrans-Slave*"
echo ============================================
echo.
pause
