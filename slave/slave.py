# -*- coding: utf-8 -*-
"""
分布式翻译器 - 从机 (Slave)
负责加载本地模型，暴露 HTTP API 供主机调用
新增：模型下载、切换、卸载管理接口
"""

import os
import sys
import yaml
import logging
import uvicorn
import httpx
import asyncio
import gc
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

# ===== 统一日志配置（所有输出进 logs/slave.log + stderr）=====
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_PATH = os.path.join(_LOG_DIR, "slave.log")

try:
    open(_LOG_PATH, "w").close()
except Exception:
    pass

# Python 3.7 兼容：basicConfig 不支持 force，手动清理 root handlers
_root = logging.getLogger()
for _h in list(_root.handlers):
    try:
        _h.close()
    except Exception:
        pass
    _root.removeHandler(_h)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [Slave] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("slave")

# 让 slave 能引用上层的 common
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.schemas import TranslateRequest, TranslateResponse, HealthResponse

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

# transformers / torch 延迟导入，避免服务启动时因环境缺失而崩溃
torch = None
AutoTokenizer = None
AutoModelForCausalLM = None
TextIteratorStreamer = None
GenerationConfig = None
snapshot_download = None


def _ensure_imports():
    """确保 heavy imports 已加载，在需要模型推理时调用"""
    global torch, AutoTokenizer, AutoModelForCausalLM, TextIteratorStreamer, GenerationConfig, snapshot_download
    if torch is not None:
        return
    import torch as _torch
    torch = _torch
    from transformers import (
        AutoTokenizer as _AutoTokenizer,
        AutoModelForCausalLM as _AutoModelForCausalLM,
        TextIteratorStreamer as _TextIteratorStreamer,
        GenerationConfig as _GenerationConfig,
    )
    from huggingface_hub import snapshot_download as _snapshot_download
    AutoTokenizer = _AutoTokenizer
    AutoModelForCausalLM = _AutoModelForCausalLM
    TextIteratorStreamer = _TextIteratorStreamer
    GenerationConfig = _GenerationConfig
    snapshot_download = _snapshot_download

# ==================== 全局状态 ====================
tokenizer = None
model = None
model_name = None
device_type = None
cfg = None
executor = ThreadPoolExecutor(max_workers=2)  # 一个给生成，一个给下载

# 模型管理状态
local_models: dict = {}      # model_id -> {"path": str, "status": str}
download_tasks: dict = {}    # model_id -> {"status": str, "error": str|None}
model_cache_dir: str = ""



# ==================== 模型管理 ====================
def get_hf_cache_dir():
    """获取 HuggingFace 默认缓存目录"""
    return os.path.expanduser("~/.cache/huggingface/hub")

def scan_local_models(cache_dir: str) -> dict:
    """扫描本地缓存，返回已下载的模型列表（无需 torch）"""
    models = {}
    cache = Path(cache_dir)
    if not cache.exists():
        return models
    for item in cache.iterdir():
        if item.is_dir() and item.name.startswith("models--"):
            # 格式: models--Qwen--Qwen2.5-1.5B-Instruct
            encoded = item.name[len("models--"):]
            parts = encoded.split("--")
            # 第一个 -- 之前是 namespace，之后是 model_name
            # 例如: Qwen--Qwen2.5-1.5B-Instruct -> Qwen/Qwen2.5-1.5B-Instruct
            if len(parts) >= 2:
                model_id = f"{parts[0]}/{'/'.join(parts[1:])}"
            else:
                model_id = encoded
            models[model_id] = {"path": str(item), "status": "downloaded"}
    return models

def _download_model_task(model_id: str, cache_dir: str):
    """在线程中执行模型下载"""
    _ensure_imports()
    global local_models, download_tasks
    try:
        download_tasks[model_id] = {"status": "downloading", "error": None}
        logger.info(f"开始下载模型: {model_id}")
        path = snapshot_download(repo_id=model_id, cache_dir=cache_dir, local_files_only=False)
        local_models[model_id] = {"path": path, "status": "downloaded"}
        download_tasks[model_id] = {"status": "done", "error": None}
        logger.info(f"模型下载完成: {model_id}")
    except Exception as e:
        download_tasks[model_id] = {"status": "error", "error": str(e)}
        logger.warning(f"模型下载失败: {model_id}, 错误: {e}")

def unload_model():
    """卸载当前模型，释放显存/内存"""
    global tokenizer, model, model_name, device_type
    if model is not None:
        del model
        model = None
    if tokenizer is not None:
        del tokenizer
        tokenizer = None
    gc.collect()
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception as e:
        logger.warning(f"CUDA 清理跳过: {e}")
    logger.info("旧模型已卸载，显存/内存已清理")

def load_model(config: dict):
    _ensure_imports()
    global tokenizer, model, model_name, device_type, cfg
    cfg = config
    mc = config["model"]
    model_path = mc["path"]
    model_name = model_path.split("/")[-1]

    logger.info(f"正在加载模型: {model_path}")

    # 解析 torch_dtype
    dtype_map = {
        "float16": torch.float16,
        "float32": torch.float32,
        "bfloat16": torch.bfloat16,
    }
    dtype_str = mc.get("torch_dtype", "auto")
    torch_dtype = dtype_map.get(dtype_str, "auto")

    load_in_8bit = mc.get("load_in_8bit", False)
    load_in_4bit = mc.get("load_in_4bit", False)

    tokenizer_kwargs = {
        "pretrained_model_name_or_path": model_path,
        "trust_remote_code": mc.get("trust_remote_code", True),
    }
    model_kwargs = {
        "pretrained_model_name_or_path": model_path,
        "trust_remote_code": mc.get("trust_remote_code", True),
        "torch_dtype": torch_dtype,
    }

    # 量化配置
    if load_in_8bit or load_in_4bit:
        try:
            from transformers import BitsAndBytesConfig
            if load_in_4bit:
                model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True)
            elif load_in_8bit:
                model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
            if "torch_dtype" in model_kwargs:
                del model_kwargs["torch_dtype"]
        except Exception as e:
            logger.warning(f"量化库不可用或配置失败，回退到普通加载: {e}")

    # 统一使用 device_map 与低内存加载
    model_kwargs["device_map"] = mc.get("device_map", "auto")
    model_kwargs["low_cpu_mem_usage"] = True

    tokenizer = AutoTokenizer.from_pretrained(**tokenizer_kwargs)
    model = AutoModelForCausalLM.from_pretrained(**model_kwargs)

    # 确定设备信息
    if hasattr(model, "hf_device_map"):
        device_type = str(model.hf_device_map)
    elif hasattr(model, "device"):
        device_type = str(model.device)
    else:
        device_type = "unknown"

    logger.info(f"模型加载完成 | 名称: {model_name} | 设备: {device_type}")


# ==================== Prompt 构建 ====================
def build_messages(text: str, source_lang: str, target_lang: str, glossary: dict = None) -> list:
    tc = cfg["translation"]
    system_prompt = tc.get("system_prompt", "")

    tpl = tc.get("user_template_auto" if source_lang == "auto" else "user_template", tc.get("user_template"))

    lang_map = {
        "zh": "中文", "en": "英文", "ja": "日文", "ko": "韩文",
        "fr": "法文", "de": "德文", "es": "西班牙文", "ru": "俄文",
        "it": "意大利文", "pt": "葡萄牙文", "ar": "阿拉伯文",
    }
    sl = lang_map.get(source_lang, source_lang)
    tl = lang_map.get(target_lang, target_lang)

    user_prompt = tpl.format(source_lang=sl, target_lang=tl, text=text)

    # 注入术语表
    if glossary:
        glossary_lines = "\n".join([f"- {src} -> {tgt}" for src, tgt in glossary.items()])
        user_prompt = (
            f"Please strictly follow the glossary below during translation:\n"
            f"{glossary_lines}\n\n"
            f"{user_prompt}"
        )

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


# ==================== FastAPI 生命周期 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global local_models, model_cache_dir, cfg

    config_path = os.environ.get(
        "SLAVE_CONFIG",
        os.path.join(os.path.dirname(__file__), "config.yaml"),
    )
    with open(config_path, "r", encoding="utf-8") as f:
        full_cfg = yaml.safe_load(f)
        cfg = full_cfg["slave"]

    model_cache_dir = cfg.get("model_cache_dir", get_hf_cache_dir())
    local_models = scan_local_models(model_cache_dir)
    logger.info(f"扫描到本地模型: {list(local_models.keys())}")

    # 尝试加载初始模型；失败则继续运行，等待后续 /models/load
    try:
        load_model(cfg)
    except Exception as e:
        logger.warning(f"初始模型加载失败（可能尚未下载）: {e}")
        logger.info("提示: 可通过 /models/download 下载模型，再通过 /models/load 加载")

    yield
    executor.shutdown(wait=False)
    unload_model()
    logger.info("服务已关闭")


app = FastAPI(title="分布式翻译从机", lifespan=lifespan)


# ==================== Ollama 翻译后端 ====================
ollama_http_client: httpx.Client = None


def _ollama_client(base_url: str = "http://localhost:11434") -> httpx.Client:
    """获取或创建 Ollama HTTP 客户端"""
    global ollama_http_client
    if ollama_http_client is None:
        ollama_http_client = httpx.Client(base_url=base_url, timeout=180.0, trust_env=False)
    return ollama_http_client


@app.post("/ollama/translate")
async def ollama_translate(req: TranslateRequest):
    """用 Ollama 模型翻译（绕过 transformers/pytorch），直接调 Ollama /api/chat"""
    ollama_cfg = (cfg.get("ollama", {}) if cfg else {}) or {}
    model_name = ollama_cfg.get("model", "tencent/hy-mt1.5-1.8b-q4")
    base_url = ollama_cfg.get("base_url", "http://localhost:11434")

    lang_map = {
        "zh": "中文", "en": "英文", "ja": "日文", "ko": "韩文",
        "fr": "法文", "de": "德文", "es": "西班牙文", "ru": "俄文",
        "it": "意大利文", "pt": "葡萄牙文", "ar": "阿拉伯文",
    }
    target_lang = lang_map.get(req.target_lang, req.target_lang)
    system_prompt = f"你是一个专业翻译助手，只输出翻译结果，严格翻译成{target_lang}。"

    if req.glossary:
        lines = "\n".join([f"- {s} -> {t}" for s, t in req.glossary.items()])
        system_prompt += f"\n\n严格遵循术语表：\n{lines}"

    client = _ollama_client(base_url)
    try:
        r = client.post(
            "/api/chat",
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": req.text},
                ],
                "stream": False,
                "options": {"num_predict": req.max_new_tokens or 128, "temperature": 0.3},
            },
        )
        r.raise_for_status()
        result = r.json()
        translated = result.get("message", {}).get("content", "") or result.get("response", "")
        return {"translated_text": translated, "model": model_name, "backend": "ollama"}
    except Exception as e:
        return {"error": f"Ollama 请求失败: {e}", "status": "error"}


@app.post("/ollama/translate/stream")
async def ollama_translate_stream(req: TranslateRequest):
    """流式 Ollama 翻译（同步 httpx.Client，FastAPI StreamingResponse 支持）"""
    ollama_cfg = (cfg.get("ollama", {}) if cfg else {}) or {}
    model_name = ollama_cfg.get("model", "tencent/hy-mt1.5-1.8b-q4")
    base_url = ollama_cfg.get("base_url", "http://localhost:11434")

    lang_map = {
        "zh": "中文", "en": "英文", "ja": "日文", "ko": "韩文",
        "fr": "法文", "de": "德文", "es": "西班牙文", "ru": "俄文",
        "it": "意大利文", "pt": "葡萄牙文", "ar": "阿拉伯文",
    }
    target_lang = lang_map.get(req.target_lang, req.target_lang)
    system_prompt = f"你是一个专业翻译助手，只输出翻译结果，严格翻译成{target_lang}。"
    if req.glossary:
        lines = "\n".join([f"- {s} -> {t}" for s, t in req.glossary.items()])
        system_prompt += f"\n\n严格遵循术语表：\n{lines}"

    def event_generator():
        try:
            client = httpx.Client(base_url=base_url, timeout=180.0, trust_env=False)
            with client.stream("POST", "/api/chat", json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": req.text},
                ],
                "stream": True,
                "options": {"num_predict": req.max_new_tokens or 128},
            }) as resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        import json
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield f"data: {content}\n\n"
                        if data.get("done"):
                            yield "data: [DONE]\n\n"
                            break
                    except Exception:
                        pass
        except Exception as e:
            yield f"data: [ERROR] {e}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ==================== 模型管理接口 ====================
@app.get("/models")
async def list_models():
    """列出本地已下载的模型及当前加载状态"""
    return {
        "local_models": local_models,
        "download_tasks": download_tasks,
        "current_model": model_name if model else None,
        "model_loaded": model is not None,
        "cache_dir": model_cache_dir,
    }


@app.post("/models/download")
async def download_model(model_id: str):
    """后台下载指定模型（通过 HuggingFace）"""
    if model_id in local_models and local_models[model_id].get("status") == "downloaded":
        return {"status": "already_exists", "model_id": model_id}
    if model_id in download_tasks and download_tasks[model_id].get("status") == "downloading":
        return {"status": "downloading", "model_id": model_id}

    # 在线程池中启动下载
    loop = asyncio.get_event_loop()
    loop.run_in_executor(executor, _download_model_task, model_id, model_cache_dir)
    return {"status": "started", "model_id": model_id}


@app.post("/models/load")
async def load_model_endpoint(model_id: str):
    """加载指定模型（会自动卸载旧模型）"""
    global cfg
    try:
        return await _do_load(model_id)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "model_id": model_id, "error": str(e)}


async def _do_load(model_id: str):
    """加载指定模型（会自动卸载旧模型）"""
    global cfg

    # 如果 model_id 是本地缓存中已扫描到的，或者即使没扫描到也尝试让 transformers 从缓存/网络加载
    if model_id not in local_models:
        # 再次扫描，可能刚刚下载完
        local_models.update(scan_local_models(model_cache_dir))

    # 更新配置中的模型路径
    cfg["model"]["path"] = model_id

    # 先卸载旧模型
    try:
        unload_model()
    except Exception as e:
        import traceback
        logger.warning(f"unload_model 失败（忽略）: {e}")
        traceback.print_exc()

    try:
        load_model(cfg)
        return {
            "status": "loaded",
            "model_id": model_id,
            "model_name": model_name,
            "device": device_type,
        }
    except Exception as e:
        import traceback
        logger.warning(f"load_model 失败: {e}")
        traceback.print_exc()
        return {"status": "error", "model_id": model_id, "error": str(e)}


@app.post("/models/unload")
async def unload_model_endpoint():
    """卸载当前模型，释放资源"""
    unload_model()
    return {"status": "unloaded", "previous_model": model_name}


# ==================== 翻译接口 ====================
@app.post("/translate")
async def translate(req: TranslateRequest):
    # 优先使用本地 transformers 模型
    if model is not None and tokenizer is not None:
        return await _translate_transformers(req)

    # 回落到 Ollama 后端
    ollama_ok, _ = _ollama_available()
    if ollama_ok:
        return await ollama_translate(req)

    return {"error": "模型未加载，且 Ollama 后端不可用", "status": "error"}


async def _translate_transformers(req: TranslateRequest):
    """用本地 transformers 模型翻译"""

    messages = build_messages(req.text, req.source_lang, req.target_lang, glossary=req.glossary)

    if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template:
        # 混元翻译模型等专业模型通常不需要 generation prompt（直接输出翻译结果）
        # 通用对话模型（Qwen/Llama）需要 generation prompt 来触发 assistant 回复
        mc = cfg["model"]
        add_gen = mc.get("add_generation_prompt")
        if add_gen is None:
            # 根据 model_type 推断：translation 类型默认 False，chat 类型默认 True
            add_gen = mc.get("model_type", "chat") == "chat"
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=add_gen,
        )
    else:
        parts = []
        for m in messages:
            if m["role"] == "system":
                parts.append(f"System: {m['content']}")
            else:
                parts.append(f"User: {m['content']}")
        parts.append("Assistant: ")
        prompt = "\n".join(parts)

    inputs = tokenizer(prompt, return_tensors="pt")

    if not hasattr(model, "hf_device_map") and hasattr(model, "device"):
        inputs = {k: v.to(model.device) for k, v in inputs.items()}

    max_new = req.max_new_tokens or cfg["translation"].get("max_new_tokens", 512)
    gen_config = GenerationConfig(
        max_new_tokens=max_new,
        do_sample=False,
        pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
    )

    # ---------- 流式模式 ----------
    if req.stream:
        streamer = TextIteratorStreamer(
            tokenizer, skip_prompt=True, skip_special_tokens=True
        )
        generation_kwargs = dict(
            inputs, streamer=streamer, generation_config=gen_config
        )

        def generate_in_thread():
            model.generate(**generation_kwargs)

        Thread(target=generate_in_thread, daemon=True).start()

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def consume_streamer():
            for text in streamer:
                if text:
                    loop.call_soon_threadsafe(queue.put_nowait, text)
            loop.call_soon_threadsafe(queue.put_nowait, None)

        Thread(target=consume_streamer, daemon=True).start()

        async def event_stream():
            while True:
                token = await queue.get()
                if token is None:
                    break
                yield f"data: {token}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(), media_type="text/event-stream"
        )

    # ---------- 非流式模式 ----------
    def _generate_sync():
        with torch.no_grad():
            outputs = model.generate(**inputs, generation_config=gen_config)
        input_len = inputs["input_ids"].shape[1]
        generated_ids = outputs[0][input_len:]
        return tokenizer.decode(generated_ids, skip_special_tokens=True)

    translated = await asyncio.get_event_loop().run_in_executor(executor, _generate_sync)

    return TranslateResponse(
        translated_text=translated.strip(),
        model=model_name,
    )


# ==================== 健康检查 ====================
def _ollama_available() -> (bool, str):
    """检查 Ollama 后端是否可用（无需 transformers/torch）"""
    try:
        import httpx
        base_url = None
        ollama_model = None
        if cfg and "ollama" in cfg and isinstance(cfg["ollama"], dict):
            base_url = cfg["ollama"].get("base_url", "http://localhost:11434")
            ollama_model = cfg["ollama"].get("model", "")
        else:
            base_url = "http://localhost:11434"
            ollama_model = ""

        client = httpx.Client(base_url=base_url, timeout=5, trust_env=False)
        r = client.get("/api/tags")
        if r.status_code != 200:
            return False, ""
        data = r.json()
        models = data.get("models", [])
        if ollama_model:
            for m in models:
                if m.get("name", "").startswith(ollama_model):
                    return True, ollama_model
            # 配置的模型不在列表
            return False, ollama_model
        # 无特定模型配置，只要 Ollama 有任何模型即可用
        if models:
            return True, models[0].get("name", "")
        return False, ""
    except Exception:
        return False, ""


@app.get("/health")
async def health():
    # 1) 本地 transformers 模型
    if model is not None:
        return HealthResponse(
            status="ok",
            model_loaded=True,
            model_name=model_name,
            device=device_type,
        )

    # 2) Ollama 后端（无需本地模型）
    ollama_ok, ollama_model_name = _ollama_available()
    if ollama_ok:
        return HealthResponse(
            status="ok",
            model_loaded=True,
            model_name="ollama:" + (ollama_model_name or "default"),
            device="ollama",
        )

    # 3) 服务运行但无可推理后端
    return HealthResponse(
        status="idle",
        model_loaded=False,
        model_name=None,
        device=None,
    )


# ==================== 入口 ====================
def main():
    config_path = os.environ.get(
        "SLAVE_CONFIG",
        os.path.join(os.path.dirname(__file__), "config.yaml"),
    )
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)["slave"]
    host = config.get("host", "0.0.0.0")
    port = config.get("port", 8001)
    uvicorn.run(app, host=host, port=port, ws="none")


if __name__ == "__main__":
    main()
