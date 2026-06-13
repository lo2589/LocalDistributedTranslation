"""
共享数据模型 / Shared Schemas
Master 与 Slave 之间的通信协议定义
"""

from typing import Optional, List, Dict
from pydantic import BaseModel


class TranslateRequest(BaseModel):
    """翻译请求"""
    text: str
    source_lang: str = "auto"      # 源语言，如 en, zh, ja
    target_lang: str = "zh"        # 目标语言
    stream: bool = False           # 是否流式返回
    max_new_tokens: Optional[int] = None  # 覆盖默认最大token数
    glossary: Optional[Dict[str, str]] = None  # 术语表：{源语言术语: 目标语言术语}


class TranslateResponse(BaseModel):
    """翻译响应（非流式）"""
    translated_text: str
    model: str                     # 实际处理请求的模型名
    slave_name: Optional[str] = None  # 处理请求的从机名


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str                    # ok / error
    model_loaded: bool
    model_name: Optional[str] = None
    device: Optional[str] = None   # cuda / cpu / mps


class SlaveInfo(BaseModel):
    """从机节点信息"""
    name: str
    url: str
    weight: int = 1
    healthy: bool = True
    last_check: Optional[str] = None
    model_name: Optional[str] = None


class MasterConfig(BaseModel):
    """主机配置结构（仅校验用）"""
    host: str
    port: int
    slaves: List[SlaveInfo]
