# Distra — Distributed Translation Framework

**What it solves**: Local batch translation, data never leaves your LAN, leverage multiple machines in parallel.

## The Problem

- **Privacy**: Contracts, medical records, technical docs — you don't want them on the cloud
- **Too slow**: Batch translating hundreds of pages on one machine takes hours
- **Old hardware**: A single weak machine can't handle a decent LLM fast enough

## The Solution

```
Multiple machines translate in parallel. Master routes. Data stays local.
```

- Machine A runs **Master**: receives requests → round-robins to idle workers
- Machines B/C/D run **Slave**: each loads a model, translates in parallel
- All communication is LAN-only REST. No external network needed for translation.

## Architecture

```
Client ──POST /translate──> Master :8000 ──round-robin──> Slave :8001
                                                          Slave :8002
                                                          Slave :8003
```

**Two inference backends**:
- **Ollama backend** (verified): calls local Ollama HTTP API, no torch needed
- **transformers backend** (planned): direct torch + transformers, requires 64-bit Python

## Hardware Requirements

| Role | Requirements | Notes |
|------|-------------|-------|
| Master | Any Python-capable machine | 2GB+ RAM, mainly routing |
| Slave | Machine that can run Ollama | 8GB+ RAM recommended, Hunyuan 1.8B Q4 needs ~2GB |

**Recommended setup**: Machines B/C/D each run Ollama + Hunyuan 1.8B Q4. Master runs Python + FastAPI.

## Installation

### Master (the router machine)

**1. Install Python dependencies**

```bash
# Option A: Auto-install (recommended)
# Right-click install_env.bat → Run as administrator
install_env.bat

# Option B: Manual (if you already have 64-bit Python)
pip install fastapi uvicorn httpx pydantic pyyaml
```

**2. Start**

```bash
start_master.bat
# Or manually
python -m uvicorn master.master:app --host 0.0.0.0 --port 8000
```

### Slave (each worker machine)

**1. Install Ollama**

Download: https://ollama.com/download

Or via command line:
```powershell
# Windows PowerShell (admin)
irm https://ollama.com/install.ps1 | iex
```

**2. Download translation model**

```bash
# Hunyuan 1.8B Q4 quantized (1.1GB, recommended)
ollama pull tencent/hy-mt1.5-1.8b-q4

# Fallback: Qwen2.5 7B (4.7GB, better quality but slower)
ollama pull qwen2.5:7b

# Fallback: Import local GGUF (if you already have the file)
# Put GGUF in the project dir, then:
ollama create hunyuan-mt:1.8b-q4 -f Modelfile.hunyuan
```

**3. Start Slave**

```bash
start_slave.bat
# Or manually
python -m uvicorn slave.slave:app --host 0.0.0.0 --port 8001
```

## Usage

### Method 1: Python Client

```python
from client import TranslatorClient

client = TranslatorClient("http://<Master_IP>:8000")

# Simple translation
result = client.translate("Hello world", target_lang="zh")
print(result.translated_text)  # 你好世界

# With glossary (force specific translations)
result = client.translate(
    "We use PyTorch for deep learning research.",
    target_lang="zh",
    glossary={"PyTorch": "PyTorch框架", "deep learning": "深度学习"}
)
print(result.translated_text)  # 我们使用PyTorch框架进行深度学习研究。

# Multi-language (French → Chinese)
result = client.translate("Bonjour monde", target_lang="zh", source_lang="fr")

# Batch translation
texts = ["Hello", "Good morning", "Thank you"]
for text in texts:
    r = client.translate(text, target_lang="zh")
    print(r.translated_text)
```

### Method 2: curl

```bash
# Simple
curl -X POST http://localhost:8000/translate ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Hello world\",\"target_lang\":\"zh\"}"

# With glossary
curl -X POST http://localhost:8000/translate ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"PyTorch is great\",\"target_lang\":\"zh\",\"glossary\":{\"PyTorch\":\"PyTorch框架\"}}"
```

### Method 3: Browser

```
http://localhost:8000/docs
```
FastAPI auto-generates an interactive docs page. Test it right in the browser.

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/translate` | POST | Translate |
| `/health` | GET | All node health status |
| `/slaves` | GET | Slave node list |
| `/models` | GET | All models from all slaves |

## Troubleshooting

### Q: "no space on device" when installing

**A**: Disk is full. Free up space first:

```powershell
# Check D: space
Get-PSDrive D

# Common cleanup targets:
# 1. Anaconda pkgs cache (can free 10GB+)
Remove-Item "$env:USERPROFILE\.conda\pkgs" -Recurse -Force -ErrorAction SilentlyContinue

# 2. Temp files
Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue
```

### Q: `ollama pull` is too slow

**A**: Download GGUF via mirror, then import to Ollama:

```bash
# 1. Download GGUF via HF mirror (~2-4MB/s)
curl -L -o HY-MT1.5-1.8B-Q4_K_M.gguf ^
  "https://hf-mirror.com/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M/resolve/main/Hy-MT1.5-1.8B-Q4_K_M.gguf"

# 2. Import to Ollama
ollama create hunyuan-mt:1.8b-q4 -f Modelfile.hunyuan
```

### Q: Can't install torch on 32-bit Python

**A**: torch dropped 32-bit support since v1.13. **You must use 64-bit Python**.

```powershell
# Check Python bitness
python -c "import struct; print(struct.calcsize('P') * 8)"
# If it prints 32, install 64-bit Python:
# https://www.python.org/downloads/windows/
```

### Q: "OutOfMemory" when loading model

**A**: Model is too large for your RAM. Try a quantized version:

| Quantization | Size | RAM needed |
|-------------|------|------------|
| Q4_K_M (recommended) | 1.1GB | ~2GB |
| Q2_K | 0.6GB | ~1GB |
| FP16 | 3.6GB | ~4GB |

### Q: Empty or garbled translation output

**A**: Check Ollama status:

```bash
ollama list           # Is the model in the list?
ollama ps             # Is the model loaded in memory?
```

### Q: Master can't reach Slave

**A**: Make sure they're on the same LAN and firewall allows the ports:

```powershell
# Allow ports 8000-8002
New-NetFirewallRule -DisplayName "DistraPorts" -Direction Inbound -LocalPort 8000,8001,8002 -Protocol TCP -Action Allow
```

## Performance Reference

> Test setup: Intel i5-10210U + Intel UHD Graphics iGPU + Hunyuan 1.8B Q4

| Scenario | Time |
|----------|------|
| Single sentence (EN→ZH) | ~0.5s |
| 5 sentences parallel (100 words each) | ~20s |
| 5 sentences serial (100 words each) | ~25s |

## Project Structure

```
分布式翻译/
├── master/              # Master (routing + health check + model management)
├── slave/               # Slave (inference + model loading/unloading)
├── common/              # Shared protocol (schemas.py)
├── client.py            # Python client library
├── start_master.bat     # Start master
├── start_slave.bat      # Start slave
├── install_env.bat      # Install dependencies
└── Modelfile.hunyuan    # GGUF → Ollama import example
```
