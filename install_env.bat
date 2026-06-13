@echo off
REM Distra - 分布式翻译框架 一键安装脚本
REM 功能：检测硬件 → 评估容量 → 生成配置 → 安装依赖

setlocal enabledelayedexpansion

echo ============================================
echo   Distra  一键安装
echo ============================================
echo.

REM ============ 硬件检测 ============
echo [检测 1/5] 操作系统...
ver | find "10" >nul && set OS=Windows10
ver | find "11" >nul && set OS=Windows11
ver | find "6.1" >nul && set OS=Windows7
ver | find "6.2" >nul && set OS=Windows8
ver | find "6.3" >nul && set OS=Windows8.1
echo        %OS%

echo [检测 2/5] CPU 核心数...
wmic CPU Get NumberOfCores /value 2>nul | find "=" >nul
if %errorlevel%==0 (
    for /f "tokens=2 delims==" %%i in ('wmic CPU Get NumberOfCores /value 2^>nul ^| find "="') do set CPU_CORES=%%i
) else (
    for /f %%i in ('wmic CPU Get NumberOfLogicalProcessors /value 2^>nul ^| find "="') do set CPU_CORES=%%i
)
echo        !CPU_CORES! 核心

echo [检测 3/5] 内存（RAM）...
for /f "tokens=2 delims==" %%i in ('wmic OS Get TotalVisibleMemorySize /value 2^>nul ^| find "="') do (
    set /a RAM_KB=%%i
    set /a RAM_GB=!RAM_KB! / 1024 / 1024
)
echo        !RAM_GB! GB

echo [检测 4/5] 显卡显存（GPU VRAM）...
powershell -NoProfile -Command "try { $dev = Get-CimInstance Win32_VideoController; $vram = [math]::Round($dev.AdapterRAM/1GB, 1); if ($vram -lt 1) { $vram = [math]::Round($dev.AdapterRAM/1MB, 0) }; Write-Host $vram } catch { Write-Host 0 }" > %TEMP%\vram.txt
set /p GPU_VRAM_GB=<%TEMP%\vram.txt
del %TEMP%\vram.txt >nul 2>&1
if "!GPU_VRAM_GB!"=="" set GPU_VRAM_GB=0
if !GPU_VRAM_GB! LSS 1 (
    echo        集成显卡（约 !GPU_VRAM_GB! GB VRAM，共享系统内存）
    set GPU_TYPE=integrated
) else (
    echo        独立显卡 !GPU_VRAM_GB! GB VRAM
    set GPU_TYPE=dedicated
)

echo [检测 5/5] 磁盘空间...
for /f "tokens=2 delims==" %%i in ('wmic LogicalDisk Where "DeviceID='C:'" Get FreeSpace /value 2^>nul ^| find "="') do set /a DISK_GB=%%i/1024/1024/1024
echo        C: 盘剩余 !DISK_GB! GB

REM ============ Python 检测 ============
echo.
echo [Python 检测]...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+ 64-bit
    echo 下载地址: https://www.python.org/downloads/
    echo.
    set INSTALL_ERROR=1
    goto :print_report
)

for /f "tokens=2" %%i in ('python -c "import struct; print(struct.calcsize('P')*8)"') do set PYTHON_BITS=%%i
echo        Python !PYTHON_BITS! 位

if "!PYTHON_BITS!"=="32" (
    echo [错误] 32-bit Python 不支持 PyTorch，必须用 64-bit
    echo 下载地址: https://www.python.org/downloads/windows/
    echo.
    set INSTALL_ERROR=1
    goto :print_report
)

REM ============ 模型容量评估 ============
echo.
echo [模型容量评估]...

REM RAM 评估：混元 1.8B Q4 每实例约 1.4GB（含 tokenizer + KV cache + 安全余量）
REM 混元 1.8B FP16 每实例约 4GB
set RAM_MODEL_GB_Q4=1400
set RAM_MODEL_GB_FP16=4000
set /a MAX_Q4_BY_RAM=!RAM_GB! * 1024 / !RAM_MODEL_GB_Q4!
set /a MAX_FP16_BY_RAM=!RAM_GB! * 1024 / !RAM_MODEL_GB_FP16!

REM VRAM 评估：混元 1.8B Q4 推理需约 600MB VRAM
set VRAM_MODEL_GB_Q4=600
if !GPU_VRAM_GB! LSS 1 (
    set /a MAX_Q4_BY_VRAM=0
) else (
    set /a MAX_Q4_BY_VRAM=!GPU_VRAM_GB! * 1024 / !VRAM_MODEL_GB_Q4!
)

set MAX_INSTANCES_Q4=!MAX_Q4_BY_RAM!
if !MAX_Q4_BY_VRAM! LSS !MAX_INSTANCES_Q4! set MAX_INSTANCES_Q4=!MAX_Q4_BY_VRAM!
if !MAX_INSTANCES_Q4! LSS 1 set MAX_INSTANCES_Q4=1
if !MAX_INSTANCES_Q4! GTR 8 set MAX_INSTANCES_Q4=8

REM ============ 生成配置 ============
echo.
echo [生成配置]...

REM 检测本机 IP（取局域网 IP）
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| find "IPv4" ^| find "192.168"') do set LOCAL_IP=%%i
set LOCAL_IP=!LOCAL_IP: =!
if "!LOCAL_IP!"=="" set LOCAL_IP=127.0.0.1

echo        本机 IP: !LOCAL_IP!

REM 生成 master/config.yaml
powershell -NoProfile -Command "
$cfg = @'
master:
  host: '0.0.0.0'
  port: 8000
  slaves:
    - name: 'slave-1'
      url: 'http://!LOCAL_IP!:8001'
      weight: 1
    - name: 'slave-2'
      url: 'http://!LOCAL_IP!:8002'
      weight: 1
    - name: 'slave-3'
      url: 'http://!LOCAL_IP!:8003'
      weight: 1
  health_check:
    interval: 30
    timeout: 5
  recommended_models:
    - id: 'hunyuan-mt:1.8b-q4'
      name: '混元翻译 1.8B Q4'
      params: '1.8B'
      memory: '1.1GB'
      description: '腾讯混元翻译模型，Q4 量化，1.1GB，33语言，推荐'
    - id: 'qwen2.5:7b'
      name: '通义千问 2.5 7B'
      params: '7B'
      memory: '4.7GB'
      description: '通义千问通用模型，需 prompt 翻译，质量好但慢'
'@
[IO.File]::WriteAllText('master\config.yaml', `$cfg.Trim(), [Text.Encoding]::UTF8)
Write-Host '  master\config.yaml generated'
"

REM 生成 slave/config.yaml（根据 RAM 决定量化参数）
set Q4_RECOMMEND=false
if !MAX_INSTANCES_Q4! GEQ 4 set Q4_RECOMMEND=true
if !RAM_GB! GEQ 16 set Q4_RECOMMEND=true

powershell -NoProfile -Command "
$q4 = '!Q4_RECOMMEND!'
$slaveCfg = @'
slave:
  host: '0.0.0.0'
  port: 8001
  model_cache_dir: '~/.cache/huggingface/hub'
  ollama:
    base_url: 'http://localhost:11434'
    default_model: 'hunyuan-mt:1.8b-q4'
  model:
    path: 'tencent/hy-mt2-1.8b'
    model_type: 'translation'
    torch_dtype: 'float16'
    device_map: 'auto'
'@
if ('true' -eq `$q4) {
    `$slaveCfg = `$slaveCfg -replace 'load_in_4bit: false', 'load_in_4bit: true'
}
[IO.File]::WriteAllText('slave\config.yaml', `$slaveCfg.Trim(), [Text.Encoding]::UTF8)
Write-Host '  slave\config.yaml generated'
"

REM ============ 打印报告 ============
:print_report
echo.
echo ============================================
echo   硬件报告
echo ============================================
echo   CPU:        !CPU_CORES! 核心
echo   内存:       !RAM_GB! GB
echo   显卡:       !GPU_VRAM_GB! GB VRAM (!GPU_TYPE!)
echo   磁盘:       !DISK_GB! GB 可用
echo   Python:     !PYTHON_BITS! 位
echo   本机 IP:    !LOCAL_IP!
echo.
echo ============================================
echo   模型容量评估（混元 1.8B Q4）
echo ============================================
echo   按 RAM 最大实例数: !MAX_Q4_BY_RAM!
if !GPU_VRAM_GB! GEQ 1 echo   按 VRAM 最大实例数: !MAX_Q4_BY_VRAM!
echo   推荐并发实例数:    !MAX_INSTANCES_Q4!
echo.

if !DISK_GB! LSS 5 (
    echo [警告] 磁盘空间不足 5GB，建议清理后再安装依赖
    echo   建议：删 D:\microedge-software\anaconda\pkgs 缓存
)

if defined INSTALL_ERROR (
    echo [跳过安装] 请先解决上述错误
    echo.
    pause
    exit /b 1
)

REM ============ 安装依赖 ============
echo.
echo ============================================
echo   安装 Python 依赖
echo ============================================

REM 创建 / 复用 .venv
echo.
echo [步骤 1/4] 创建虚拟环境 .venv ...
if exist .venv (
    echo [跳过] .venv 已存在
) else (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
    echo [完成] .venv 创建成功
)

echo.
echo [步骤 2/4] 配置清华源...
.venv\Scripts\python.exe -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe -m pip config set install.trusted-host pypi.tuna.tsinghua.edu.cn
echo [完成]

echo.
echo [步骤 3/4] 升级 pip ...
.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
echo [完成]

echo.
echo [步骤 4/4] 安装依赖包...
.venv\Scripts\python.exe -m pip install fastapi uvicorn httpx pydantic pyyaml
echo [完成]

echo.
echo ============================================
echo   安装完成！
echo ============================================
echo.
echo 下一步：
echo   1. 启动 Ollama（Slave 机器）：    ollama serve
echo   2. 下载模型：                    ollama pull tencent/hy-mt1.5-1.8b-q4
echo   3. 启动 Master：                 start_master.bat
echo   4. 启动 Slave（每台机器）：       start_slave.bat
echo.
echo 配置文件已根据本机硬件自动生成：
echo   master\config.yaml
echo   slave\config.yaml
echo.
pause
