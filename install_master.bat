@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM Local Distributed Translation - Master Install Script
REM Steps:
REM   1. Detect Python 64-bit
REM   2. Install pip dependencies
REM   3. Start Master (background)
REM   4. Input Slave IPs + ping verify
REM   5. Write master/config.yaml + show status
REM ============================================================

cd /d "%~dp0"

set MASTER_PORT=8000

echo.
echo ============================================
echo   Local Distributed Translation - Master
echo ============================================
echo.

REM ============ Step 1: Python 64-bit ============
echo [1/5] Checking Python 64-bit...
if defined PYTHON (
    set "PYEXE=!PYTHON!"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python not found
        echo         Download: https://www.python.org/downloads/windows/
        echo         Or set PYTHON env var to a 64-bit Python path:
        echo             set PYTHON=C:\Path\To\python.exe
        pause
        exit /b 1
    )
    set "PYEXE=python"
)

"!PYEXE!" scripts\check_python.py >nul 2>&1
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
echo [2/5] Installing pip dependencies (fastapi uvicorn httpx pydantic pyyaml)...
"!PYEXE!" -m pip install --quiet --disable-pip-version-check fastapi uvicorn httpx pydantic pyyaml
if errorlevel 1 (
    echo        Retrying with --user...
    "!PYEXE!" -m pip install --user --quiet --disable-pip-version-check fastapi uvicorn httpx pydantic pyyaml
    if errorlevel 1 (
        echo [ERROR] pip install failed
        pause
        exit /b 1
    )
)
echo        OK

REM ============ Step 3: Start Master (background) ============
echo.
echo [3/5] Starting Master service (port !MASTER_PORT!)...

REM kill old process if port taken
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":!MASTER_PORT! "') do (
    echo        Killing old process on port !MASTER_PORT! (PID=%%a)...
    taskkill /F /PID %%a >nul 2>&1
    timeout /t 2 /nobreak >nul
)

REM 日志统一放到 logs\，启动前清理旧日志
if not exist logs (
    mkdir logs
)
if exist logs\master.log (
    del /q logs\master.log
)

set "PYTHONPATH=%~dp0;!PYTHONPATH!"
start "LocalTrans-Master" /min cmd /c ""!PYEXE!" -m uvicorn master.master:app --host 0.0.0.0 --port !MASTER_PORT! > logs\master.log 2>&1"

echo        Waiting for Master service...
set /a WAIT=0
:wait_master
timeout /t 2 /nobreak >nul
curl -s --max-time 2 http://127.0.0.1:!MASTER_PORT!/health >nul 2>&1
if not errorlevel 1 goto master_ready
set /a WAIT+=1
if !WAIT! GEQ 20 (
    echo [ERROR] Master startup timeout (40s)
    echo         Check logs\master.log:
    if exist logs\master.log (
        echo        ---------------- logs\master.log ----------------
        type logs\master.log
        echo        -----------------------------------------------
    )
    pause
    exit /b 1
)
goto wait_master

:master_ready
echo        OK (Master running on port !MASTER_PORT!)

REM ============ Step 4: Input Slave IPs ============
echo.
echo [4/5] Configuring Slave nodes
echo ============================================
echo   Enter Slave IP:port one per line
echo   Format: 192.168.1.101:8001
echo   Press Enter on empty line to finish
echo ============================================
echo.

set SLAVE_COUNT=0
set "CFG_PATH=master\config.yaml"

REM Pre-write the top-level config
(
echo master:
echo   host: '0.0.0.0'
echo   port: !MASTER_PORT!
echo   slaves:
) > "!CFG_PATH!"

:input_loop
set /p "INPUT=Slave #!SLAVE_COUNT! (Enter=done): "

REM Empty = done
if "!INPUT!"=="" goto input_done

REM format check: must contain ":"
echo !INPUT! | find ":" >nul
if errorlevel 1 (
    echo        [SKIP] Bad format (missing ":"); expected IP:port
    goto input_loop
)

REM try to ping health
echo        Verifying http://!INPUT!/health ...
curl -s --max-time 3 http://!INPUT!/health >nul 2>&1
if errorlevel 1 (
    echo        [WARN] Could not reach http://!INPUT!/health
    set CONFIRM=n
    set /p "CONFIRM=        Add anyway? (y/n): "
    if /i not "!CONFIRM!"=="y" goto input_loop
)

set /a SLAVE_COUNT+=1
>> "!CFG_PATH!" echo     - name: 'slave-!SLAVE_COUNT!'
>> "!CFG_PATH!" echo       url: 'http://!INPUT!'
>> "!CFG_PATH!" echo       weight: 1
echo        [OK] Added http://!INPUT!
echo.
goto input_loop

:input_done
if !SLAVE_COUNT!==0 (
    echo.
    echo [WARN] No slaves configured - Master will have nothing to route to.
    set CONFIRM=n
    set /p "CONFIRM=        Continue anyway? (y/n): "
    if /i not "!CONFIRM!"=="y" exit /b 0
)

REM ============ Step 5: Write config.yaml ============
echo.
echo [5/5] master\config.yaml already written during input.
echo        OK (slaves: !SLAVE_COUNT!)
type "!CFG_PATH!" | findstr /v "^$" | findstr /n ".*"

REM ============ Summary ============
set LOCAL_IP=127.0.0.1
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /C:"IPv4"') do (
    set "TMP=%%i"
    set "TMP=!TMP: =!"
    if "!TMP!"=="" continue
    if not "!TMP:~0,3!"=="127" (
        set "LOCAL_IP=!TMP!"
        goto got_my_ip
    )
)
:got_my_ip

echo.
echo ============================================
echo   MASTER READY
echo ============================================
echo   IP:         !LOCAL_IP!:!MASTER_PORT!
echo   URL:        http://!LOCAL_IP!:!MASTER_PORT!
echo   Docs:       http://!LOCAL_IP!:!MASTER_PORT!/docs
echo   Health:     http://!LOCAL_IP!:!MASTER_PORT!/health
echo   Slaves:     !SLAVE_COUNT! node(s)
echo.
echo   Client setup (on other machines):
echo     set LOCALTRANS_MASTER_URL=http://!LOCAL_IP!:!MASTER_PORT!
echo     pip install localtrans
echo     python -c "from localtrans import translate; print(translate('Hello', 'zh'))"
echo.
echo   Master running in background (minimized window)
echo   Stop: taskkill /F /FI "WINDOWTITLE eq LocalTrans-Master*"
echo ============================================
echo.
pause
