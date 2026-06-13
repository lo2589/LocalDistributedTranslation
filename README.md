# Distra — 分布式翻译框架

**解决什么问题**：本地批量翻译，数据不出局域网，支持用多台旧电脑并行加速。
（[English version](README_en.md)）

## 痛点

- **隐私**：合同、病例、技术文档不想上传云端
- **速度慢**：单台机器跑批量翻译要几小时
- **机器性能差**：旧电脑带不动大模型，单机跑太慢

## 解决方案

```
多台旧电脑并行翻译，Master 统一调度，数据全在本地
```

- 机器 A 跑 Master：接收请求 → 轮询分发到空闲机器
- 机器 B/C/D 跑 Slave：各自加载模型，并行翻译
- 局域网内 REST 调用，不走外网

## 架构

```
Client ──POST /translate──> Master :8000 ──轮询负载均衡──> Slave :8001
                                                         Slave :8002
                                                         Slave :8003
```

## 硬件要求

| 角色 | 要求 | 说明 |
|------|------|------|
| Master | 任意能跑 Python 的机器 | 内存 2GB+，主要做路由 |
| Slave | 能跑 Ollama 的机器 | 推荐 8GB+ 内存，混元 1.8B Q4 需 ~2GB |

**推荐配置**：机器 B/C/D 各装 Ollama + 混元 1.8B Q4，Master 装 Python + FastAPI。

## 安装

### Master（主机）

**1. 安装 Python 依赖**

```bash
# 方式一：自动安装（推荐）
# 右键 install_env.bat → 以管理员身份运行
install_env.bat

# 方式二：手动安装（已有 Python 64-bit 时）
pip install fastapi uvicorn httpx pydantic pyyaml
```

**2. 启动**

```bash
start_master.bat
# 或手动
python -m uvicorn master.master:app --host 0.0.0.0 --port 8000
```

### Slave（从机，每台机器都要装）

**1. 安装 Ollama**

下载地址：https://ollama.com/download

或命令行：
```powershell
# Windows PowerShell
irm https://ollama.com/install.ps1 | iex
```

**2. 下载翻译模型**

```bash
# 混元 1.8B Q4 量化（1.1GB，推荐）
ollama pull tencent/hy-mt1.5-1.8b-q4

# 备选：通义千问 7B（4.7GB，质量好但慢）
ollama pull qwen2.5:7b

# 备选：本地 GGUF 导入（已有 GGUF 文件时）
# 先把 GGUF 文件放到本目录，然后：
ollama create hunyuan-mt:1.8b-q4 -f Modelfile.hunyuan
```

**3. 启动 Slave**

```bash
start_slave.bat
# 或手动
python -m uvicorn slave.slave:app --host 0.0.0.0 --port 8001
```

## 使用

### 方式一：Python 客户端

```python
from client import TranslatorClient

client = TranslatorClient("http://<Master_IP>:8000")

# 简单翻译
result = client.translate("Hello world", target_lang="zh")
print(result.translated_text)  # 你好世界

# 带术语表（强制特定翻译）
result = client.translate(
    "We use PyTorch for deep learning research.",
    target_lang="zh",
    glossary={"PyTorch": "PyTorch框架", "deep learning": "深度学习"}
)
print(result.translated_text)  # 我们使用PyTorch框架进行深度学习研究。

# 多语言（法→中）
result = client.translate("Bonjour monde", target_lang="zh", source_lang="fr")

# 批量翻译
texts = ["Hello", "Good morning", "Thank you"]
for text in texts:
    r = client.translate(text, target_lang="zh")
    print(r.translated_text)
```

### 方式二：curl

```bash
# 简单翻译
curl -X POST http://localhost:8000/translate ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Hello world\",\"target_lang\":\"zh\"}"

# 带术语表
curl -X POST http://localhost:8000/translate ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"PyTorch is great\",\"target_lang\":\"zh\",\"glossary\":{\"PyTorch\":\"PyTorch框架\"}}"
```

### 方式三：浏览器直接访问

```
http://localhost:8000/docs
```
FastAPI 自动生成文档界面，可直接在线测试。

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/translate` | POST | 翻译 |
| `/health` | GET | 所有节点健康状态 |
| `/slaves` | GET | 从机列表 |
| `/models` | GET | 所有从机的模型 |

## 常见问题

### Q: 安装依赖时报错 "no space on device"

**A**: 磁盘空间不足。清理磁盘后再试：
```powershell
# 查看 D 盘空间
Get-PSDrive D

# 常见清理位置
# 1. Anaconda pkgs 缓存（可删 10GB+）
Remove-Item "$env:USERPROFILE\.conda\pkgs" -Recurse -Force -ErrorAction SilentlyContinue

# 2. 删临时文件
Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue
```

### Q: `ollama pull` 下载太慢

**A**: 用 HuggingFace 镜像下载 GGUF，再导入 Ollama：

```bash
# 1. 下载 GGUF（走镜像，2-4MB/s）
curl -L -o HY-MT1.5-1.8B-Q4_K_M.gguf ^
  "https://hf-mirror.com/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M/resolve/main/Hy-MT1.5-1.8B-Q4_K_M.gguf"

# 2. 导入 Ollama
ollama create hunyuan-mt:1.8b-q4 -f Modelfile.hunyuan
```

### Q: 32-bit Python 装不上 torch

**A**: torch 从 1.13 起不再支持 32-bit。**必须用 64-bit Python**。

```powershell
# 检查 Python 位数
python -c "import struct; print(struct.calcsize('P') * 8)"

# 如果显示 32，安装 64-bit Python：
# https://www.python.org/downloads/windows/
```

### Q: 模型加载报错 "OutOfMemory"

**A**: 模型太大，内存不够。试试量化版本：

| 量化 | 大小 | 内存需求 |
|------|------|---------|
| Q4_K_M（推荐） | 1.1GB | ~2GB |
| Q2_K | 0.6GB | ~1GB |
| FP16 | 3.6GB | ~4GB |

### Q: 翻译结果为空或乱码

**A**: 检查 Ollama 是否在跑、模型是否加载：
```bash
ollama list           # 看模型是否在列表
ollama ps             # 看模型是否在内存
```

### Q: Master 连不上 Slave

**A**: 确认在同一局域网，防火墙放行端口：
```powershell
# 放行 8000-8002
New-NetFirewallRule -DisplayName "DistributedTranslator" -Direction Inbound -LocalPort 8000,8001,8002 -Protocol TCP -Action Allow
```

## 性能参考

> 测试：Intel i5-10210U + Intel UHD Graphics 集显 + 混元 1.8B Q4

| 场景 | 耗时 |
|------|------|
| 单句英→中 | ~0.5s |
| 5句并行（各100词） | ~20s |
| 5句串行（各100词） | ~25s |

## 项目结构

```
分布式翻译/
├── master/              # 主机（路由 + 健康检查）
├── slave/               # 从机（推理 + 模型管理）
├── common/              # 共享协议（schemas.py）
├── client.py            # Python 客户端
├── start_master.bat     # 启动主机
├── start_slave.bat      # 启动从机
├── install_env.bat      # 安装依赖
├── Modelfile.hunyuan    # GGUF 导入示例
└── README_en.md         # English version
```
