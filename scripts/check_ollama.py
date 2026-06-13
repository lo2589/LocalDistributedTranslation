"""
Ollama 检查脚本 - 由 install_slave.bat 调用
检查 Ollama 是否在跑、模型是否已下载

Exit codes:
    0 - Ollama 正在运行，且指定模型已下载
    1 - Ollama 命令不存在（未安装）
    2 - Ollama 未启动（serve 进程不在）
    3 - Ollama 在跑但指定模型未下载
"""

import subprocess
import sys
import os


def main():
    # 从命令行或环境变量接受模型名
    model_name = None
    if len(sys.argv) > 1:
        model_name = sys.argv[1]
    if not model_name:
        model_name = os.environ.get("OLLAMA_MODEL", "tencent/hy-mt1.5-1.8b-q4")

    # 1) 检查 ollama 命令是否存在
    try:
        subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("OLLAMA_NOT_FOUND")
        sys.exit(1)

    # 2) 检查 ollama serve 是否在跑
    try:
        import httpx
        client = httpx.Client(timeout=5, trust_env=False)
        r = client.get("http://127.0.0.1:11434/api/tags")
        if r.status_code != 200:
            print("OLLAMA_NOT_RUNNING (bad status)")
            sys.exit(2)
    except Exception:
        print("OLLAMA_NOT_RUNNING")
        sys.exit(2)

    # 3) 检查模型是否已下载
    data = r.json()
    models = data.get("models", [])
    model_names = [m.get("name", "") for m in models]
    found = False
    for m in model_names:
        if m.startswith(model_name):
            found = True
            print(f"OLLAMA_OK model={m}")
            sys.exit(0)
    if found:
        sys.exit(0)

    # 模型不在列表
    print(f"OLLAMA_NO_MODEL have={model_names} need={model_name}")
    sys.exit(3)


if __name__ == "__main__":
    main()
