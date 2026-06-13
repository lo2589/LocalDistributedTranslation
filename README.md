# 分布式翻译框架

局域网分布式翻译系统，数据不出本地，支持多台机器并行加载模型，主机统一调度。

## 架构

```
            ┌──────────────┐
            │   Client     │
            └──────┬───────┘
                   │ POST /translate
                   ▼
        ┌──────────────────┐
        │  Master :8000    │   主机：轮询分发 + 健康检查 + 模型管理
        │                  │
        │  (master.py)     │
        └────┬─────┬───────┘
             │     │
    ┌────────▼─┐ ┌─▼────────┐
    │ Slave   │ │ Slave    │   从机：模型推理 + 翻译
    │ :8001   │ │ :8002    │
    │         │ │          │
    │ Ollama  │ │ Ollama   │
    └─────────┘ └──────────┘
```

**支持两种推理后端**：
- **Ollama 后端**（已验证）：通过 Ollama HTTP API 调用本地模型，不依赖 torch，开箱即用
- **transformers 后端**（计划中）：直接用 torch + transformers，需 64-bit Python

## 推荐模型

| 模型 | 参数量 | 大小 | 说明 |
|------|--------|------|------|
| `hunyuan-mt:1.8b-q4` | 1.8B | 1.1GB | 混元翻译模型，33语言，速度快 |
| `tencent/HY-MT1.5-1.8B-Q4_K_M` | 1.8B | 1.1GB | 同上，GGUF 格式 |
| `qwen2.5:7b` | 7B | 4.7GB | 通用意模型，需 prompt 翻译 |

**优先使用混元 1.8B Q4**：速度快（~0.5s/句），质量好，体积小。

## 项目结构

```
.
├── common/
│   └── schemas.py          # 共享数据模型（TranslateRequest/Response 等）
├── master/
│   └── master.py          # 主机服务（路由 + 健康检查 + 模型管理）
├── slave/
│   └── slave.py           # 从机服务（Ollama/transformers 推理）
├── client.py              # Python 客户端示例
├── start_master.bat       # 启动主机脚本
├── start_slave.bat        # 启动从机脚本
├── install_env.bat        # 安装依赖脚本
├── requirements.txt
├── pyproject.toml
├── Modelfile.hunyuan      # 混元 GGUF → Ollama Modelfile 示例
└── README.md
```

## 快速开始

### 1. 安装依赖

**方式一：自动安装（推荐）**
```bash
install_env.bat
```

**方式二：手动安装**
```bash
pip install -r requirements.txt
# 需 64-bit Python 3.8+，torch + transformers
```

### 2. 启动 Ollama（从机需先装好）

```bash
# 安装混元翻译模型（Q4 量化，1.1GB）
ollama pull tencent/hy-mt1.5-1.8b-q4

# 或本地 GGUF 导入（已有 GGUF 文件时）
ollama create hunyuan-mt:1.8b-q4 -f Modelfile.hunyuan

# 确认模型可用
ollama list
```

### 3. 配置并启动

**编辑从机配置**（`slave/slave.py` 或命令行参数）：
- 设置 Ollama 地址（默认 `http://localhost:11434`）
- 设置默认模型（默认 `hunyuan-mt:1.8b-q4`）

**启动主机**：
```bash
start_master.bat
# 主机监听 :8000
```

**启动从机**（每台机器）：
```bash
start_slave.bat
# 从机监听 :8001，注册到主机
```

### 4. 调用翻译

**Python 客户端**：
```python
from client import TranslatorClient

client = TranslatorClient("http://localhost:8000")

# 简单翻译
result = client.translate("Hello world", target_lang="zh")
print(result.translated_text)  # 你好世界

# 带术语表
result = client.translate(
    "We use PyTorch for deep learning.",
    target_lang="zh",
    glossary={"PyTorch": "PyTorch框架", "deep learning": "深度学习"}
)
print(result.translated_text)  # 我们使用PyTorch框架进行深度学习。

# 多语言
result = client.translate("Bonjour monde", target_lang="zh", source_lang="fr")
```

**HTTP API（直接调用 Master）**：
```bash
curl -X POST http://localhost:8000/translate \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello world","target_lang":"zh"}'
```

## API 参考

### Master 端点（:8000）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/translate` | POST | 翻译入口 |
| `/health` | GET | 主+从机健康状态 |
| `/slaves` | GET | 所有从机列表 |
| `/models` | GET | 聚合查询所有从机模型 |
| `/models/recommendations` | GET | 推荐模型列表 |
| `/models/download` | POST | 触发从机下载模型 |
| `/models/load` | POST | 指定从机加载模型 |
| `/models/unload` | POST | 指定从机卸载模型 |

### Slave 端点（:8001 等）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/translate` | POST | transformers 后端翻译 |
| `/ollama/translate` | POST | Ollama 后端翻译 |
| `/ollama/translate/stream` | POST | Ollama 流式翻译 |
| `/health` | GET | 从机健康状态 |
| `/models` | GET | 本地从机模型列表 |
| `/models/download` | POST | 下载模型 |
| `/models/load` | POST | 加载模型 |
| `/models/unload` | POST | 卸载模型 |

### 请求/响应示例

**翻译请求**：
```json
{
    "text": "Artificial intelligence is changing the world",
    "source_lang": "en",
    "target_lang": "zh",
    "glossary": {"artificial intelligence": "人工智能"},
    "stream": false,
    "max_new_tokens": 256
}
```

**翻译响应**：
```json
{
    "translated_text": "人工智能正在改变世界",
    "model": "hunyuan-mt:1.8b-q4",
    "slave_name": "slave-1"
}
```

## 模型管理

### 下载混元 1.8B Q4（GGUF 格式，推荐）

```bash
# 通过 HuggingFace 镜像下载（约 1.1GB）
curl -L -o HY-MT1.5-1.8B-Q4_K_M.gguf \
  "https://hf-mirror.com/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M/resolve/main/Hy-MT1.5-1.8B-Q4_K_M.gguf"

# 导入 Ollama
ollama create hunyuan-mt:1.8b-q4 -f Modelfile.hunyuan
```

### llama.cpp 独立运行（可选）

不用 Ollama 时，可直接用 llama.cpp 服务器：
```bash
# 下载 llama.cpp b9263+（支持 hunyuan-dense 架构）
# 启动服务器
llama-server.exe -m HY-MT1.5-1.8B-Q4_K_M.gguf --port 8081 -ngl 0 -c 2048

# 调用
curl http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"hy-mt","messages":[{"role":"user","content":"Hello world"}],"max_tokens":64}'
```

## 性能基准

> 测试环境：Intel i5-10210U + Intel UHD Graphics集显

| 模型 | 方案 | 5段100词并行耗时 | 单句耗时 |
|------|------|-----------------|---------|
| 混元 1.8B Q4 | Ollama (Intel UHD Vulkan) | ~20s | ~0.5s |
| 混元 1.8B Q4 | llama.cpp CPU (4 slot) | ~33s | ~1.3s |

## 依赖

```
fastapi>=0.100.0
uvicorn[standard]>=0.23.0
pydantic>=2.0.0
PyYAML>=6.0
httpx>=0.24.0
# 以下为 transformers 后端（可选）：
torch>=2.0.0          # 需 64-bit Python
transformers>=4.37.0
accelerate>=0.20.0
huggingface-hub>=0.16.0
```

## 注意事项

- **32-bit Python 无法使用 torch**，transformers 后端需要 64-bit Python
- **模型文件不加入 git**，已配置 `.gitignore` 排除 `*.gguf`
- 首次加载模型较慢（约 2-3s），之后热推理很快
- 术语表注入到 prompt 头部，模型会**尽量遵循但不保证完全替换**
