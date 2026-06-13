"""
分布式翻译器 Python 客户端
提供简洁的 Python API 调用 Master 翻译服务

用法:
    from localtrans import TranslatorClient

    client = TranslatorClient("http://localhost:8000")
    result = client.translate("Hello world", target_lang="zh")
    print(result.translated_text)
"""

from typing import Optional, Dict, List, Iterator
import httpx


class TranslationResult:
    """翻译结果封装"""
    def __init__(self, data: dict):
        self.translated_text: str = data.get("translated_text", "")
        self.model: str = data.get("model", "")
        self.slave_name: Optional[str] = data.get("slave_name")
        self.raw: dict = data

    def __repr__(self):
        return f"TranslationResult(text={self.translated_text!r}, model={self.model!r})"


class TranslatorClient:
    """
    分布式翻译器客户端

    Args:
        base_url: Master 服务地址，如 "http://localhost:8000"
        timeout: HTTP 请求超时（秒）
    """

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def translate(
        self,
        text: str,
        target_lang: str = "zh",
        source_lang: str = "auto",
        glossary: Optional[Dict[str, str]] = None,
        stream: bool = False,
        max_new_tokens: Optional[int] = None,
    ) -> TranslationResult:
        """
        调用翻译服务（同步）

        Args:
            text: 待翻译文本
            target_lang: 目标语言代码，如 zh, en, ja, fr
            source_lang: 源语言代码，默认 auto 自动检测
            glossary: 术语表，如 {"PyTorch": "PyTorch框架"}
            stream: 是否流式返回（当前仅支持非流式封装）
            max_new_tokens: 最大生成 token 数

        Returns:
            TranslationResult: 翻译结果对象
        """
        payload = {
            "text": text,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "stream": stream,
        }
        if glossary is not None:
            payload["glossary"] = glossary
        if max_new_tokens is not None:
            payload["max_new_tokens"] = max_new_tokens

        r = self._client.post(f"{self.base_url}/translate", json=payload)
        r.raise_for_status()
        return TranslationResult(r.json())

    def translate_stream(
        self,
        text: str,
        target_lang: str = "zh",
        source_lang: str = "auto",
        glossary: Optional[Dict[str, str]] = None,
        max_new_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        """
        流式翻译（返回生成文本的迭代器）

        Yields:
            str: 逐段生成的翻译文本
        """
        payload = {
            "text": text,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "stream": True,
        }
        if glossary is not None:
            payload["glossary"] = glossary
        if max_new_tokens is not None:
            payload["max_new_tokens"] = max_new_tokens

        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", f"{self.base_url}/translate", json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk.strip():
                            yield chunk

    def health(self) -> dict:
        """查询 Master 健康状态及从机列表"""
        r = self._client.get(f"{self.base_url}/health")
        r.raise_for_status()
        return r.json()

    def list_recommended_models(self) -> List[dict]:
        """获取推荐模型列表"""
        r = self._client.get(f"{self.base_url}/models/recommendations")
        r.raise_for_status()
        return r.json().get("recommended_models", [])

    def download_model(self, model_id: str, target_slaves: Optional[List[str]] = None) -> dict:
        """
        向从机下发模型下载指令

        Args:
            model_id: HuggingFace 模型 ID
            target_slaves: 目标从机名列表，None 表示所有从机
        """
        params = {"model_id": model_id}
        if target_slaves is not None:
            params["target_slaves"] = target_slaves
        r = self._client.post(f"{self.base_url}/models/download", params=params)
        r.raise_for_status()
        return r.json()

    def load_model(self, model_id: str, slave_name: Optional[str] = None) -> dict:
        """
        指定从机加载模型

        Args:
            model_id: 模型 ID
            slave_name: 从机名，None 表示所有从机
        """
        params = {"model_id": model_id}
        if slave_name is not None:
            params["slave_name"] = slave_name
        r = self._client.post(f"{self.base_url}/models/load", params=params)
        r.raise_for_status()
        return r.json()

    def unload_model(self, slave_name: Optional[str] = None) -> dict:
        """卸载从机模型（释放内存/显存）"""
        params = {}
        if slave_name is not None:
            params["slave_name"] = slave_name
        r = self._client.post(f"{self.base_url}/models/unload", params=params)
        r.raise_for_status()
        return r.json()

    def close(self):
        """关闭 HTTP 客户端"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
