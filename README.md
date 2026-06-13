# Local Distributed Translation

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

```bash
install_slave.bat
```

脚本会**自动完成**：
1. 检测 Python 64-bit
2. 装 pip 依赖
3. 检测/启动 Ollama
4. 下载混元 1.8B Q4 模型
5. 后台启动 Slave 服务
6. 并行翻译 5 段自测
7. ✅ 通过后显示本机 IP

### Master（路由机器）

```bash
install_master.bat
```

脚本会**自动完成**：
1. 检测 Python 64-bit
2. 装 pip 依赖
3. 后台启动 Master
4. 自测 `/health` 端点
5. **逐行提示输入 Slave IP**（如 `192.168.1.101:8001`，回车结束）
6. 写入 `master/config.yaml` 并 ping 验证

### 客户端调用

```bash
# 在其他机器上安装（需要能访问 Master）
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
├── localtrans/          # Python 客户端包（pip install localtrans）
├── scripts/             # 自检辅助脚本
├── install_slave.bat    # Slave 6 步自检 + 启动
├── install_master.bat   # Master 配置 + 启动
├── Modelfile.hunyuan    # Ollama 混元模型示例
├── logs/                # 运行日志（自动创建，git 忽略）
└── README_en.md         # English version
```
