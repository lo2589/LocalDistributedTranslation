@echo off
REM Local Distributed Translation - Slave 安装脚本
REM 功能：6 步自检 + 后台挂载 + 显示本机 IP

setlocal enabledelayedexpansion

set SLAVE_PORT=8001
set TEST_PARAGRAPHS=5
set TEST_TIMEOUT=60

echo ============================================
echo   Local Distributed Translation - Slave 安装
echo ============================================
echo.

REM ============ 步骤 1: Python 64-bit 检测 ============
echo [1/6] 检测 Python 64-bit...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python
    echo        下载: https://www.python.org/downloads/windows/
    echo        安装时勾选 "Add Python to PATH"
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python -c "import struct; print(struct.calcsize('P')*8)"') do set PYTHON_BITS=%%i
if not "!PYTHON_BITS!"=="64" (
    echo [错误] 当前 Python 是 !PYTHON_BITS! 位，必须用 64 位
    echo        下载 64-bit: https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
echo        [OK] Python 64-bit

REM ============ 步骤 2: 装依赖 ============
echo.
echo [2/6] 安装依赖...
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

REM ============ 步骤 3: Ollama 检测 ============
echo.
echo [3/6] 检测 Ollama...
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Ollama
    echo        下载: https://ollama.com/download
    pause
    exit /b 1
)

REM 检查 Ollama 服务在跑
curl -s --max-time 3 http://127.0.0.1:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo        启动 Ollama 服务...
    start "OllamaService" /min ollama serve
    timeout /t 5 /nobreak >nul
    curl -s --max-time 3 http://127.0.0.1:11434/api/tags >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] Ollama 启动失败，请手动运行: ollama serve
        pause
        exit /b 1
    )
)
echo        [OK] Ollama 运行中

REM ============ 步骤 4: 模型下载 ============
echo.
echo [4/6] 检查/下载模型 hunyuan-mt:1.8b-q4 (1.1GB)...
ollama list | find "hunyuan-mt:1.8b-q4" >nul 2>&1
if %errorlevel%==0 (
    echo        [跳过] 模型已存在
) else (
    echo        正在下载（可能需要 5-30 分钟）...
    ollama pull tencent/hy-mt1.5-1.8b-q4
    if %errorlevel% neq 0 (
        echo [错误] 模型下载失败
        echo        可手动重试: ollama pull tencent/hy-mt1.5-1.8b-q4
        pause
        exit /b 1
    )
)
echo        [OK] 模型已就绪

REM ============ 步骤 5: 启动 Slave 服务（后台）============
echo.
echo [5/6] 启动 Slave 服务（端口 !SLAVE_PORT!）...
REM 先 kill 已有的
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":!SLAVE_PORT! " 2^>nul') do taskkill /F /PID %%a >nul 2>&1

cd /d "%~dp0"
start "LocalTrans-Slave" /min cmd /c ".venv\Scripts\python.exe -m uvicorn slave.slave:app --host 0.0.0.0 --port !SLAVE_PORT! > slave.log 2>&1"

REM 等待服务起来
echo        等待服务启动...
set /a WAIT_COUNT=0
:wait_slave
timeout /t 2 /nobreak >nul
curl -s --max-time 2 http://127.0.0.1:!SLAVE_PORT!/health >nul 2>&1
if %errorlevel%==0 goto slave_ready
set /a WAIT_COUNT+=1
if !WAIT_COUNT! GEQ 15 (
    echo [错误] Slave 启动超时（30秒）
    echo        查看日志: slave.log
    pause
    exit /b 1
)
goto wait_slave

:slave_ready
echo        [OK] Slave 服务运行中

REM ============ 步骤 6: 并行翻译自测 ============
echo.
echo [6/6] 并行翻译自测（!TEST_PARAGRAPHS! 段，验证机器能干活）...
.venv\Scripts\python.exe -c "
import httpx, concurrent.futures, time, sys
URL = 'http://127.0.0.1:!SLAVE_PORT!/ollama/translate'
texts = [
    'Hello world',
    'Good morning, how are you?',
    'Artificial intelligence is changing the world.',
    'Machine learning algorithms require large datasets.',
    'The quick brown fox jumps over the lazy dog.',
]
def trans(text):
    try:
        r = httpx.post(URL, json={'text': text, 'target_lang': 'zh'}, timeout=!TEST_TIMEOUT!)
        r.raise_for_status()
        return text, r.json().get('translated_text', ''), None
    except Exception as e:
        return text, '', str(e)

start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=!TEST_PARAGRAPHS!) as ex:
    results = list(ex.map(trans, texts))
elapsed = time.time() - start
passed = sum(1 for _, c, e in results if c and not e)
print(f'  通过: {passed}/!TEST_PARAGRAPHS! | 耗时: {elapsed:.1f}s')
for t, c, e in results:
    if e:
        print(f'  [FAIL] {t[:30]}... -> {e[:50]}')
    else:
        print(f'  [OK]   {t[:30]}... -> {c[:40]}')
sys.exit(0 if passed >= !TEST_PARAGRAPHS! - 1 else 1)
"
if %errorlevel% neq 0 (
    echo [错误] 自测失败（通过数不足）
    echo        查看日志: slave.log
    pause
    exit /b 1
)

REM ============ 检测本机 IP ============
echo.
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| find "IPv4" ^| find "192.168"') do set LOCAL_IP=%%i
set LOCAL_IP=!LOCAL_IP: =!
if "!LOCAL_IP!"=="" set LOCAL_IP=127.0.0.1

REM ============ 报告 ============
echo ============================================
echo   Slave 已就绪
echo ============================================
echo   本机 IP:     !LOCAL_IP!
echo   端口:        !SLAVE_PORT!
echo   模型:        hunyuan-mt:1.8b-q4
echo   地址:        http://!LOCAL_IP!:!SLAVE_PORT!
echo.
echo   把下面这行复制到 Master 的 master\config.yaml:
echo.
echo     - name: "slave-!LOCAL_IP!"
echo       url: "http://!LOCAL_IP!:!SLAVE_PORT!"
echo       weight: 1
echo.
echo   Slave 服务在后台运行中（最小化窗口）
echo   停止: taskkill /F /FI "WINDOWTITLE eq LocalTrans-Slave*"
echo ============================================
echo.
pause
