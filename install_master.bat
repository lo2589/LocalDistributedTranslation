@echo off
REM Local Distributed Translation - Master 安装脚本
REM 功能：自测 + 启动 + 配置 Slave 节点 + 验证

setlocal enabledelayedexpansion

set MASTER_PORT=8000

echo ============================================
echo   Local Distributed Translation - Master 安装
echo ============================================
echo.

REM ============ 步骤 1: Python 64-bit ============
echo [1/5] 检测 Python 64-bit...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python
    echo        下载: https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python -c "import struct; print(struct.calcsize('P')*8)"') do set PYTHON_BITS=%%i
if not "!PYTHON_BITS!"=="64" (
    echo [错误] 必须用 64-bit Python
    pause
    exit /b 1
)
echo        [OK] Python 64-bit

REM ============ 步骤 2: 装依赖 ============
echo.
echo [2/5] 安装依赖...
if not exist .venv (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
)
.venv\Scripts\python.exe -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
.venv\Scripts\python.exe -m pip config set install.trusted-host pypi.tuna.tsinghua.edu.cn >nul 2>&1
.venv\Scripts\python.exe -m pip install --quiet fastapi uvicorn httpx pydantic pyyaml
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo        [OK] 依赖已就绪

REM ============ 步骤 3: 启动 Master（后台）============
echo.
echo [3/5] 启动 Master 服务（端口 !MASTER_PORT!）...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":!MASTER_PORT! " 2^>nul') do taskkill /F /PID %%a >nul 2>&1

cd /d "%~dp0"
start "LocalTrans-Master" /min cmd /c ".venv\Scripts\python.exe -m uvicorn master.master:app --host 0.0.0.0 --port !MASTER_PORT! > master.log 2>&1"

echo        等待服务启动...
set /a WAIT_COUNT=0
:wait_master
timeout /t 2 /nobreak >nul
curl -s --max-time 2 http://127.0.0.1:!MASTER_PORT!/health >nul 2>&1
if %errorlevel%==0 goto master_ready
set /a WAIT_COUNT+=1
if !WAIT_COUNT! GEQ 15 (
    echo [错误] Master 启动超时（30秒）
    echo        查看日志: master.log
    pause
    exit /b 1
)
goto wait_master

:master_ready
echo        [OK] Master 服务运行中

REM ============ 步骤 4: 配置 Slave 节点（逐行输入）============
echo.
echo [4/5] 配置 Slave 节点
echo ============================================
echo   逐行输入 Slave 的 IP:端口（按回车结束）
echo   格式: 192.168.1.101:8001
echo ============================================
echo.

REM 清空旧配置
set SLAVE_COUNT=0
set SLAVE_YAML=

:input_loop
set /p "INPUT=Slave #!SLAVE_COUNT! (回车结束): "
if "!INPUT!"=="" goto input_done

REM 简单格式校验（必须包含冒号）
echo !INPUT! | find ":" >nul
if %errorlevel% neq 0 (
    echo        [跳过] 格式错误，需为 IP:端口
    goto input_loop
)

REM 校验能连上（ping health）
echo        验证 !INPUT! ...
curl -s --max-time 3 http://!INPUT!/health >nul 2>&1
if %errorlevel% neq 0 (
    echo        [警告] 连不上 http://!INPUT!/health
    set /p "CONFIRM=        仍然添加? (y/n): "
    if /i not "!CONFIRM!"=="y" goto input_loop
)

set /a SLAVE_COUNT+=1
set "SLAVE_YAML=!SLAVE_YAML!    - name: 'slave-!SLAVE_COUNT!'\n      url: 'http://!INPUT!'\n      weight: 1\n"
echo        [OK] 已记录 http://!INPUT!
echo.
goto input_loop

:input_done
if !SLAVE_COUNT!==0 (
    echo.
    echo [提示] 没配置任何 Slave，Master 启动后无法分发翻译
    set /p "CONFIRM=继续? (y/n): "
    if /i not "!CONFIRM!"=="y" exit /b 0
)

REM ============ 步骤 5: 写入 config.yaml + 最终验证 ============
echo.
echo [5/5] 写入 master\config.yaml ...

(
echo master:
echo   host: '0.0.0.0'
echo   port: !MASTER_PORT!
echo   slaves:
) > master\config.yaml
if !SLAVE_COUNT! GTR 0 (
    powershell -NoProfile -Command "[IO.File]::AppendAllText('master\config.yaml', \"`n!SLAVE_YAML!\", [Text.Encoding]::UTF8)"
)

echo        [OK] 配置文件已写入

REM ============ 报告 ============
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| find "IPv4" ^| find "192.168"') do set LOCAL_IP=%%i
set LOCAL_IP=!LOCAL_IP: =!
if "!LOCAL_IP!"=="" set LOCAL_IP=127.0.0.1

echo.
echo ============================================
echo   Master 已就绪
echo ============================================
echo   本机 IP:     !LOCAL_IP!
echo   端口:        !MASTER_PORT!
echo   节点数:      !SLAVE_COUNT!
echo   访问:        http://!LOCAL_IP!:!MASTER_PORT!
echo   文档:        http://!LOCAL_IP!:!MASTER_PORT!/docs
echo.
echo   其他机器调用:
echo     set LOCALTRANS_MASTER_URL=http://!LOCAL_IP!:!MASTER_PORT!
echo     pip install localtrans
echo     python -c "from localtrans import translate; print(translate('Hello', 'zh'))"
echo.
echo   Master 服务在后台运行中
echo   停止: taskkill /F /FI "WINDOWTITLE eq LocalTrans-Master*"
echo ============================================
echo.
pause
