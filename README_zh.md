# Local Distributed Translation

**需要 Ollama**：Slave 依赖 Ollama 做推理，每台翻译机器需要安装 Ollama 并拉取混元翻译模型。

**解决什么问题**：本地批量翻译，数据不出局域网，支持用多台旧电脑并行加速。
（[English version](README.md)）

---

## 痛点

- **隐私**：合同、病例、技术文档不想上传云端
- **速度慢**：单台机器跑批量翻译要几小时
- **机器性能差**：旧电脑带不动大模型，单机跑太慢

## 解决方案

```
多台旧电脑并行翻译，Master 统一调度，数据全在本地
```

- 机器 A 跑 Master：接收请求 → 轮询分发到空闲机器
- 机器 B/C/D 跑 Slave：各自通过 Ollama 加载翻译模型，并行翻译
- 局域网内 REST 调用，不走外网

## 架构

```
Client ──POST /translate──> Master :8000 ──轮询负载均衡──> Slave :8001 (Ollama)
                                                         Slave :8002 (Ollama)
                                                         Slave :8003 (Ollama)
```

---

## Ollama + 混元模型安装

每台 Slave 机器需要完成以下步骤：

### 第 1 步：装 Ollama

访问 https://ollama.com/download 下载安装包。

安装后确认能运行：

```powershell
ollama --version
```

如果已经装了 Ollama 但没在跑，`install_slave.bat` 会尝试自动启动 `ollama serve`。

### 第 2 步：拉取混元翻译模型

本项目默认使用 `hunyuan-mt:1.8b-q4`（腾讯混元翻译模型 1.8B 参数 Q4 量化版，~1.1GB，中英互译质量不错）。

**方式 A：直接 `ollama pull`（推荐）**

```powershell
ollama pull hunyuan-mt:1.8b-q4
```

验证是否成功：

```
ollama list
# 应该看到：hunyuan-mt:1.8b-q4
```

**方式 B：从 HuggingFace 社区下载 GGUF 再导入（`ollama pull` 下不了时用）**

1. 从 HuggingFace 下载 GGUF 文件（国内用镜像）：
   - 直连：https://huggingface.co/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M
   - 镜像：https://hf-mirror.com/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M

```powershell
# 下载 GGUF（国内用镜像地址）
curl -L -o HY-MT1.5-1.8B-Q4_K_M.gguf ^
  "https://hf-mirror.com/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M/resolve/main/Hy-MT1.5-1.8B-Q4_K_M.gguf"
```

2. 把 GGUF 文件放到项目根目录（和 `Modelfile.hunyuan` 同级），然后导入：

```powershell
ollama create hunyuan-mt:1.8b-q4 -f Modelfile.hunyuan
```

**方式 C：换其他翻译模型**

也可以用任何 Ollama 上有的翻译/对话模型：

```powershell
ollama pull qwen2.5:1.5b-instruct-q4_K_M     # 阿里 Qwen2.5（通用，也能翻译）
ollama pull llama3.2:3b-instruct-q4_K_M       # Llama 3.2（通用，英文强）
```

换了模型记得改 `slave/config.yaml` 第 13 行：

```yaml
ollama:
  model: "你的模型名"   # 例如 "qwen2.5:1.5b-instruct-q4_K_M"
```

### 第 3 步：验证

```powershell
# 看模型是否在列表
ollama list

# 手动测一次翻译
ollama run hunyuan-mt:1.8b-q4 "Translate: Hello world -> Chinese"
```

---

## 安装

### 推荐流程：先装 Slave，再装 Master

```
每台翻译机器：运行 install_slave.bat
   ↓
  自检 6 步全过 → 显示本机 IP
   ↓
把 IP 抄到 Master 那台机器
   ↓
Master 机器：运行 install_master.bat
   ↓
  逐行输入 Slave IP → Master 验证连接
   ↓
  全部就绪
```

### Slave（每台翻译机器）

**先确认 Ollama + `hunyuan-mt:1.8b-q4` 模型已就绪**（见上一节），然后：

```bash
install_slave.bat
```

脚本会**自动完成**：
1. 检测 Python 64-bit
2. 装 pip 依赖（fastapi uvicorn httpx pydantic pyyaml）
3. 检测/启动 Ollama + 确认 `hunyuan-mt:1.8b-q4` 模型存在
4. 后台启动 Slave 服务（端口 8001，日志在 `logs/slave.log`）
5. 并行翻译 5 段自测
6. ✅ 通过后显示本机 IP

### Master（路由机器）

```bash
install_master.bat
```

脚本会**自动完成**：
1. 检测 Python 64-bit
2. 装 pip 依赖
3. 后台启动 Master（端口 8000，日志在 `logs/master.log`）
4. 自测 `/health` 端点
5. **逐行提示输入 Slave IP**（如 `192.168.1.101:8001`，回车结束）
6. 写入 `master/config.yaml` 并 ping 验证

### 客户端调用

```bash
pip install localtrans
localtrans-save http://192.168.1.100:8000
```

```python
from localtrans import translate
print(translate("Hello world", target_lang="zh"))  # 你好世界
```

## 使用

### 方式一：Python 客户端

```python
from client import TranslatorClient

client = TranslatorClient("http://<Master_IP>:8000")

# 简单翻译
result = client.translate("Hello world", target_lang="zh")
print(result.translated_text)  # 你好世界

# 带术语表
result = client.translate(
    "We use PyTorch for deep learning research.",
    target_lang="zh",
    glossary={"PyTorch": "PyTorch框架", "deep learning": "深度学习"}
)
print(result.translated_text)

# 批量翻译
texts = ["Hello", "Good morning", "Thank you"]
for text in texts:
    r = client.translate(text, target_lang="zh")
    print(r.translated_text)
```

### 方式二：curl / PowerShell

```powershell
curl -X POST http://localhost:8000/translate ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Hello world\",\"target_lang\":\"zh\"}"
```

### 方式三：浏览器

```
http://localhost:8000/docs
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/translate` | POST | 翻译 |
| `/health` | GET | 所有节点健康状态 |
| `/slaves` | GET | 从机列表 |
| `/models` | GET | 所有从机的模型 |

## 常见问题

### Q: Ollama 没装怎么办？

**A**: Slave 依赖 Ollama 来做推理，没装的话暂时无法翻译。可以到这里安装：https://ollama.com/download

### Q: `ollama pull hunyuan-mt:1.8b-q4` 下载太慢 / 失败

**A**: 用 HuggingFace 镜像下载 GGUF 再导入：

```powershell
curl -L -o HY-MT1.5-1.8B-Q4_K_M.gguf ^
  "https://hf-mirror.com/AngelSlim/Hy-MT1.5-1.8B-Q4_K_M/resolve/main/Hy-MT1.5-1.8B-Q4_K_M.gguf"
ollama create hunyuan-mt:1.8b-q4 -f Modelfile.hunyuan
```

### Q: Slave 报错 "model not found"

**A**: 确认以下 3 处的模型名保持一致即可：

1. `ollama list` 显示的模型名
2. `slave/config.yaml` 第 13 行 `ollama.model`
3. `install_slave.bat` 第 19 行 `set OLLAMA_MODEL=`

本项目默认使用 `hunyuan-mt:1.8b-q4`。

### Q: Master 连不上 Slave

**A**: 确认在同一局域网，防火墙放行端口：

```powershell
New-NetFirewallRule -DisplayName "DistributedTranslator" -Direction Inbound -LocalPort 8000,8001,8002 -Protocol TCP -Action Allow
```

### Q: 模型加载报错 "OutOfMemory"

**A**: 试试更小的量化版本：

| 量化 | 大小 | 内存需求 |
|------|------|---------|
| Q4_K_M（推荐） | 1.1GB | ~2GB |
| Q2_K | 0.6GB | ~1GB |
| FP16 | 3.6GB | ~4GB |

### Q: 翻译结果为空或乱码

**A**: 检查 Ollama 是否在跑：

```powershell
ollama list
ollama ps
```

### Q: 安装依赖时报错 "no space on device"

**A**: 清理磁盘空间：

```powershell
Remove-Item "$env:USERPROFILE\.conda\pkgs" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue
```

## 性能参考

> 测试：Intel i5-10210U + 8GB 内存 + Ollama + `hunyuan-mt:1.8b-q4`

| 场景 | 耗时 |
|------|------|
| 单句英→中 | ~2s |
| 单台机器 5 句并行（各 100 词） | ~20s |

每多加一台 Slave 机器，翻译吞吐量大致线性提升。

## 项目结构

```
分布式翻译/
├── master/              # 主机（路由 + 健康检查）
├── slave/               # 从机（调用 Ollama 做翻译）
├── common/              # 共享协议（schemas.py）
├── localtrans/          # Python 客户端包（pip install localtrans）
├── scripts/             # 自检辅助脚本
├── install_slave.bat    # Slave 6 步自检 + 启动
├── install_master.bat   # Master 配置 + 启动
├── Modelfile.hunyuan    # Ollama 混元模型导入示例
├── logs/                # 运行日志（自动创建，git 忽略）
└── README.md            # English version
```
