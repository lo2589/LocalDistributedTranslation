# -*- coding: utf-8 -*-
"""
分布式翻译器 - 主机 (Master)
接收翻译请求，负载均衡分发到多个从机节点，支持流式与非流式返回
新增：模型下载/加载/卸载的统一控制接口，推荐模型列表
"""

import os
import sys
import yaml
import asyncio
import httpx
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.schemas import TranslateRequest, SlaveInfo

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import uvicorn

# ==================== 全局状态 ====================
slaves: List[SlaveInfo] = []
slave_index: int = 0
lock = asyncio.Lock()
client: httpx.AsyncClient = None
cfg: dict = {}
recommended_models: list = []


# ==================== 负载均衡 ====================
def pick_slave() -> Optional[SlaveInfo]:
    """轮询选择健康的从机节点"""
    global slave_index
    healthy = [s for s in slaves if s.healthy]
    if not healthy:
        return None
    idx = slave_index % len(healthy)
    slave_index += 1
    return healthy[idx]


def get_slave_by_name(name: str) -> Optional[SlaveInfo]:
    """按名称获取从机"""
    for s in slaves:
        if s.name == name:
            return s
    return None


# ==================== 健康检查 ====================
async def health_checker():
    """后台任务：定时探测各从机存活状态"""
    interval = cfg.get("health_check", {}).get("interval", 30)
    timeout = cfg.get("health_check", {}).get("timeout", 5)

    while True:
        await asyncio.sleep(interval)
        for s in slaves:
            try:
                r = await client.get(
                    f"{s.url}/health",
                    timeout=timeout,
                )
                data = r.json()
                s.healthy = data.get("model_loaded", False)
                s.last_check = datetime.now().isoformat()
                s.model_name = data.get("model_name")
            except Exception as e:
                s.healthy = False
                s.last_check = datetime.now().isoformat()
                print(f"[{datetime.now().isoformat()}] [健康检查] {s.name} 异常: {e}")


# ==================== FastAPI 生命周期 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global slaves, client, cfg, recommended_models

    config_path = os.environ.get(
        "MASTER_CONFIG",
        os.path.join(os.path.dirname(__file__), "config.yaml"),
    )
    with open(config_path, "r", encoding="utf-8") as f:
        full_cfg = yaml.safe_load(f)
        cfg = full_cfg["master"]

    client = httpx.AsyncClient(timeout=300.0)
    slaves = [SlaveInfo(**s) for s in cfg["slaves"]]
    recommended_models = cfg.get("recommended_models", [])

    # 启动后先执行一次健康检查，确认初始状态
    for s in slaves:
        try:
            r = await client.get(f"{s.url}/health", timeout=5)
            data = r.json()
            s.healthy = data.get("model_loaded", False)
            s.model_name = data.get("model_name")
        except Exception as e:
            s.healthy = False
            print(f"[{datetime.now().isoformat()}] [启动检查] {s.name} 不可达: {e}")
        s.last_check = datetime.now().isoformat()

    asyncio.create_task(health_checker())
    print(f"[{datetime.now().isoformat()}] [Master] 已注册 {len(slaves)} 个从机节点")
    if recommended_models:
        print(f"[{datetime.now().isoformat()}] [Master] 已加载 {len(recommended_models)} 个推荐模型配置")

    yield

    await client.aclose()
    print("[Master] 服务已关闭")


app = FastAPI(title="分布式翻译主机", lifespan=lifespan)


# ==================== 翻译接口 ====================
@app.post("/translate")
async def translate(req: TranslateRequest):
    """
    翻译入口
    - 非流式：主机等待从机完成后一次性返回 JSON
    - 流式：主机直接透传从机的 SSE 流，降低延迟
    """
    slave = pick_slave()
    if slave is None:
        return {"error": "当前没有可用的从机节点，请检查 slave 服务状态", "status": "error"}

    url = f"{slave.url}/translate"
    payload = req.dict()

    if req.stream:
        async def proxy_stream():
            async with client.stream("POST", url, json=payload) as response:
                async for chunk in response.aiter_text():
                    yield chunk

        return StreamingResponse(
            proxy_stream(),
            media_type="text/event-stream",
            headers={"X-Slave-Name": slave.name},
        )

    try:
        r = await client.post(url, json=payload)
        data = r.json()
    except Exception as e:
        return {"error": f"请求从机失败: {e}", "status": "error", "slave_name": slave.name}

    if "translated_text" in data:
        data["slave_name"] = slave.name
    return data


# ==================== 模型管理接口（主机控制面） ====================
@app.get("/models/recommendations")
async def list_recommended_models():
    """返回内置的推荐模型列表（含内存占用参考）"""
    return {"recommended_models": recommended_models}


@app.get("/models")
async def list_models():
    """聚合查询所有从机的模型状态"""
    results = {}
    for s in slaves:
        if not s.healthy:
            results[s.name] = {"healthy": False, "error": "从机离线"}
            continue
        try:
            r = await client.get(f"{s.url}/models", timeout=10)
            results[s.name] = r.json()
        except Exception as e:
            results[s.name] = {"error": str(e)}
    return results


@app.post("/models/download")
async def download_model(model_id: str, target_slaves: Optional[List[str]] = None):
    """
    向指定从机（或全部）发送模型下载指令
    target_slaves: 从机名称列表，为空则下发给所有健康从机
    """
    targets = [s for s in slaves if s.healthy and (not target_slaves or s.name in target_slaves)]
    if not targets:
        return {"error": "没有可用的目标从机", "status": "error"}

    results = []
    for s in targets:
        try:
            r = await client.post(f"{s.url}/models/download", params={"model_id": model_id}, timeout=10)
            results.append({"slave": s.name, "result": r.json()})
        except Exception as e:
            results.append({"slave": s.name, "error": str(e)})

    return {"model_id": model_id, "targets": [t.name for t in targets], "results": results}


@app.post("/models/load")
async def load_model_on_slave(model_id: str, slave_name: str):
    """指定某个从机加载某个模型（自动卸载旧模型）"""
    slave = get_slave_by_name(slave_name)
    if not slave or not slave.healthy:
        return {"error": f"从机 {slave_name} 不存在或不可用", "status": "error"}
    try:
        r = await client.post(f"{slave.url}/models/load", params={"model_id": model_id}, timeout=120)
        return r.json()
    except Exception as e:
        return {"error": str(e), "status": "error"}


@app.post("/models/unload")
async def unload_model_on_slave(slave_name: str):
    """指定某个从机卸载模型，释放资源"""
    slave = get_slave_by_name(slave_name)
    if not slave or not slave.healthy:
        return {"error": f"从机 {slave_name} 不存在或不可用", "status": "error"}
    try:
        r = await client.post(f"{slave.url}/models/unload", timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e), "status": "error"}


# ==================== 状态查询 ====================
@app.get("/health")
async def health():
    """查看主机及所有从机的健康状态"""
    return {
        "role": "master",
        "slaves": [s.dict() for s in slaves],
        "total": len(slaves),
        "healthy_count": sum(1 for s in slaves if s.healthy),
    }


@app.get("/slaves")
async def list_slaves():
    """列出所有已配置的从机节点"""
    return [s.dict() for s in slaves]


# ==================== 入口 ====================
def main():
    config_path = os.environ.get(
        "MASTER_CONFIG",
        os.path.join(os.path.dirname(__file__), "config.yaml"),
    )
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)["master"]
    host = cfg.get("host", "0.0.0.0")
    port = cfg.get("port", 8000)
    uvicorn.run(app, host=host, port=port, ws="none")


if __name__ == "__main__":
    main()
