# Local Distributed Translation

**Requires Ollama**: Slave nodes rely on Ollama for inference. Each translation machine needs Ollama installed with a translation model pulled.

**What it solves**: Local batch translation, data never leaves your LAN, leverage multiple machines in parallel.
（[中文版](README_zh.md)）

---

## The Problem

- **Privacy**: Contracts, medical records, technical docs — you don't want them on the cloud
- **Too slow**: Batch translating hundreds of pages on one machine takes hours
- **Old hardware**: A single weak machine can't handle a decent LLM fast enough

## The Solution

```
Multiple machines translate in parallel. Master routes. Data stays local.
```

- Machine A runs **Master**: receives requests → round-robins to idle workers
- Machines B/C/D run **Slave**: each uses Ollama to load a translation model, translates in parallel
- All communication is LAN-only REST. No external network needed for translation.

## Architecture

```
Client ──POST /translate──> Master :8000 ──round-robin──> Slave :8001 (Ollama)
                                                          Slave :8002 (Ollama)
                                                          Slave :8003 (Ollama)
```

---

## Ollama + Model Setup

Each Slave machine needs the following steps:

### Step 1: Install Ollama

Visit https://ollama.com/download to download the installer for your OS.

After installation, verify in your terminal:

```powershell
ollama --version
```

If Ollama is installed but not running, `install_slave.bat` will try to start `ollama serve` automatically.

### Step 2: Pull the Translation Model

This project uses `hunyuan-mt:1.8b-q4` by default (Tencent Hunyuan translation model, 1.8B params, Q4 quantized, ~1.1GB, good EN↔ZH quality).

**Option A: Direct `ollama pull` (recommended)**

```powershell
ollama pull hunyuan-mt:1.8b-q4
```

Verify:

```
ollama list
# You should see: hunyuan-mt:1.8b-q4
```

**Option B: Download GGUF from HuggingFace community, then import (if `ollama pull` doesn't work)**

1. Download the GGUF file from HuggingFace (use mirror if needed):
   - Direct: https://huggingface.co/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M
   - Mirror (China): https://hf-mirror.com/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M

```powershell
# Download GGUF (adjust URL if using mirror)
curl -L -o HY-MT1.5-1.8B-Q4_K_M.gguf ^
  "https://hf-mirror.com/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M/resolve/main/Hy-MT1.5-1.8B-Q4_K_M.gguf"
```

2. Place the GGUF file in the project root (same folder as `Modelfile.hunyuan`), then import:

```powershell
ollama create hunyuan-mt:1.8b-q4 -f Modelfile.hunyuan
```

**Option C: Use a different model**

You can use any model available on Ollama:

```powershell
ollama pull qwen2.5:1.5b-instruct-q4_K_M     # Qwen2.5 (general-purpose, also translates)
ollama pull llama3.2:3b-instruct-q4_K_M       # Llama 3.2 (strong English)
```

If you change the model, update `slave/config.yaml` line 13:

```yaml
ollama:
  model: "your-model-name"   # e.g. "qwen2.5:1.5b-instruct-q4_K_M"
```

### Step 3: Verify

```powershell
# Check model is listed
ollama list

# Quick test
ollama run hunyuan-mt:1.8b-q4 "Translate: Hello world -> Chinese"
```

---

## Installation

### Recommended flow: install Slaves first, then Master

```
Each translation machine: run install_slave.bat
   ↓
  6-step self-test passes → shows local IP
   ↓
Copy the IP to the Master machine
   ↓
Master machine: run install_master.bat
   ↓
  Enter Slave IPs line by line → Master verifies connections
   ↓
  Ready
```

### Slave (each translation machine)

Make sure Ollama + `hunyuan-mt:1.8b-q4` is ready (see above), then:

```bash
install_slave.bat
```

The script **automatically**:
1. Checks Python 64-bit
2. Installs pip dependencies (fastapi uvicorn httpx pydantic pyyaml)
3. Detects/starts Ollama + confirms `hunyuan-mt:1.8b-q4` model exists
4. Starts Slave service in background (port 8001, logs in `logs/slave.log`)
5. Runs 5-paragraph parallel translation self-test
6. ✅ On success, displays the local IP

### Master (router machine)

```bash
install_master.bat
```

The script **automatically**:
1. Checks Python 64-bit
2. Installs pip dependencies
3. Starts Master in background (port 8000, logs in `logs/master.log`)
4. Self-tests the `/health` endpoint
5. **Prompts for Slave IPs line by line** (e.g. `192.168.1.101:8001`, Enter to finish)
6. Writes to `master/config.yaml` and pings each Slave

### Client Usage

```bash
# Install on other machines that need to access Master
pip install localtrans
localtrans-save http://192.168.1.100:8000
```

```python
from localtrans import translate
print(translate("Hello world", target_lang="zh"))  # 你好世界
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

### Method 2: curl / PowerShell

```powershell
# Simple translation
curl -X POST http://localhost:8000/translate ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Hello world\",\"target_lang\":\"zh\"}"
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
| `/health` | GET | All node health status (includes Ollama model readiness) |
| `/slaves` | GET | Slave node list |
| `/models` | GET | All models from all slaves |

## FAQ

### Q: What if Ollama is not installed?

**A**: Slave depends on Ollama for inference — translation won't work without it. Install from https://ollama.com/download

### Q: `ollama pull hunyuan-mt:1.8b-q4` is too slow or fails

**A**: Download GGUF via HuggingFace mirror and import:

```powershell
curl -L -o HY-MT1.5-1.8B-Q4_K_M.gguf ^
  "https://hf-mirror.com/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M/resolve/main/Hy-MT1.5-1.8B-Q4_K_M.gguf"
ollama create hunyuan-mt:1.8b-q4 -f Modelfile.hunyuan
```

### Q: Slave reports "model not found"

**A**: Make sure the model name is consistent in these 3 places:

1. `ollama list` output
2. `slave/config.yaml` line 13 `ollama.model`
3. `install_slave.bat` line 19 `set OLLAMA_MODEL=`

Default model name: `hunyuan-mt:1.8b-q4`.

### Q: Master can't reach Slave

**A**: Make sure they're on the same LAN and firewall allows the ports:

```powershell
New-NetFirewallRule -DisplayName "DistraPorts" -Direction Inbound -LocalPort 8000,8001,8002 -Protocol TCP -Action Allow
```

### Q: "OutOfMemory" when loading model

**A**: Try a smaller quantization:

| Quantization | Size | RAM needed |
|-------------|------|------------|
| Q4_K_M (recommended) | 1.1GB | ~2GB |
| Q2_K | 0.6GB | ~1GB |
| FP16 | 3.6GB | ~4GB |

### Q: Empty or garbled translation output

**A**: Check Ollama status:

```powershell
ollama list   # Is the model in the list?
ollama ps     # Is the model loaded in memory?
```

### Q: "no space on device" when installing

**A**: Free up disk space:

```powershell
# Anaconda pkgs cache (can free 10GB+)
Remove-Item "$env:USERPROFILE\.conda\pkgs" -Recurse -Force -ErrorAction SilentlyContinue

# Temp files
Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue
```

## Performance

> Test: Intel i5-10210U + 8GB RAM + Ollama + `hunyuan-mt:1.8b-q4`

| Scenario | Time |
|----------|------|
| Single sentence EN→ZH | ~2s |
| 5 sentences parallel (100 words each) | ~20s |

Adding more Slave machines roughly scales throughput linearly.

## Project Structure

```
分布式翻译/
├── master/              # Master (routing + health check)
├── slave/               # Slave (calls Ollama for translation)
├── common/              # Shared protocol (schemas.py)
├── localtrans/          # Python client package (pip install localtrans)
├── scripts/             # Self-test helpers
├── install_slave.bat    # Slave 6-step self-test + start (requires Ollama)
├── install_master.bat   # Master config + start
├── Modelfile.hunyuan    # Ollama Hunyuan model import example
├── logs/                # Runtime logs (auto-created, git-ignored)
└── README_zh.md         # 中文版
```
