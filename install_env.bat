@echo off
REM 分布式翻译器 - 一键安装脚本 (Windows)
REM 自动创建虚拟环境并安装所有依赖

setlocal enabledelayedexpansion

echo ============================================
echo   分布式翻译器 - 一键安装
echo ============================================
echo.

REM 检测 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+ 64-bit
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检测 Python 位数
for /f "tokens=2" %%i in ('python -c "import struct; print(struct.calcsize('P')*8)"') do set BITS=%%i
echo [信息] 检测到 Python !BITS! 位

if "!BITS!"=="32" (
    echo [警告] 当前是 32 位 Python，PyTorch 官方只提供 64 位版本
    echo [信息] 将尝试使用清华源安装 64 位 Python
    echo.
    set PYTHON_EXE=python
    goto :create_venv
)

set PYTHON_EXE=python

:create_venv
echo.
echo [步骤 1/4] 创建虚拟环境 .venv ...
if exist .venv (
    echo [信息] .venv 已存在，跳过创建
    goto :install_deps
)
python -m venv .venv
if %errorlevel% neq 0 (
    echo [错误] 虚拟环境创建失败
    pause
    exit /b 1
)

:install_deps
echo.
echo [步骤 2/4] 配置清华源（国内加速）...
".venv\Scripts\python.exe" -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
".venv\Scripts\python.exe" -m pip config set install.trusted-host pypi.tuna.tsinghua.edu.cn

echo.
echo [步骤 3/4] 升级 pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel

echo.
echo [步骤 4/4] 安装依赖（这可能需要几分钟下载 PyTorch ~200MB）...
".venv\Scripts\python.exe" -m pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo [错误] 依赖安装失败，请检查网络或手动安装
    pause
    exit /b 1
)

echo.
echo ============================================
echo   安装完成！
echo ============================================
echo.
echo 使用方式:
echo   1. 启动主机:  start_master.bat
echo   2. 启动从机:  start_slave.bat
echo   3. Python 调用: 见 README.md 客户端示例
echo.
echo 模型无需预装，启动从机后通过 API 下载:
echo   curl -X POST "http://localhost:8000/models/download?model_id=tencent/hy-mt2-1.8b"
echo.
pause
